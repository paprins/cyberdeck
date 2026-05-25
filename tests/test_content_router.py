from __future__ import annotations
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.models.registry import Module, Registry
from app.services.registry import save_registry


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _seed_static_module(tmp_settings, module_id="first-aid", files: dict | None = None):
    save_registry(tmp_settings, Registry(modules=[
        Module(
            id=module_id, display_name="First Aid", category="medical",
            description="", latest_version="2026-05", size_gb=0.01,
            kind="static",
            signature_url="https://x/x.minisig",
            entry="index.md", active=True,
        )
    ]))
    target = tmp_settings.content_dir / module_id
    target.mkdir(parents=True, exist_ok=True)
    for name, data in (files or {"index.md": "# Hello\n\nbody"}).items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data) if isinstance(data, str) else path.write_bytes(data)


async def test_md_file_renders_html(client, tmp_settings):
    _seed_static_module(tmp_settings)
    r = await client.get("/content/first-aid/index.md")
    assert r.status_code == 200
    assert ">Hello</h1>" in r.text
    assert "<p>body</p>" in r.text
    assert "<!DOCTYPE html>" in r.text  # wrapped in base.html


async def test_non_md_file_served_raw(client, tmp_settings):
    _seed_static_module(tmp_settings, files={"data.json": '{"x":1}'})
    r = await client.get("/content/first-aid/data.json")
    assert r.status_code == 200
    assert r.text == '{"x":1}'


async def test_unknown_module_returns_404(client, tmp_settings):
    save_registry(tmp_settings, Registry())
    r = await client.get("/content/missing/index.md")
    assert r.status_code == 404


async def test_path_traversal_rejected(client, tmp_settings):
    _seed_static_module(tmp_settings)
    # FastAPI normalizes the URL path; the resolved-path check is the guard.
    r = await client.get("/content/first-aid/../../etc/passwd")
    # FastAPI / httpx may normalize; either way it must NOT return passwd.
    assert r.status_code in (400, 404)
    assert "root:" not in r.text


async def test_missing_file_returns_404(client, tmp_settings):
    _seed_static_module(tmp_settings)
    r = await client.get("/content/first-aid/missing.md")
    assert r.status_code == 404


async def test_non_static_kind_returns_404(client, tmp_settings):
    # zim module with same id; content router should refuse
    save_registry(tmp_settings, Registry(modules=[
        Module(
            id="first-aid", display_name="First Aid", category="medical",
            description="", latest_version="x", size_gb=0.01,
            checksum="sha256:abc",
        )
    ]))
    r = await client.get("/content/first-aid/index.md")
    assert r.status_code == 404
