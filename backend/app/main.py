import logging
import logging.config
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from app.core.config import settings
from app.core.logging_config import setup_logging
from app.api.v1.router import api_router
from app.db.session import engine, AsyncSessionLocal
from app.db.base import Base
import socketio as socketio_lib
from app.socket import sio

setup_logging()
logger = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

limiter = Limiter(key_func=get_remote_address)


async def seed_default_sources():
    from sqlalchemy import select
    from app.models.models import SheetSource

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SheetSource).limit(5))
        existing = {s.label for s in result.scalars().all()}

        sources = []
        if "Operations Sheet" not in existing:
            sources.append(SheetSource(
                label="Operations Sheet",
                spreadsheet_id="1lZCsuNceb_FsePEFtPg4X-rs9pk4JJKjSsV_ZN65w60",
                sync_interval_minutes=1,
                is_enabled=True,
                tab_mappings={"ops_data": "Master Log", "store_config": "Config"},
            ))
        if "Dashboard Sheet" not in existing:
            sources.append(SheetSource(
                label="Dashboard Sheet",
                spreadsheet_id="1w893ChKglcqIxHnoDqJ6DfOEmQG51VGJqiEy5lg-yEA",
                sync_interval_minutes=1,
                is_enabled=True,
                tab_mappings={
                    "store_config_v2": "STORE CONFIG",
                    "staff": "OSMC",
                    "intl_staff": "OSMC Intl",
                    "reviews": "Google Reviews",
                    "gr_action_plan": "GR Action Plan",
                    "tl_report": "TL Report",
                },
            ))
        if "Daily Store Tracker (xlsx)" not in existing:
            sources.append(SheetSource(
                label="Daily Store Tracker (xlsx)",
                spreadsheet_id="1T1TaNluKoUIh70UPZkoWUkdml026aCOl",
                is_xlsx_upload=True,
                sync_interval_minutes=1,
                is_enabled=True,
                tab_mappings={"daily_input": "Daily Input", "store_dashboard": "Store Dashboard"},
            ))

        if sources:
            db.add_all(sources)
            await db.commit()
            logger.info(f"Seeded {len(sources)} new sheet sources")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY is not set. Cannot start without it.")

    await seed_default_sources()

    from app.workers.scheduler import start_scheduler
    start_scheduler()

    yield
    await engine.dispose()


app = FastAPI(
    title="BP Analytics",
    description="CRM & Live Ops Dashboard for BreakProtection",
    version="1.0.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.middleware("http")
async def cache_control(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")

socket_app = socketio_lib.ASGIApp(sio, other_asgi_app=app)
