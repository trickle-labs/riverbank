from __future__ import annotations

import pytest
from testcontainers.postgres import PostgresContainer

# The pg-ripple image ships with pg_ripple, pg_trickle, and all required extensions.
# Until the image is published, integration tests run against standard PostgreSQL
# (sufficient for catalog migration tests that do not exercise pg-ripple SQL functions).
POSTGRES_IMAGE = "postgres:17-alpine"


@pytest.fixture(scope="session")
def postgres_container():
    """Ephemeral PostgreSQL with pg_ripple for the integration/golden test session."""
    with PostgresContainer(image=POSTGRES_IMAGE, dbname="test_riverbank") as container:
        yield container


@pytest.fixture(scope="session")
def db_dsn(postgres_container: PostgresContainer) -> str:
    """psycopg-compatible DSN for the test database."""
    url: str = postgres_container.get_connection_url()
    # testcontainers returns a SQLAlchemy URL; strip the dialect suffix
    return url.replace("postgresql+psycopg2://", "postgresql+psycopg://")
