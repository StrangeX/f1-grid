from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parent
FALLBACK_PATH = APP_DIR / "data" / "fallback.json"
TEMPLATES = Jinja2Templates(directory=str(APP_DIR / "templates"))

API_BASE = os.getenv("F1_API_BASE", "https://api.jolpi.ca/ergast/f1").rstrip("/")
SEASON = os.getenv("F1_SEASON", "current")
CACHE_TTL_SEC = int(os.getenv("F1_CACHE_TTL", "300"))

app = FastAPI(title="F1 Grid", version="1.0.0")

_cache: dict[str, Any] = {"ts": 0.0, "payload": None}


def _load_fallback() -> dict[str, Any]:
    return json.loads(FALLBACK_PATH.read_text(encoding="utf-8"))


def _driver_row(item: dict[str, Any]) -> dict[str, Any]:
    driver = item.get("Driver", {})
    constructors = item.get("Constructors") or [{}]
    return {
        "position": int(item.get("position", 0)),
        "code": driver.get("code", ""),
        "name": f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip(),
        "team": constructors[0].get("name", ""),
        "points": float(item.get("points", 0)),
        "wins": int(item.get("wins", 0)),
    }


def _parse_standings(raw: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    table = raw["MRData"]["StandingsTable"]
    listing = table["StandingsLists"][0]
    drivers = [_driver_row(row) for row in listing.get("DriverStandings", [])]
    return str(listing.get("season", SEASON)), str(listing.get("round", "")), drivers


def _parse_next_race(raw: dict[str, Any]) -> dict[str, Any] | None:
    races = raw.get("MRData", {}).get("RaceTable", {}).get("Races") or []
    if not races:
        return None
    race = races[0]
    circuit = race.get("Circuit", {})
    location = circuit.get("Location", {})
    return {
        "round": str(race.get("round", "")),
        "name": race.get("raceName", ""),
        "circuit": circuit.get("circuitName", ""),
        "locality": location.get("locality", ""),
        "country": location.get("country", ""),
        "date": race.get("date", ""),
        "time": race.get("time", ""),
    }


async def _fetch_live() -> dict[str, Any]:
    timeout = httpx.Timeout(8.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        standings_url = f"{API_BASE}/{SEASON}/driverStandings.json"
        next_url = f"{API_BASE}/{SEASON}/next.json"
        standings_res, next_res = await client.get(standings_url), await client.get(next_url)
        standings_res.raise_for_status()
        next_res.raise_for_status()
        season, round_no, drivers = _parse_standings(standings_res.json())
        return {
            "season": season,
            "round": round_no,
            "source": "live",
            "drivers": drivers,
            "next_race": _parse_next_race(next_res.json()),
        }


async def get_grid() -> dict[str, Any]:
    now = time.time()
    if _cache["payload"] and now - _cache["ts"] < CACHE_TTL_SEC:
        return _cache["payload"]
    try:
        payload = await _fetch_live()
    except Exception:
        payload = _load_fallback()
        payload["source"] = "fallback"
    _cache["ts"] = now
    _cache["payload"] = payload
    return payload


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> JSONResponse:
    payload = await get_grid()
    if payload.get("drivers"):
        return JSONResponse({"status": "ready", "source": payload.get("source")})
    return JSONResponse({"status": "not-ready"}, status_code=503)


@app.get("/api/standings")
async def standings() -> dict[str, Any]:
    return await get_grid()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    payload = await get_grid()
    return TEMPLATES.TemplateResponse(
        "index.html",
        {"request": request, "grid": payload},
    )
