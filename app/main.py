from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.config import Settings
from app.services.registry import load_registry

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for d in (cfg.zim_dir, cfg.maps_dir, cfg.downloads_dir, cfg.registry_path.parent):
            d.mkdir(parents=True, exist_ok=True)
        app.state.settings = cfg
        yield

    app = FastAPI(title="Cyberdeck", lifespan=lifespan)

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    from app.routers import system as system_router
    app.include_router(system_router.make_router(cfg))

    from app.routers import home as home_router
    app.include_router(home_router.make_router(cfg))

    @app.get("/health")
    async def health():
        return {"status": "ok"}

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

    return app


app = create_app()
