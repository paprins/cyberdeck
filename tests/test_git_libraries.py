from __future__ import annotations
import httpx
import pytest

from app.models.library import (
    Library,
    LibraryEntry,
    LibraryInvalidUrlError,
    LibraryParseError,
    LibraryUnreachableError,
)
import app.services.git_libraries as svc


def _manifest_with_assets(host: str) -> dict:
    """Build a manifest whose release assets live on the given host."""
    base = f"https://{host}/paprins/cyberdeck-content/releases/download/v2026-05"
    return {
        "title": "Cyberdeck Content",
        "packages": [
            {
                "id": "first-aid",
                "display_name": "First Aid Guide",
                "description": "Basic emergency procedures",
                "category": "medical",
                "version": "2026-05",
                "size_bytes": 4_194_304,
                "tarball_url": f"{base}/first-aid.tar.gz",
                "signature_url": f"{base}/first-aid.tar.gz.minisig",
                "image_url": f"https://{host}/paprins/cyberdeck-content/-/raw/main/cover.png",
                "entry": "index.md",
            },
            {
                "id": "shelter",
                "display_name": "Shelter",
                "description": "",
                "category": "shelter",
                "version": "2026-01",
                "size_bytes": 1024,
                "tarball_url": f"{base}/shelter.tar.gz",
                "signature_url": f"{base}/shelter.tar.gz.minisig",
                "entry": "README.md",
            },
        ],
    }


_GITHUB_MANIFEST = _manifest_with_assets("github.com")
_GITLAB_MANIFEST = _manifest_with_assets("gitlab.com")
_CODEBERG_MANIFEST = _manifest_with_assets("codeberg.org")


# ── detect_type ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        ("owner/repo", "github"),
        ("https://github.com/owner/repo", "github"),
        ("https://github.com/owner/repo/tree/main", "github"),
        ("https://raw.githubusercontent.com/owner/repo/main/manifest.json", "github"),
        ("https://gitlab.com/owner/repo", "gitlab"),
        ("https://gitlab.com/group/subgroup/repo", "gitlab"),
        ("https://codeberg.org/owner/repo", "codeberg"),
        ("https://library.kiwix.org/catalog/v2/entries", "opds"),
        ("https://browse.library.kiwix.org/#lang=nld", "opds"),
        ("ftp://example.org/feed", "opds"),
        ("", "opds"),
        ("   ", "opds"),
    ],
)
def test_detect_type(url, expected):
    assert svc.detect_type(url) == expected


# ── normalize_git_url ────────────────────────────────────────────────────────


def test_normalize_shorthand_only_github():
    assert svc.normalize_git_url("owner/repo", "github") == "owner/repo"


def test_normalize_shorthand_rejected_on_gitlab():
    with pytest.raises(LibraryInvalidUrlError):
        svc.normalize_git_url("owner/repo", "gitlab")


def test_normalize_shorthand_rejected_on_codeberg():
    with pytest.raises(LibraryInvalidUrlError):
        svc.normalize_git_url("owner/repo", "codeberg")


@pytest.mark.parametrize(
    "url, git_type, expected",
    [
        ("https://github.com/owner/repo", "github", "owner/repo"),
        ("https://github.com/owner/repo/tree/main", "github", "owner/repo"),
        ("https://raw.githubusercontent.com/owner/repo/main/manifest.json", "github", "owner/repo"),
        ("https://gitlab.com/owner/repo", "gitlab", "owner/repo"),
        ("https://codeberg.org/owner/repo", "codeberg", "owner/repo"),
    ],
)
def test_normalize_full_urls(url, git_type, expected):
    assert svc.normalize_git_url(url, git_type) == expected


def test_normalize_rejects_empty():
    with pytest.raises(LibraryInvalidUrlError):
        svc.normalize_git_url("", "github")


def test_normalize_rejects_unrelated_host_for_github():
    with pytest.raises(LibraryInvalidUrlError):
        svc.normalize_git_url("https://gitlab.com/owner/repo", "github")


def test_normalize_rejects_gitlab_subgroup_with_clear_error():
    with pytest.raises(LibraryInvalidUrlError) as exc:
        svc.normalize_git_url("https://gitlab.com/group/subgroup/repo", "gitlab")
    assert "subgroup" in str(exc.value).lower()


def test_normalize_rejects_codeberg_deep_path():
    with pytest.raises(LibraryInvalidUrlError):
        svc.normalize_git_url("https://codeberg.org/org/team/repo", "codeberg")


def test_normalize_rejects_unknown_git_type():
    with pytest.raises(LibraryInvalidUrlError):
        svc.normalize_git_url("https://github.com/owner/repo", "bitbucket")  # type: ignore[arg-type]


# ── manifest_url_for ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "git_type, expected",
    [
        ("github", "https://raw.githubusercontent.com/owner/repo/main/manifest.json"),
        ("gitlab", "https://gitlab.com/owner/repo/-/raw/main/manifest.json"),
        ("codeberg", "https://codeberg.org/owner/repo/raw/branch/main/manifest.json"),
    ],
)
def test_manifest_url_for(git_type, expected):
    assert svc.manifest_url_for("owner/repo", git_type) == expected


# ── validate_library ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw_url, git_type, manifest",
    [
        ("https://github.com/paprins/cyberdeck-content", "github", _GITHUB_MANIFEST),
        ("https://gitlab.com/paprins/cyberdeck-content", "gitlab", _GITLAB_MANIFEST),
        ("https://codeberg.org/paprins/cyberdeck-content", "codeberg", _CODEBERG_MANIFEST),
    ],
)
async def test_validate_returns_canonical(monkeypatch, raw_url, git_type, manifest):
    async def fake(_url): return manifest
    monkeypatch.setattr(svc, "_fetch_manifest", fake)
    result = await svc.validate_library(raw_url, git_type)
    assert result.canonical_url == "paprins/cyberdeck-content"
    assert result.display_name == "Cyberdeck Content"
    assert result.entry_count == 2


async def test_validate_network_error_maps_to_unreachable(monkeypatch):
    async def boom(_url):
        raise httpx.RequestError("dns")
    monkeypatch.setattr(svc, "_fetch_manifest", boom)
    with pytest.raises(LibraryUnreachableError):
        await svc.validate_library("paprins/cyberdeck-content", "github")


async def test_validate_parse_error_on_missing_packages(monkeypatch):
    async def fake(_url): return {"title": "broken"}
    monkeypatch.setattr(svc, "_fetch_manifest", fake)
    with pytest.raises(LibraryParseError):
        await svc.validate_library("paprins/cyberdeck-content", "github")


# ── fetch_page ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "git_type, manifest, host",
    [
        ("github", _GITHUB_MANIFEST, "github.com"),
        ("gitlab", _GITLAB_MANIFEST, "gitlab.com"),
        ("codeberg", _CODEBERG_MANIFEST, "codeberg.org"),
    ],
)
async def test_fetch_page_returns_entries(monkeypatch, git_type, manifest, host):
    async def fake(_url): return manifest
    monkeypatch.setattr(svc, "_fetch_manifest", fake)
    library = Library(
        id="L1", display_name="x",
        url="paprins/cyberdeck-content", type=git_type,
    )
    page = await svc.fetch_page(library, start=0, count=20)
    assert page.total_results == 2
    assert len(page.entries) == 2
    e = page.entries[0]
    assert e.kind == git_type
    assert e.entry_id == "first-aid"
    assert e.title == "First Aid Guide"
    assert host in (e.tarball_url or "")


async def test_fetch_page_paginates(monkeypatch):
    async def fake(_url): return _GITHUB_MANIFEST
    monkeypatch.setattr(svc, "_fetch_manifest", fake)
    library = Library(id="L1", display_name="x", url="paprins/cyberdeck-content", type="github")
    page = await svc.fetch_page(library, start=1, count=10)
    assert len(page.entries) == 1
    assert page.entries[0].entry_id == "shelter"


async def test_fetch_page_skips_malformed(monkeypatch):
    bad = {"title": "x", "packages": [
        {"id": "good", "display_name": "Good", "version": "1",
         "tarball_url": "https://github.com/o/r/x.tar.gz",
         "signature_url": "https://github.com/o/r/x.minisig", "entry": "index.md",
         "size_bytes": 1},
        {"id": "missing-fields"},
    ]}
    async def fake(_url): return bad
    monkeypatch.setattr(svc, "_fetch_manifest", fake)
    library = Library(id="L1", display_name="x", url="o/r", type="github")
    page = await svc.fetch_page(library, 0, 10)
    assert len(page.entries) == 1
    assert page.entries[0].entry_id == "good"


# ── resolve_entry ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "git_type, manifest",
    [
        ("github", _GITHUB_MANIFEST),
        ("gitlab", _GITLAB_MANIFEST),
        ("codeberg", _CODEBERG_MANIFEST),
    ],
)
async def test_resolve_entry_returns_module_dict(
    monkeypatch, tmp_settings, git_type, manifest
):
    async def fake(_url): return manifest
    async def no_cache(*_a, **_kw): return None
    monkeypatch.setattr(svc, "_fetch_manifest", fake)
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", no_cache)
    library = Library(
        id="L1", display_name="x",
        url="paprins/cyberdeck-content", type=git_type,
    )
    entry = (await svc.fetch_page(library, 0, 10)).entries[0]
    result = await svc.resolve_entry(entry, library, tmp_settings)
    assert result["id"] == "first-aid"
    assert result["kind"] == "static"
    assert result["source_library_id"] == "L1"
    assert result["latest_version"] == "2026-05"
    assert result["download_url"].endswith("first-aid.tar.gz")
    assert result["signature_url"].endswith(".minisig")
    assert result["entry"] == "index.md"
    assert result["size_gb"] == round(4_194_304 / (1024 ** 3), 3)
    # The manifest's category flows through to the module.
    assert result["category"] == "medical"


async def test_resolve_entry_coerces_unknown_category(monkeypatch, tmp_settings):
    # A manifest category outside the fixed set must not crash registration —
    # it falls back to the reference slug instead of raising.
    manifest = {
        "title": "X",
        "packages": [{
            "id": "almanac",
            "display_name": "Almanac",
            "description": "",
            "category": "history",  # not one of the 11 slugs
            "version": "1",
            "size_bytes": 1024,
            "tarball_url": "https://github.com/o/r/releases/download/v1/a.tar.gz",
            "signature_url": "https://github.com/o/r/releases/download/v1/a.tar.gz.minisig",
            "entry": "index.md",
        }],
    }
    async def fake(_url): return manifest
    async def no_cache(*_a, **_kw): return None
    monkeypatch.setattr(svc, "_fetch_manifest", fake)
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", no_cache)
    library = Library(id="L1", display_name="x", url="o/r", type="github")
    entry = (await svc.fetch_page(library, 0, 10)).entries[0]
    result = await svc.resolve_entry(entry, library, tmp_settings)
    assert result["category"] == "reference"


@pytest.mark.parametrize("git_type", ["github", "gitlab", "codeberg"])
async def test_resolve_entry_rejects_foreign_asset_host(tmp_settings, git_type):
    entry = LibraryEntry(
        entry_id="bad", kind=git_type, title="Bad", version="1", entry="index.md",
        tarball_url="https://attacker.example.com/x.tar.gz",
        signature_url="https://attacker.example.com/x.minisig",
    )
    library = Library(id="L1", display_name="x", url="o/r", type=git_type)
    with pytest.raises(LibraryParseError):
        await svc.resolve_entry(entry, library, tmp_settings)


async def test_resolve_entry_caches_http_image_and_clears_image_path(
    tmp_settings, monkeypatch
):
    """An HTTP image_url in the manifest is fetched + cached now; image_path stays None."""
    calls: list[str] = []
    async def fake_cache(_id, url, _settings):
        calls.append(url)
        return "/data-cache/first-aid/cover.png"
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", fake_cache)

    entry = LibraryEntry(
        entry_id="first-aid", kind="github", title="x", version="1", entry="index.md",
        tarball_url="https://github.com/o/r/x.tar.gz",
        signature_url="https://github.com/o/r/x.minisig",
        thumbnail_url="https://raw.githubusercontent.com/o/r/main/cover.png",
    )
    library = Library(id="L1", display_name="x", url="o/r", type="github")
    result = await svc.resolve_entry(entry, library, tmp_settings)
    assert result["image"] == "/data-cache/first-aid/cover.png"
    assert result["image_path"] is None
    assert calls == ["https://raw.githubusercontent.com/o/r/main/cover.png"]


async def test_resolve_entry_relative_image_sets_image_path_and_skips_http_cache(
    tmp_settings, monkeypatch
):
    """A relative image_url (no scheme) is deferred to install time."""
    async def boom(*a, **kw):
        raise AssertionError("cache_thumbnail must not be called for relative image_url")
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", boom)

    entry = LibraryEntry(
        entry_id="first-aid", kind="github", title="x", version="1", entry="index.md",
        tarball_url="https://github.com/o/r/x.tar.gz",
        signature_url="https://github.com/o/r/x.minisig",
        thumbnail_url="images/logo.png",
    )
    library = Library(id="L1", display_name="x", url="o/r", type="github")
    result = await svc.resolve_entry(entry, library, tmp_settings)
    assert result["image"] is None
    assert result["image_path"] == "images/logo.png"


async def test_resolve_entry_no_image_url_clears_both(tmp_settings, monkeypatch):
    async def no_cache(*_a, **_kw): return None
    monkeypatch.setattr("app.services.git_libraries.cache_thumbnail", no_cache)
    entry = LibraryEntry(
        entry_id="first-aid", kind="github", title="x", version="1", entry="index.md",
        tarball_url="https://github.com/o/r/x.tar.gz",
        signature_url="https://github.com/o/r/x.minisig",
        thumbnail_url=None,
    )
    library = Library(id="L1", display_name="x", url="o/r", type="github")
    result = await svc.resolve_entry(entry, library, tmp_settings)
    assert result["image"] is None
    assert result["image_path"] is None


async def test_resolve_entry_rejects_github_asset_on_gitlab_library(tmp_settings):
    """SSRF cross-host: gitlab library must reject github-hosted assets."""
    entry = LibraryEntry(
        entry_id="x", kind="gitlab", title="x", version="1", entry="index.md",
        tarball_url="https://github.com/owner/repo/releases/download/v1/x.tar.gz",
        signature_url="https://github.com/owner/repo/releases/download/v1/x.tar.gz.minisig",
    )
    library = Library(id="L1", display_name="x", url="owner/repo", type="gitlab")
    with pytest.raises(LibraryParseError):
        await svc.resolve_entry(entry, library, tmp_settings)
