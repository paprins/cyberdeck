from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.config import Settings
from app.services.connectivity import connectivity_probe_loop, make_default_probe
from app.services.notifications import services_probe_loop
from app.services.registry import load_registry
from app.services.packages import init_kiwix_library, reconcile_kiwix_library

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    # Shared proxy client. Constructed eagerly (no async I/O) so tests using
    # ASGITransport — which does not run lifespan events — still have it.
    http_client = httpx.AsyncClient(timeout=30.0, follow_redirects=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for d in (cfg.zim_dir, cfg.maps_dir, cfg.downloads_dir,
                  cfg.registry_path.parent, cfg.images_dir, cfg.content_dir,
                  cfg.cache_dir):
            d.mkdir(parents=True, exist_ok=True)
        init_kiwix_library(cfg)
        reconcile_kiwix_library(cfg)
        probe_task = asyncio.create_task(services_probe_loop(cfg))
        connectivity_task = asyncio.create_task(
            connectivity_probe_loop(cfg, make_default_probe(cfg))
        )
        try:
            yield
        finally:
            probe_task.cancel()
            connectivity_task.cancel()
            for task in (probe_task, connectivity_task):
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await http_client.aclose()

    app = FastAPI(title="Cyberdeck", lifespan=lifespan)
    app.state.settings = cfg
    app.state.http_client = http_client

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # check_dir=False defers the directory check to request time, so the mount
    # registers even on a fresh install where the dir is created later by lifespan.
    app.mount(
        "/data-static",
        StaticFiles(directory=cfg.data_dir / "static", check_dir=False),
        name="data-static",
    )
    app.mount(
        "/data-cache",
        StaticFiles(directory=cfg.cache_dir, check_dir=False),
        name="data-cache",
    )

    from app.routers import system as system_router
    app.include_router(system_router.make_router(cfg))

    from app.routers import home as home_router
    app.include_router(home_router.make_router(cfg))

    from app.routers import search as search_router
    app.include_router(search_router.make_router(cfg))

    from app.routers import packages as packages_router
    app.include_router(packages_router.make_router(cfg))

    from app.routers import settings as settings_router
    app.include_router(settings_router.make_router(cfg))

    from app.routers import wifi as wifi_router
    app.include_router(wifi_router.make_router(cfg))

    from app.routers import upgrade as upgrade_router
    app.include_router(upgrade_router.make_router(cfg))

    from app.routers import libraries as libraries_router
    app.include_router(libraries_router.make_router(cfg))

    from app.routers import content as content_router
    app.include_router(content_router.make_router(cfg))

    from app.routers import map_viewer as map_viewer_router
    app.include_router(map_viewer_router.make_router(cfg))

    from app.routers import proxy as proxy_router
    app.include_router(proxy_router.make_router(cfg))

    @app.get("/health")
    async def health():
        from app.services.upgrade import current_version
        return {"status": "ok", "version": current_version(cfg)}

    @app.get("/api/status")
    async def status():
        registry = load_registry(cfg)
        active = [m for m in registry.modules if m.active]
        return {
            "active_modules": len(active),
            "total_modules": len(registry.modules),
            "data_dirs": {
                "zim": str(cfg.zim_dir),
                "maps": str(cfg.maps_dir),
                "downloads": str(cfg.downloads_dir),
            },
        }

    @app.exception_handler(404)
    async def not_found(request, exc):
        return JSONResponse({"error": "not found"}, status_code=404)

    from app.services.system import SystemCommandError

    @app.exception_handler(SystemCommandError)
    async def system_command_error(request, exc: SystemCommandError):
        return JSONResponse(
            {"detail": str(exc)},
            status_code=503 if exc.unsupported else 500,
        )

    return app


app = create_app()
