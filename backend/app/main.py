from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.calendar import router as calendar_router
from app.api.lists import router as lists_router
from app.api.optimize import optimize_router, snapshots_router
from app.api.settings import router as settings_router
from app.api.slots import router as slots_router
from app.api.tasks import list_scoped_router as task_list_scoped_router
from app.api.tasks import task_router

app = FastAPI(title="task-scheduler", version="0.3.0")


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
