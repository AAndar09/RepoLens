import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.health import get_readiness_vector_store
from app.config import get_settings
from app.database import Base, get_session
from app.main import app


class HealthyVectorStore:
    def health_check(self) -> None:
        return None


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> TestClient:
    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_readiness_vector_store] = HealthyVectorStore
    settings = get_settings()
    previous_rate_limit = settings.rate_limit_enabled
    previous_recovery = settings.recover_interrupted_jobs_on_startup
    settings.rate_limit_enabled = False
    settings.recover_interrupted_jobs_on_startup = False
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        settings.rate_limit_enabled = previous_rate_limit
        settings.recover_interrupted_jobs_on_startup = previous_recovery
        app.dependency_overrides.clear()
