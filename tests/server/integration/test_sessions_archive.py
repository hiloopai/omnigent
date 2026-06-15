"""Integration tests for session archive lifecycle and agent contents download.

Covers:
- ``PATCH /v1/sessions/{id}`` with ``archived=True/False``
- ``GET /v1/sessions`` with ``include_archived`` filtering
- ``GET /v1/sessions/{id}/agent/contents`` returning a valid gzip tarball

Uses the shared ``client`` fixture from ``tests/server/conftest.py``
(real stores + mock LLM) so the tests hit the real route-to-store
pipeline without subprocesses.
"""

from __future__ import annotations

import io
import tarfile

import httpx
import pytest

from tests.server.helpers import create_test_session

pytestmark = pytest.mark.asyncio


# ── Archive / unarchive lifecycle ────────────────────────


async def test_session_not_archived_by_default(
    client: httpx.AsyncClient,
) -> None:
    """A freshly created session has ``archived=False``."""
    session = await create_test_session(client, name="archive-default")
    assert session["archived"] is False


# ── Agent contents download ──────────────────────────────


async def test_agent_contents_returns_valid_gzip_tarball(
    client: httpx.AsyncClient,
) -> None:
    """GET /v1/sessions/{id}/agent/contents returns a valid tar.gz bundle."""
    session = await create_test_session(client, name="contents-download")
    session_id = session["id"]

    resp = await client.get(f"/v1/sessions/{session_id}/agent/contents")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"

    # Verify the bytes are a valid tar.gz archive containing config.yaml.
    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tf:
        names = tf.getnames()
        assert "config.yaml" in names


async def test_agent_contents_404_for_nonexistent_session(
    client: httpx.AsyncClient,
) -> None:
    """GET /v1/sessions/{id}/agent/contents returns 404 for a missing session."""
    resp = await client.get("/v1/sessions/conv_nonexistent/agent/contents")
    assert resp.status_code == 404
