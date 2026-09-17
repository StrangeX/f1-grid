from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app import cache, settings
from app.brief import ask, full_analysis, get_brief
from app.grid import get_grid
from app.refresh import LOCK_KEY, poll_forever, sync_standings

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


class AskBody(BaseModel):
    question: str = Field(min_length=2, max_length=240)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await cache.init()
    except Exception:
        pass
    poller = asyncio.create_task(poll_forever())
    yield
    poller.cancel()
    try:
        await poller
    except asyncio.CancelledError:
        pass
    await cache.release_lock(LOCK_KEY)
    await cache.close()


app = FastAPI(title="F1 Grid", version="1.4.0", lifespan=lifespan)


def _rows(items: list[dict], extra: dict[str, dict], key: str) -> list[dict]:
    rows = []
    for item in items:
        row = dict(item)
        info = extra.get(item.get(key) or "") or {}
        row["gap"] = info.get("gap", 0)
        row["still_in"] = info.get("still_in", False)
        row["spark"] = info.get("spark", "")
        row["title_pct"] = info.get("title_pct", 0)
        row["podium_pct"] = info.get("podium_pct", 0)
        rows.append(row)
    return rows


async def _page(kind: str) -> dict:
    grid = await get_grid()
    drivers_a, constructors_a, forecast = await full_analysis(grid)
    analysis = constructors_a if kind == "constructors" else drivers_a
    brief = await get_brief(grid, kind)
    view = dict(grid)
    view["page"] = kind
    view["brief"] = brief
    view["analysis"] = analysis
    view["forecast_runs"] = forecast.get("runs", 0)
    view["refresh"] = await cache.get_json("f1:meta:refresh") or {}
    if kind == "constructors":
        extra = {row["id"]: row for row in analysis.get("contenders") or []}
        view["teams"] = _rows(grid.get("constructors") or [], extra, "id")
    else:
        extra = {row["code"]: row for row in analysis.get("contenders") or []}
        view["drivers"] = _rows(grid.get("drivers") or [], extra, "code")
    return view


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> JSONResponse:
    if settings.REDIS_URL and not await cache.ping():
        return JSONResponse({"status": "not-ready", "reason": "redis"}, status_code=503)
    payload = await get_grid()
    if payload.get("drivers"):
        return JSONResponse(
            {
                "status": "ready",
                "source": payload.get("source"),
                "cache": cache.backend(),
            }
        )
    return JSONResponse({"status": "not-ready"}, status_code=503)


@app.get("/api/standings")
async def standings() -> dict:
    return await get_grid()


@app.get("/api/analysis")
async def analysis() -> dict:
    grid = await get_grid()
    drivers, constructors, forecast = await full_analysis(grid)
    return {"drivers": drivers, "constructors": constructors, "forecast": forecast}


@app.get("/api/forecast")
async def forecast() -> dict:
    grid = await get_grid()
    _drivers, _constructors, payload = await full_analysis(grid)
    return payload


@app.get("/api/brief")
async def brief() -> dict:
    grid = await get_grid()
    return await get_brief(grid)


@app.get("/api/refresh")
async def refresh(force: bool = False) -> dict:
    return await sync_standings(force=force)


@app.post("/api/ask")
async def ask_route(body: AskBody) -> dict:
    grid = await get_grid()
    return await ask(grid, body.question)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        "championship.html",
        {"request": request, "grid": await _page("drivers")},
    )


@app.get("/constructors", response_class=HTMLResponse)
async def constructors(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        "championship.html",
        {"request": request, "grid": await _page("constructors")},
    )
