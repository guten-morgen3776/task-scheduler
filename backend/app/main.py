from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.calendar import router as calendar_router
from app.api.lists import router as lists_router
from app.api.optimize import optimize_router, snapshots_router
from app.api.settings import router as settings_router
from app.api.slots import router as slots_router
from app.api.tasks import list_scoped_router as task_list_scoped_router
from app.api.tasks import task_router
from app.core.config import get_settings

app = FastAPI(title="task-scheduler", version="0.3.0")

_settings = get_settings()
_cors_origins: list[str] = [_settings.public_frontend_url]
if _settings.app_env == "dev":
    # Allow both the configured frontend URL and Vite's default port for ad-hoc use.
    _cors_origins.extend(["http://localhost:47824", "http://localhost:5173"])
# Dedupe while preserving order.
_cors_origins = list(dict.fromkeys(_cors_origins))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(calendar_router)
app.include_router(slots_router)
app.include_router(settings_router)
app.include_router(lists_router)
app.include_router(task_list_scoped_router)
app.include_router(task_router)
app.include_router(optimize_router)
app.include_router(snapshots_router)
