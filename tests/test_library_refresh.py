from __future__ import annotations
import pytest

from app.models.library import Library, LibraryNotFoundError, LibraryUnreachableError
from app.models.registry import Module, Registry
import app.services.git_libraries as git_svc
import app.services.library_refresh as refresh_svc


@pytest.fixture(autouse=True)
def reset_state():
    refresh_svc.reset_state_for_tests()
    yield
    refresh_svc.reset_state_for_tests()


def _seed(tmp_settings, libraries=None, modules=None):
    tmp_settings.registry_path.parent.mkdir(parents=True, exist_ok=True)
    reg = Registry(modules=modules or [], libraries=libraries or [])
    tmp_settings.registry_path.write_text(reg.model_dump_json())


def _git_lib(library_id="L1") -> Library:
    return Library(
        id=library_id, display_name="Cyberdeck", url="paprins/cyberdeck",
        type="github",
    )


def _installed_module(module_id="first-aid", source="L1", **overrides) -> Module:
    defaults = dict(
        id=module_id,
        display_name="First Aid",
        category="medical",
        description="",
        latest_version="1.0",
        size_gb=0.0,
        kind="static",
        signature_url="https://example.com/x.minisig",
        download_url="https://example.com/x.tar.gz",
        entry="index.md",
        installed_version="1.0",
        active=True,
        source_library_id=source,
    )
    defaults.update(overrides)
    return Module(**defaults)


def _manifest(version: str, package_id: str = "first-aid", host: str = "github.com"):
    base = f"https://{host}/paprins/cyberdeck/releases/download/v{version}"
    return {
        "title": "Cyberdeck",
        "packages": [
            {
                "id": package_id,
                "display_name": "First Aid",
                "category": "medical",
                "version": version,
                "size_bytes": 1024,
                "tarball_url": f"{base}/{package_id}.tar.gz",
                "signature_url": f"{base}/{package_id}.tar.gz.minisig",
                "entry": "index.md",
            }
        ],
    }


# ── refresh_all_libraries ────────────────────────────────────────────────────


async def test_refresh_updates_latest_version(monkeypatch, tmp_settings):
    _seed(tmp_settings, libraries=[_git_lib()], modules=[_installed_module()])
    async def fake(_url): return _manifest("2.0")
    monkeypatch.setattr(git_svc, "_fetch_manifest", fake)
    async def no_cache(*_a, **_kw): return None
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", no_cache)

    result = await refresh_svc.refresh_all_libraries(tmp_settings)

    assert result.refreshed_libraries == 1
    assert result.updated_modules == 1
    assert result.errors == []
    from app.services.registry import load_registry
    reg = load_registry(tmp_settings)
    mod = reg.modules[0]
    assert mod.latest_version == "2.0"
    assert mod.installed_version == "1.0"  # preserved
    assert mod.has_update is True


async def test_refresh_skips_modules_not_in_manifest(monkeypatch, tmp_settings):
    """Manifest entries that don't match any registered module are ignored."""
    _seed(tmp_settings, libraries=[_git_lib()], modules=[_installed_module("first-aid")])
    async def fake(_url): return _manifest("2.0", package_id="other-package")
    monkeypatch.setattr(git_svc, "_fetch_manifest", fake)

    result = await refresh_svc.refresh_all_libraries(tmp_settings)
    assert result.refreshed_libraries == 1
    assert result.updated_modules == 0
    from app.services.registry import load_registry
    assert load_registry(tmp_settings).modules[0].latest_version == "1.0"  # unchanged


async def test_refresh_skips_libraries_with_no_known_modules(monkeypatch, tmp_settings):
    """A library that's registered but has nothing installed is silently skipped."""
    _seed(tmp_settings, libraries=[_git_lib()], modules=[])
    called: list[str] = []
    async def fake(url): called.append(url); return _manifest("2.0")
    monkeypatch.setattr(git_svc, "_fetch_manifest", fake)

    result = await refresh_svc.refresh_all_libraries(tmp_settings)
    assert result.refreshed_libraries == 0
    assert called == []  # no fetch happened


async def test_refresh_skips_opds_libraries(monkeypatch, tmp_settings):
    """OPDS versions are baked into the module id; nothing to refresh."""
    opds_lib = Library(
        id="O1", display_name="Kiwix", url="https://kiwix.org/catalog/v2/entries",
        type="opds",
    )
    opds_module = Module(
        id="mdwiki_2025-11", display_name="MDWiki", category="medical",
        description="", latest_version="mdwiki_2025-11", size_gb=2.0,
        checksum="sha256:a", installed_version="mdwiki_2025-11", active=True,
        source_library_id="O1",
    )
    _seed(tmp_settings, libraries=[opds_lib], modules=[opds_module])
    async def boom(_url):
        raise AssertionError("OPDS must not be refreshed")
    monkeypatch.setattr(git_svc, "_fetch_manifest", boom)
    # Also patch the OPDS catalog fetcher to be safe.
    import app.services.libraries as lib_svc
    monkeypatch.setattr(lib_svc, "_fetch_catalog", boom)

    result = await refresh_svc.refresh_all_libraries(tmp_settings)
    assert result.refreshed_libraries == 0


async def test_refresh_per_library_error_isolation(monkeypatch, tmp_settings):
    """One library failing doesn't kill the rest."""
    good_lib = Library(id="L1", display_name="Good", url="o/r1", type="github")
    bad_lib = Library(id="L2", display_name="Bad", url="o/r2", type="github")
    _seed(
        tmp_settings,
        libraries=[good_lib, bad_lib],
        modules=[
            _installed_module("first-aid", source="L1"),
            _installed_module("water", source="L2"),
        ],
    )

    async def fake(url):
        if "r2" in url:
            raise LibraryUnreachableError("bad library down")
        return _manifest("2.0")
    monkeypatch.setattr(git_svc, "_fetch_manifest", fake)
    async def no_cache(*_a, **_kw): return None
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", no_cache)

    result = await refresh_svc.refresh_all_libraries(tmp_settings)
    assert result.refreshed_libraries == 1
    assert result.updated_modules == 1
    assert len(result.errors) == 1
    assert "Bad" in result.errors[0]


# ── refresh_one_library ─────────────────────────────────────────────────────


async def test_refresh_one_library_updates_only_that_library(monkeypatch, tmp_settings):
    lib_a = Library(id="L1", display_name="A", url="o/a", type="github")
    lib_b = Library(id="L2", display_name="B", url="o/b", type="github")
    _seed(
        tmp_settings,
        libraries=[lib_a, lib_b],
        modules=[
            _installed_module("first-aid", source="L1"),
            _installed_module("water", source="L2"),
        ],
    )
    fetches: list[str] = []
    async def fake(url):
        fetches.append(url)
        return _manifest("2.0")
    monkeypatch.setattr(git_svc, "_fetch_manifest", fake)
    async def no_cache(*_a, **_kw): return None
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", no_cache)

    result = await refresh_svc.refresh_one_library("L1", tmp_settings)
    assert result.refreshed_libraries == 1
    assert result.updated_modules == 1
    # Only library A was fetched.
    assert len(fetches) == 1
    assert "o/a" in fetches[0]

    from app.services.registry import load_registry
    by_id = {m.id: m for m in load_registry(tmp_settings).modules}
    assert by_id["first-aid"].latest_version == "2.0"
    assert by_id["water"].latest_version == "1.0"  # untouched


async def test_refresh_one_library_unknown_id_raises(tmp_settings):
    _seed(tmp_settings)
    with pytest.raises(LibraryNotFoundError):
        await refresh_svc.refresh_one_library("does-not-exist", tmp_settings)


async def test_refresh_one_library_opds_is_noop(monkeypatch, tmp_settings):
    opds_lib = Library(
        id="O1", display_name="Kiwix", url="https://kiwix.org/catalog/v2/entries", type="opds",
    )
    _seed(tmp_settings, libraries=[opds_lib])
    async def boom(_url):
        raise AssertionError("OPDS must not be refreshed")
    monkeypatch.setattr(git_svc, "_fetch_manifest", boom)
    result = await refresh_svc.refresh_one_library("O1", tmp_settings)
    assert result.refreshed_libraries == 0
    assert result.updated_modules == 0


async def test_refresh_one_library_does_not_advance_global_ttl(monkeypatch, tmp_settings):
    """Per-library refresh shouldn't poison the opportunistic refresh TTL."""
    _seed(tmp_settings, libraries=[_git_lib()], modules=[_installed_module()])
    async def fake(_url): return _manifest("2.0")
    monkeypatch.setattr(git_svc, "_fetch_manifest", fake)
    async def no_cache(*_a, **_kw): return None
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", no_cache)
    await refresh_svc.refresh_one_library("L1", tmp_settings)
    # Global TTL state is still cold → maybe_refresh would still run.
    assert refresh_svc._state.checked_at is None


# ── bundled-image rescan on refresh ─────────────────────────────────────────


async def test_refresh_heals_bundled_image_for_existing_install(monkeypatch, tmp_settings):
    """A static module installed before the bundled-image feature shipped
    (Module.image is null but card.png is on disk) gets healed on refresh."""
    lib = _git_lib()
    existing = _installed_module()  # image=None by default
    _seed(tmp_settings, libraries=[lib], modules=[existing])

    # Place the extracted card.png where _final_path() expects it.
    content_dir = tmp_settings.content_dir / existing.id
    content_dir.mkdir(parents=True)
    (content_dir / "card.png").write_bytes(b"bundled-data")

    async def fake(_url): return _manifest("1.0", package_id=existing.id)
    monkeypatch.setattr(git_svc, "_fetch_manifest", fake)
    async def no_cache(*_a, **_kw): return None
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", no_cache)

    await refresh_svc.refresh_one_library(lib.id, tmp_settings)

    from app.services.registry import load_registry
    healed = load_registry(tmp_settings).modules[0]
    assert healed.image == f"/content/{existing.id}/card.png"
    # No copy — bytes are served straight from the extracted content dir.
    assert not (tmp_settings.cache_dir / existing.id).exists()


async def test_refresh_skips_rescan_when_image_already_set(monkeypatch, tmp_settings):
    """Don't overwrite an existing Module.image (preserves HTTP-cached or
    previously-resolved bundled images)."""
    lib = _git_lib()
    existing = _installed_module(image="/data-cache/first-aid/cover.png")
    _seed(tmp_settings, libraries=[lib], modules=[existing])

    content_dir = tmp_settings.content_dir / existing.id
    content_dir.mkdir(parents=True)
    (content_dir / "card.jpg").write_bytes(b"new-bundled-data")  # different ext, would clobber

    async def fake(_url): return _manifest("1.0", package_id=existing.id)
    monkeypatch.setattr(git_svc, "_fetch_manifest", fake)
    async def no_cache(*_a, **_kw): return None
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", no_cache)

    await refresh_svc.refresh_one_library(lib.id, tmp_settings)

    from app.services.registry import load_registry
    refreshed = load_registry(tmp_settings).modules[0]
    assert refreshed.image == "/data-cache/first-aid/cover.png"  # unchanged


async def test_refresh_rescan_noop_when_no_bundled_card(monkeypatch, tmp_settings):
    lib = _git_lib()
    existing = _installed_module()
    _seed(tmp_settings, libraries=[lib], modules=[existing])
    content_dir = tmp_settings.content_dir / existing.id
    content_dir.mkdir(parents=True)
    (content_dir / "index.md").write_text("# hi")

    async def fake(_url): return _manifest("1.0", package_id=existing.id)
    monkeypatch.setattr(git_svc, "_fetch_manifest", fake)
    async def no_cache(*_a, **_kw): return None
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", no_cache)

    await refresh_svc.refresh_one_library(lib.id, tmp_settings)

    from app.services.registry import load_registry
    assert load_registry(tmp_settings).modules[0].image is None


# ── maybe_refresh_libraries ─────────────────────────────────────────────────


async def test_maybe_refresh_runs_when_cold(monkeypatch, tmp_settings):
    _seed(tmp_settings, libraries=[_git_lib()], modules=[_installed_module()])
    async def fake(_url): return _manifest("2.0")
    monkeypatch.setattr(git_svc, "_fetch_manifest", fake)
    async def no_cache(*_a, **_kw): return None
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", no_cache)

    result = await refresh_svc.maybe_refresh_libraries(tmp_settings)
    assert result is not None
    assert result.updated_modules == 1


async def test_maybe_refresh_is_ttl_gated(monkeypatch, tmp_settings):
    """A second call inside the TTL window is a no-op."""
    _seed(tmp_settings, libraries=[_git_lib()], modules=[_installed_module()])
    calls = 0
    async def fake(_url):
        nonlocal calls
        calls += 1
        return _manifest("2.0")
    monkeypatch.setattr(git_svc, "_fetch_manifest", fake)
    async def no_cache(*_a, **_kw): return None
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", no_cache)

    first = await refresh_svc.maybe_refresh_libraries(tmp_settings)
    assert first is not None
    second = await refresh_svc.maybe_refresh_libraries(tmp_settings)
    assert second is None  # skipped
    assert calls == 1


async def test_maybe_refresh_skipped_when_in_flight(tmp_settings):
    refresh_svc._state.in_flight = True
    try:
        result = await refresh_svc.maybe_refresh_libraries(tmp_settings)
        assert result is None
    finally:
        refresh_svc._state.in_flight = False
