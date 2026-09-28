import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings
from app.observability import request_id_context

logger = logging.getLogger(__name__)


def error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    *,
    details: object | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    error: dict[str, object] = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if details is not None:
        error["details"] = details
    return JSONResponse({"error": error}, status_code=status_code, headers=headers)


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        candidate = request.headers.get("x-request-id", "")
        request_id = (
            candidate
            if 0 < len(candidate) <= 100 and candidate.isascii()
            else uuid.uuid4().hex
        )
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        try:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    too_large = int(content_length) > self.settings.max_request_body_bytes
                except ValueError:
                    too_large = True
                if too_large:
                    response = error_response(
                        413,
                        "request_too_large",
                        "Request body exceeds the configured limit",
                        request_id,
                    )
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
            duration_ms = round((time.perf_counter() - started) * 1_000, 3)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            if self.settings.environment.lower() == "production":
                response.headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains"
                )
            mutable_snapshot_resources = ("/retrieval-index", "/vulnerabilities")
            if (
                request.method == "GET"
                and "/snapshots/" in request.url.path
                and not request.url.path.endswith(mutable_snapshot_resources)
            ):
                response.headers.setdefault(
                    "Cache-Control",
                    f"public, max-age={self.settings.immutable_cache_max_age_seconds}",
                )
            else:
                response.headers.setdefault("Cache-Control", "no-store")
            logger.info(
                "request_completed",
                extra={
                    "event": "request_completed",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "client": request.client.host if request.client else "unknown",
                },
            )
            return response
        except Exception:
            logger.exception(
                "request_failed",
                extra={
                    "event": "request_failed",
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1_000, 3),
                },
            )
            raise
        finally:
            request_id_context.reset(token)


class InMemoryRateLimiter:
    def __init__(self, maximum_clients: int) -> None:
        self.maximum_clients = maximum_clients
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, round(events[0] + window_seconds - now))
                return False, retry_after
            events.append(now)
            if len(self._events) > self.maximum_clients:
                oldest = sorted(
                    self._events,
                    key=lambda item: self._events[item][-1] if self._events[item] else 0,
                )
                for item in oldest[: len(self._events) - self.maximum_clients]:
                    self._events.pop(item, None)
        return True, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings
        self.limiter = InMemoryRateLimiter(settings.rate_limit_max_clients)

    def _policy(self, request: Request) -> tuple[str, int, int]:
        path = request.url.path
        if request.method == "POST" and path.rstrip("/").endswith("/repositories"):
            return (
                "submission",
                self.settings.rate_limit_submission_requests,
                self.settings.rate_limit_submission_window_seconds,
            )
        if request.method == "POST" and (
            path.endswith("/ingestions") or "/ingestion-jobs" in path
        ):
            return (
                "ingestion",
                self.settings.rate_limit_ingestion_requests,
                self.settings.rate_limit_ingestion_window_seconds,
            )
        if request.method == "POST" and (
            path.endswith("/queries") or path.endswith("/investigations")
        ):
            return (
                "query",
                self.settings.rate_limit_query_requests,
                self.settings.rate_limit_query_window_seconds,
            )
        return (
            "default",
            self.settings.rate_limit_default_requests,
            self.settings.rate_limit_default_window_seconds,
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.settings.rate_limit_enabled or not request.url.path.startswith("/api/"):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        if self.settings.trust_proxy_headers:
            forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
            if forwarded:
                client = forwarded
        policy, limit, window = self._policy(request)
        allowed, retry_after = self.limiter.allow(f"{policy}:{client}", limit, window)
        if not allowed:
            request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
            return error_response(
                429,
                "rate_limit_exceeded",
                "Request rate limit exceeded",
                request_id,
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
