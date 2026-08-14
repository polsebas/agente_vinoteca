"""
Fixtures compartidos para todos los tests.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest


@pytest.fixture
def session_id() -> str:
    return f"sess_web_test_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def correlation_id() -> str:
    return f"sess_web_test_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def vino_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def mock_pg_fetch_one():
    with patch("storage.postgres.fetch_one") as mock:
        yield mock


@pytest.fixture
def mock_pg_fetch_all():
    with patch("storage.postgres.fetch_all") as mock:
        yield mock


@pytest.fixture
def mock_pg_execute():
    with patch("storage.postgres.execute") as mock:
        yield mock


@pytest.fixture
def mock_pg_fetchval():
    with patch("storage.postgres.fetchval") as mock:
        yield mock


@pytest.fixture(autouse=True)
def reset_memgraph_engine():
    """Aísla el singleton de MemGraphRAG entre tests."""
    from core.rag.memgraph_adapter import set_engine

    set_engine(None)
    yield
    set_engine(None)


@pytest.fixture(autouse=True)
def reset_observability_singletons():
    """Evita que KPIs/costos in-process se filtren entre tests."""
    from observability import reset_observability

    reset_observability()
    yield
    reset_observability()
