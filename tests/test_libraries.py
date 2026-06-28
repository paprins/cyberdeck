from __future__ import annotations
import pytest
import httpx
from httpx import AsyncClient, ASGITransport

from app.main import create_app
from app.models.library import (
    Library,
    LibraryAlreadyExistsError,
    LibraryEntry,
    LibraryInvalidUrlError,
    LibraryNotFoundError,
    LibraryParseError,
    LibraryUnreachableError,
)
from app.models.registry import Module, Registry
from app.services import libraries as lib_svc
from app.services import packages as packages_svc
from app.services import registry as registry_svc


# ── Test fixtures ────────────────────────────────────────────────────────────


_OPDS_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:dc="http://purl.org/dc/terms/"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <title>Test Catalog</title>
  <opensearch:totalResults>42</opensearch:totalResults>
  <entry>
    <id>urn:uuid:e1</id>
    <title>MDWiki Medical Encyclopedia</title>
    <summary>Healthcare articles curated by WikiProjectMed</summary>
    <dc:language>eng</dc:language>
    <link rel="http://opds-spec.org/acquisition/open-access"
          type="application/x-zim"
          href="https://download.example.org/zim/mdwiki_en_all_maxi_2025-11.zim.meta4"
          length="2302838784"/>
    <link rel="http://opds-spec.org/image/thumbnail"
          href="/catalog/v2/illustration/e1/?size=48"
          type="image/png"/>
  </entry>
  <entry>
    <id>urn:uuid:e2</id>
    <title>No Acquisition Link</title>
  </entry>
</feed>"""

_META4 = b"""<?xml version="1.0" encoding="UTF-8"?>
<metalink xmlns="urn:ietf:params:xml:ns:metalink">
  <file name="mdwiki_en_all_maxi_2025-11.zim">
    <size>2302838784</size>
    <hash type="sha-256">896e15f81c68a567bd7e8979b9e6ea3df1f8359397a9ce2ac46eeb4f692cf583</hash>
    <url priority="1">https://mirror1.example.org/zim/mdwiki_en_all_maxi_2025-11.zim</url>
    <url priority="2">https://mirror2.example.org/zim/mdwiki_en_all_maxi_2025-11.zim</url>
  </file>
</metalink>"""


def _seed(tmp_settings, libraries=None, modules=None):
    tmp_settings.registry_path.parent.mkdir(parents=True, exist_ok=True)
    reg = Registry(
        
        modules=modules or [],
        libraries=libraries or [],
    )
    tmp_settings.registry_path.write_text(reg.model_dump_json())


# ── URL normalization ────────────────────────────────────────────────────────


def test_normalize_url_extracts_lang_from_fragment():
    canonical, lang = lib_svc.normalize_opds_url("https://browse.library.kiwix.org/#lang=nld")
    assert canonical == "https://browse.library.kiwix.org/catalog/v2/entries"
    assert lang == "nld"


def test_normalize_url_keeps_canonical_path():
    canonical, lang = lib_svc.normalize_opds_url(
        "https://library.kiwix.org/catalog/v2/entries"
    )
    assert canonical == "https://library.kiwix.org/catalog/v2/entries"
    assert lang is None


def test_normalize_url_rejects_non_http():
    with pytest.raises(LibraryInvalidUrlError):
        lib_svc.normalize_opds_url("ftp://example.org/")


def test_normalize_url_rejects_empty():
    with pytest.raises(LibraryInvalidUrlError):
        lib_svc.normalize_opds_url("")


# ── OPDS parsing ─────────────────────────────────────────────────────────────


def test_parse_catalog_page_extracts_entries_and_title():
    page, title = lib_svc._parse_catalog_page(
        library_id="lib1",
        raw_xml=_OPDS_FEED,
        base_url="https://library.example.org/catalog/v2/entries",
        start=0, count=20,
    )
    assert title == "Test Catalog"
    assert page.total_results == 42
    assert len(page.entries) == 1  # second entry has no acquisition link, skipped
    e = page.entries[0]
    assert e.title == "MDWiki Medical Encyclopedia"
    assert e.summary == "Healthcare articles curated by WikiProjectMed"
    assert e.language == "eng"
    assert e.size_bytes == 2302838784
    assert e.meta4_url.endswith(".zim.meta4")
    assert e.acquisition_url.endswith(".zim")
    assert e.thumbnail_url.startswith("https://library.example.org/catalog/v2/illustration/")


def test_parse_catalog_page_raises_on_non_feed():
    with pytest.raises(LibraryParseError):
        lib_svc._parse_catalog_page("lib1", b"<html/>", "https://x/", 0, 20)


def test_parse_catalog_page_raises_on_malformed_xml():
    with pytest.raises(LibraryParseError):
        lib_svc._parse_catalog_page("lib1", b"not xml", "https://x/", 0, 20)


# ── Metalink parsing ─────────────────────────────────────────────────────────


def test_parse_meta4_extracts_sha256_and_priority_url():
    parsed = lib_svc._parse_meta4(_META4)
    assert parsed["checksum"] == "sha256:896e15f81c68a567bd7e8979b9e6ea3df1f8359397a9ce2ac46eeb4f692cf583"
    assert parsed["download_url"] == "https://mirror1.example.org/zim/mdwiki_en_all_maxi_2025-11.zim"
    assert parsed["size_bytes"] == 2302838784


def test_parse_meta4_raises_without_sha256():
    xml = b"""<?xml version="1.0"?>
<metalink xmlns="urn:ietf:params:xml:ns:metalink">
  <file name="x.zim"><url>https://x/x.zim</url></file>
</metalink>"""
    with pytest.raises(LibraryParseError):
        lib_svc._parse_meta4(xml)


def test_parse_meta4_raises_without_url():
    xml = b"""<?xml version="1.0"?>
<metalink xmlns="urn:ietf:params:xml:ns:metalink">
  <file name="x.zim"><hash type="sha-256">abc</hash></file>
</metalink>"""
    with pytest.raises(LibraryParseError):
        lib_svc._parse_meta4(xml)


# ── module_id derivation ─────────────────────────────────────────────────────


def test_module_id_from_acquisition_url():
    assert lib_svc.module_id_from_acquisition_url(
        "https://download.kiwix.org/zim/other/mdwiki_en_all_maxi_2025-11.zim"
    ) == "mdwiki_en_all_maxi_2025-11"


# ── validate_library ─────────────────────────────────────────────────────────


async def test_validate_library_returns_canonical_and_origin(monkeypatch):
    async def fake_fetch(url):
        return _OPDS_FEED
    monkeypatch.setattr(lib_svc, "_fetch_catalog", fake_fetch)
    result = await lib_svc.validate_library("https://library.example.org/")
    # display_name is the URL origin, not the feed <title>, because Kiwix
    # mutates the title per query (returns "Filtered Entries (count=1)" for our probe).
    assert result.display_name == "https://library.example.org"
    assert result.entry_count == 42
    assert result.canonical_url.endswith("/catalog/v2/entries")


async def test_validate_library_unreachable(monkeypatch):
    async def fake_fetch(url):
        raise httpx.RequestError("down")
    monkeypatch.setattr(lib_svc, "_fetch_catalog", fake_fetch)
    with pytest.raises(LibraryUnreachableError):
        await lib_svc.validate_library("https://x.example.org/")


async def test_validate_library_falls_back_to_host_rewrite(monkeypatch):
    """When browse.X fails but X succeeds, picks X."""
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        if "browse." in url:
            raise httpx.HTTPStatusError("404", request=None, response=None)
        return _OPDS_FEED

    monkeypatch.setattr(lib_svc, "_fetch_catalog", fake_fetch)
    result = await lib_svc.validate_library("https://browse.library.example.org/#lang=nld")
    assert "browse." not in result.canonical_url
    assert any("browse." in c for c in calls)


# ── fetch_page ───────────────────────────────────────────────────────────────


async def test_fetch_page_passes_lang_param(monkeypatch):
    seen = {}

    async def fake_fetch(url):
        seen["url"] = url
        return _OPDS_FEED

    monkeypatch.setattr(lib_svc, "_fetch_catalog", fake_fetch)
    library = Library(
        id="L1",
        display_name="Test",
        url="https://library.example.org/catalog/v2/entries",
        lang="nld",
    )
    page = await lib_svc.fetch_page(library, start=20, count=10)
    assert "lang=nld" in seen["url"]
    assert "start=20" in seen["url"]
    assert "count=10" in seen["url"]
    assert page.start == 20
    assert page.count == 10


async def test_fetch_page_propagates_network_error(monkeypatch):
    async def fake_fetch(url):
        raise httpx.RequestError("down")

    monkeypatch.setattr(lib_svc, "_fetch_catalog", fake_fetch)
    library = Library(id="L1", display_name="x", url="https://x/")
    with pytest.raises(LibraryUnreachableError):
        await lib_svc.fetch_page(library, 0, 20)


# ── resolve_entry ────────────────────────────────────────────────────────────


async def test_resolve_entry_returns_module_dict(monkeypatch, tmp_settings):
    async def fake_meta4(url):
        return _META4

    async def fake_image(url):
        return (b"\x89PNG\r\n\x1a\nbody", "image/png")

    from app.services import thumbnails

    monkeypatch.setattr(lib_svc, "_fetch_meta4", fake_meta4)
    monkeypatch.setattr(thumbnails, "_fetch_image", fake_image)
    entry = LibraryEntry(
        entry_id="urn:uuid:e1",
        title="MDWiki",
        summary="hi",
        language="eng",
        size_bytes=100,
        acquisition_url="https://download.example.org/zim/mdwiki_en_all_maxi_2025-11.zim",
        meta4_url="https://download.example.org/zim/mdwiki_en_all_maxi_2025-11.zim.meta4",
        thumbnail_url="https://example.org/thumb.png",
    )
    library = Library(id="lib-1", display_name="X", url="https://catalog.example.org/catalog/v2/entries")
    result = await lib_svc.resolve_entry(entry, library, tmp_settings)
    assert result["id"] == "mdwiki_en_all_maxi_2025-11"
    assert result["latest_version"] == "mdwiki_en_all_maxi_2025-11"
    assert result["checksum"].startswith("sha256:")
    assert result["download_url"].startswith("https://mirror1.")
    assert result["source_library_id"] == "lib-1"
    assert result["image"] == "/data-cache/mdwiki_en_all_maxi_2025-11/cover.png"
    # OPDS catalogs carry no category; the wizard assigns one, so the
    # service-level fallback is the generic reference slug.
    assert result["category"] == "reference"


async def test_resolve_entry_propagates_unreachable(monkeypatch, tmp_settings):
    async def fake_meta4(url):
        raise httpx.RequestError("down")
    monkeypatch.setattr(lib_svc, "_fetch_meta4", fake_meta4)
    entry = LibraryEntry(
        entry_id="x", title="x",
        acquisition_url="https://x.example.org/x.zim",
        meta4_url="https://x.example.org/x.zim.meta4",
    )
    library = Library(id="lib", display_name="X", url="https://x.example.org/catalog/v2/entries")
    with pytest.raises(LibraryUnreachableError):
        await lib_svc.resolve_entry(entry, library, tmp_settings)


async def test_resolve_entry_rejects_foreign_meta4_host(tmp_settings):
    entry = LibraryEntry(
        entry_id="x", title="x",
        acquisition_url="http://127.0.0.1/x.zim",
        meta4_url="http://127.0.0.1/x.zim.meta4",
    )
    library = Library(id="lib", display_name="X", url="https://library.example.org/catalog/v2/entries")
    with pytest.raises(LibraryParseError):
        await lib_svc.resolve_entry(entry, library, tmp_settings)


async def test_resolve_entry_accepts_sibling_subdomain(tmp_settings):
    """Kiwix's OPDS feed references a CDN subdomain (e.g. lbo.download.kiwix.org)."""
    async def fake_meta4(url):
        return _META4

    import unittest.mock as mock
    with mock.patch.object(lib_svc, "_fetch_meta4", fake_meta4):
        entry = LibraryEntry(
            entry_id="x", title="x",
            acquisition_url="https://lbo.download.example.org/zim/foo_2025-01.zim",
            meta4_url="https://lbo.download.example.org/zim/foo_2025-01.zim.meta4",
        )
        library = Library(id="lib", display_name="X", url="https://library.example.org/catalog/v2/entries")
        result = await lib_svc.resolve_entry(entry, library, tmp_settings)
        assert result["id"] == "foo_2025-01"


# ── Registry mutations ───────────────────────────────────────────────────────


def test_add_library_persists(tmp_settings):
    _seed(tmp_settings)
    lib = registry_svc.add_library(
        tmp_settings, "https://library.example.org/catalog/v2/entries", "Test", "nld"
    )
    reloaded = registry_svc.list_libraries(tmp_settings)
    assert len(reloaded) == 1
    assert reloaded[0].id == lib.id
    assert reloaded[0].lang == "nld"


def test_add_library_rejects_duplicate(tmp_settings):
    _seed(tmp_settings)
    registry_svc.add_library(tmp_settings, "https://x.org/catalog/v2/entries", "X", None)
    with pytest.raises(LibraryAlreadyExistsError):
        registry_svc.add_library(tmp_settings, "https://x.org/catalog/v2/entries", "X", None)


def test_remove_library_prunes_available_modules(tmp_settings):
    lib = Library(id="L1", display_name="X", url="https://x/")
    available = Module(
        id="pkg1", display_name="P", category="library",
        description="", latest_version="v1", size_gb=1.0, checksum="sha256:a",
        source_library_id="L1",
    )
    _seed(tmp_settings, libraries=[lib], modules=[available])
    registry_svc.remove_library(tmp_settings, "L1")
    reg = registry_svc.load_registry(tmp_settings)
    assert reg.libraries == []
    assert reg.modules == []


def test_remove_library_keeps_installed_modules_with_source_cleared(tmp_settings):
    lib = Library(id="L1", display_name="X", url="https://x/")
    installed = Module(
        id="pkg1", display_name="P", category="library",
        description="", latest_version="v1", size_gb=1.0, checksum="sha256:a",
        installed_version="v1", installed_checksum="sha256:a", active=True,
        source_library_id="L1",
    )
    other = Module(
        id="pkg2", display_name="O", category="medical",
        description="", latest_version="v1", size_gb=1.0, checksum="sha256:b",
    )
    _seed(tmp_settings, libraries=[lib], modules=[installed, other])
    registry_svc.remove_library(tmp_settings, "L1")
    reg = registry_svc.load_registry(tmp_settings)
    assert reg.libraries == []
    by_id = {m.id: m for m in reg.modules}
    assert "pkg1" in by_id and by_id["pkg1"].source_library_id is None
    assert "pkg2" in by_id


def test_remove_library_raises_not_found(tmp_settings):
    _seed(tmp_settings)
    with pytest.raises(LibraryNotFoundError):
        registry_svc.remove_library(tmp_settings, "nope")


def test_remove_library_deletes_cached_thumbnails_for_dropped_modules(tmp_settings):
    lib = Library(id="L1", display_name="X", url="https://x/")
    available = Module(
        id="pkg1", display_name="P", category="library",
        description="", latest_version="v1", size_gb=1.0, checksum="sha256:a",
        image="/data-cache/pkg1/cover.png",
        source_library_id="L1",
    )
    installed = Module(
        id="pkg2", display_name="I", category="library",
        description="", latest_version="v1", size_gb=1.0, checksum="sha256:b",
        installed_version="v1", installed_checksum="sha256:b", active=True,
        image="/data-cache/pkg2/cover.png",
        source_library_id="L1",
    )
    _seed(tmp_settings, libraries=[lib], modules=[available, installed])
    (tmp_settings.cache_dir / "pkg1").mkdir(parents=True, exist_ok=True)
    (tmp_settings.cache_dir / "pkg1" / "cover.png").write_bytes(b"a")
    (tmp_settings.cache_dir / "pkg2").mkdir(parents=True, exist_ok=True)
    (tmp_settings.cache_dir / "pkg2" / "cover.png").write_bytes(b"b")

    registry_svc.remove_library(tmp_settings, "L1")

    assert not (tmp_settings.cache_dir / "pkg1").exists()
    # Installed module is kept (source cleared) so its cache stays.
    assert (tmp_settings.cache_dir / "pkg2" / "cover.png").exists()


# ── HTTP fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── HTTP endpoints ───────────────────────────────────────────────────────────


async def test_validate_endpoint_returns_canonical(client, tmp_settings, monkeypatch):
    async def fake_fetch(url):
        return _OPDS_FEED
    monkeypatch.setattr(lib_svc, "_fetch_catalog", fake_fetch)
    r = await client.post(
        "/api/libraries/validate",
        json={"url": "https://library.example.org/"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["display_name"] == "https://library.example.org"
    assert body["canonical_url"].endswith("/catalog/v2/entries")


async def test_validate_endpoint_returns_502_on_network(client, monkeypatch):
    async def fake_fetch(url):
        raise httpx.RequestError("down")
    monkeypatch.setattr(lib_svc, "_fetch_catalog", fake_fetch)
    r = await client.post("/api/libraries/validate", json={"url": "https://x.org/"})
    assert r.status_code == 502


async def test_validate_endpoint_returns_400_on_invalid_url(client):
    r = await client.post("/api/libraries/validate", json={"url": "not-a-url"})
    assert r.status_code == 400


async def test_add_endpoint_creates_library(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.post(
        "/api/libraries",
        json={
            "url": "https://library.example.org/catalog/v2/entries",
            "display_name": "Test",
            "lang": "nld",
        },
    )
    assert r.status_code == 201
    assert len(registry_svc.list_libraries(tmp_settings)) == 1


async def test_add_endpoint_returns_409_on_duplicate(client, tmp_settings):
    _seed(tmp_settings)
    payload = {
        "url": "https://library.example.org/catalog/v2/entries",
        "display_name": "Test",
    }
    await client.post("/api/libraries", json=payload)
    r = await client.post("/api/libraries", json=payload)
    assert r.status_code == 409


async def test_delete_endpoint_returns_204(client, tmp_settings):
    lib = Library(id="L1", display_name="X", url="https://x/")
    _seed(tmp_settings, libraries=[lib])
    r = await client.delete("/api/libraries/L1")
    assert r.status_code == 204
    assert registry_svc.list_libraries(tmp_settings) == []


async def test_delete_endpoint_returns_404_for_unknown(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.delete("/api/libraries/nope")
    assert r.status_code == 404


async def test_browse_endpoint_returns_entries(client, tmp_settings, monkeypatch):
    lib = Library(
        id="L1", display_name="X",
        url="https://library.example.org/catalog/v2/entries",
    )
    _seed(tmp_settings, libraries=[lib])

    async def fake_fetch(url):
        return _OPDS_FEED
    monkeypatch.setattr(lib_svc, "_fetch_catalog", fake_fetch)

    r = await client.get("/api/libraries/L1/entries?start=0&count=20")
    assert r.status_code == 200
    body = r.json()
    assert body["total_results"] == 42
    assert len(body["entries"]) == 1


async def test_browse_endpoint_returns_404_for_unknown_library(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.get("/api/libraries/nope/entries")
    assert r.status_code == 404


async def test_browse_endpoint_returns_502_on_network_error(client, tmp_settings, monkeypatch):
    lib = Library(id="L1", display_name="X", url="https://x/")
    _seed(tmp_settings, libraries=[lib])

    async def fake_fetch(url):
        raise httpx.RequestError("down")
    monkeypatch.setattr(lib_svc, "_fetch_catalog", fake_fetch)

    r = await client.get("/api/libraries/L1/entries")
    assert r.status_code == 502


async def test_register_endpoint_writes_modules(client, tmp_settings, monkeypatch):
    lib = Library(id="L1", display_name="X", url="https://catalog.example.org/catalog/v2/entries")
    _seed(tmp_settings, libraries=[lib])

    async def fake_meta4(url):
        return _META4
    monkeypatch.setattr(lib_svc, "_fetch_meta4", fake_meta4)
    installs: list[str] = []
    async def fake_start(module, settings):
        installs.append(module.id)
    monkeypatch.setattr(packages_svc, "start_download", fake_start)

    payload = {
        "entries": [
            {
                "entry_id": "urn:uuid:e1",
                "title": "MDWiki",
                "summary": "x",
                "language": "eng",
                "size_bytes": 2302838784,
                "acquisition_url": "https://download.example.org/zim/mdwiki_en_all_maxi_2025-11.zim",
                "meta4_url": "https://download.example.org/zim/mdwiki_en_all_maxi_2025-11.zim.meta4",
                "thumbnail_url": None,
            }
        ]
    }
    r = await client.post("/api/libraries/L1/register", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["registered"] == ["mdwiki_en_all_maxi_2025-11"]
    assert body["failed"] == []

    reg = registry_svc.load_registry(tmp_settings)
    assert any(m.id == "mdwiki_en_all_maxi_2025-11" for m in reg.modules)
    mod = next(m for m in reg.modules if m.id == "mdwiki_en_all_maxi_2025-11")
    assert mod.source_library_id == "L1"
    assert installs == ["mdwiki_en_all_maxi_2025-11"]


async def test_register_endpoint_partial_success(client, tmp_settings, monkeypatch):
    lib = Library(id="L1", display_name="X", url="https://catalog.example.org/catalog/v2/entries")
    _seed(tmp_settings, libraries=[lib])

    async def fake_meta4(url):
        if "fail" in url:
            raise httpx.RequestError("down")
        return _META4
    monkeypatch.setattr(lib_svc, "_fetch_meta4", fake_meta4)
    installs: list[str] = []
    async def fake_start(module, settings):
        installs.append(module.id)
    monkeypatch.setattr(packages_svc, "start_download", fake_start)

    payload = {
        "entries": [
            {
                "entry_id": "ok",
                "title": "Good",
                "acquisition_url": "https://download.example.org/zim/good_2025-01.zim",
                "meta4_url": "https://download.example.org/zim/good_2025-01.zim.meta4",
            },
            {
                "entry_id": "bad",
                "title": "Bad",
                "acquisition_url": "https://download.example.org/zim/fail.zim",
                "meta4_url": "https://download.example.org/zim/fail.zim.meta4",
            },
        ]
    }
    r = await client.post("/api/libraries/L1/register", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert "good_2025-01" in body["registered"]
    assert len(body["failed"]) == 1
    assert body["failed"][0]["title"] == "Bad"
    # Only the successful entry was queued for download.
    assert installs == ["good_2025-01"]


async def test_register_endpoint_rejects_foreign_meta4_host(client, tmp_settings, monkeypatch):
    """SSRF guard: meta4 URL host must match the library host."""
    lib = Library(id="L1", display_name="X", url="https://library.example.org/catalog/v2/entries")
    _seed(tmp_settings, libraries=[lib])

    payload = {
        "entries": [
            {
                "entry_id": "x",
                "title": "Evil",
                "acquisition_url": "http://127.0.0.1/x.zim",
                "meta4_url": "http://127.0.0.1/x.zim.meta4",
            }
        ]
    }
    r = await client.post("/api/libraries/L1/register", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["registered"] == []
    assert len(body["failed"]) == 1
    assert "host" in body["failed"][0]["reason"].lower()


async def test_register_endpoint_returns_404_for_unknown_library(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.post("/api/libraries/nope/register", json={"entries": []})
    assert r.status_code == 404


async def test_refresh_endpoint_returns_counts(client, tmp_settings):
    """Empty registry: endpoint succeeds with zero counts."""
    _seed(tmp_settings)
    r = await client.post("/api/libraries/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body == {"refreshed_libraries": 0, "updated_modules": 0, "errors": []}


async def test_refresh_one_endpoint_returns_404_for_unknown(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.post("/api/libraries/nope/refresh")
    assert r.status_code == 404


async def test_refresh_one_endpoint_returns_counts(client, tmp_settings):
    lib = Library(id="L1", display_name="X", url="o/r", type="github")
    _seed(tmp_settings, libraries=[lib])
    r = await client.post("/api/libraries/L1/refresh")
    assert r.status_code == 200
    body = r.json()
    # Empty registry (no modules from L1) → no fetch happens, zero counts.
    assert body == {"refreshed_libraries": 0, "updated_modules": 0, "errors": []}


async def test_register_endpoint_skips_install_when_already_installed(
    client, tmp_settings, monkeypatch
):
    """Re-picking an already-installed entry refreshes metadata but does not redownload."""
    lib = Library(id="L1", display_name="X", url="https://catalog.example.org/catalog/v2/entries")
    existing = Module(
        id="mdwiki_en_all_maxi_2025-11",
        display_name="MDWiki", category="library",
        description="", latest_version="mdwiki_en_all_maxi_2025-11",
        size_gb=2.3, checksum="sha256:old",
        installed_version="mdwiki_en_all_maxi_2025-11",
        installed_checksum="sha256:old",
        active=True,
        source_library_id="L1",
    )
    _seed(tmp_settings, libraries=[lib], modules=[existing])

    async def fake_meta4(url):
        return _META4
    monkeypatch.setattr(lib_svc, "_fetch_meta4", fake_meta4)
    installs: list[str] = []
    async def fake_start(module, settings):
        installs.append(module.id)
    monkeypatch.setattr(packages_svc, "start_download", fake_start)

    payload = {
        "entries": [
            {
                "entry_id": "urn:uuid:e1",
                "title": "MDWiki",
                "acquisition_url": "https://download.example.org/zim/mdwiki_en_all_maxi_2025-11.zim",
                "meta4_url": "https://download.example.org/zim/mdwiki_en_all_maxi_2025-11.zim.meta4",
            }
        ]
    }
    r = await client.post("/api/libraries/L1/register", json=payload)
    assert r.status_code == 200
    assert r.json()["registered"] == ["mdwiki_en_all_maxi_2025-11"]
    assert installs == []  # already installed → no redownload


# ── Packages page renders libraries ──────────────────────────────────────────


async def test_packages_page_renders_libraries(client, tmp_settings):
    lib = Library(
        id="L1", display_name="Kiwix NL",
        url="https://library.kiwix.org/catalog/v2/entries", lang="nld",
    )
    _seed(tmp_settings, libraries=[lib])
    r = await client.get("/settings/packages")
    assert r.status_code == 200
    assert "Kiwix NL" in r.text
    assert "LIBRARIES" in r.text


async def test_settings_preferences_page_no_longer_renders_libraries(client, tmp_settings):
    lib = Library(
        id="L1", display_name="Kiwix NL",
        url="https://library.kiwix.org/catalog/v2/entries", lang="nld",
    )
    _seed(tmp_settings, libraries=[lib])
    r = await client.get("/settings/preferences")
    assert r.status_code == 200
    assert "Kiwix NL" not in r.text
    assert "PICK_FROM_LIBRARY" not in r.text
    assert "ADD_LIBRARY" not in r.text


async def test_settings_redirects_to_status(client):
    r = await client.get("/settings", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/settings/status"
