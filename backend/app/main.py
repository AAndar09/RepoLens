import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.database import get_engine
from app.middleware import RateLimitMiddleware, RequestContextMiddleware, error_response
from app.observability import configure_logging
from app.services.ingestion_jobs import recover_interrupted_ingestion_jobs

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.recover_interrupted_jobs_on_startup:
            try:
                with sessionmaker(bind=get_engine(), expire_on_commit=False)() as session:
                    recovered = recover_interrupted_ingestion_jobs(session)
            except SQLAlchemyError:
                logger.warning(
                    "ingestion_job_recovery_unavailable",
                    extra={"event": "ingestion_job_recovery_unavailable"},
                    exc_info=True,
                )
            else:
                if recovered:
                    logger.warning(
                        "interrupted_ingestion_jobs_recovered",
                        extra={
                            "event": "interrupted_ingestion_jobs_recovered",
                            "job_count": recovered,
                        },
                    )
        yield

    application = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        debug=settings.debug,
        docs_url="/docs" if settings.expose_api_docs else None,
        redoc_url="/redoc" if settings.expose_api_docs else None,
        openapi_url="/openapi.json" if settings.expose_api_docs else None,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.add_middleware(RateLimitMiddleware, settings=settings)
    application.add_middleware(RequestContextMiddleware, settings=settings)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)

    @application.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return error_response(
            exc.status_code,
            f"http_{exc.status_code}",
            message,
            getattr(request.state, "request_id", "-"),
            details=exc.detail if not isinstance(exc.detail, str) else None,
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        details = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in exc.errors()
        ]
        return error_response(
            422,
            "validation_error",
            "Request validation failed",
            getattr(request.state, "request_id", "-"),
            details=details,
        )

    @application.exception_handler(Exception)
    async def unexpected_exception_handler(request: Request, exc: Exception):
        logger.exception(
            "unhandled_request_error",
            extra={"event": "unhandled_request_error", "error_type": exc.__class__.__name__},
        )
        return error_response(
            500,
            "internal_error",
            "An unexpected server error occurred",
            getattr(request.state, "request_id", "-"),
        )

    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()
