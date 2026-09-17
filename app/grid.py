from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app import cache, settings
from app.analytics import form_by_code, form_by_team, max_remaining_points, remaining_races, team_max_remaining_points

FALLBACK_PATH = Path(__file__).resolve().parent / "data" / "fallback.json"


def load_fallback() -> dict[str, Any]:
    payload = json.loads(FALLBACK_PATH.read_text(encoding="utf-8"))
    payload["source"] = "fallback"
    leftover = payload.get("remaining_races") or []
    payload["remaining_count"] = len(leftover)
    payload["max_remaining"] = payload.get("max_remaining") or max_remaining_points(leftover)
    payload["constructor_max_remaining"] = payload.get("constructor_max_remaining") or team_max_remaining_points(leftover)
    payload.setdefault("form", {})
    payload.setdefault("team_form", {})
    payload.setdefault("constructors", [])
    return payload


def _driver_row(item: dict[str, Any]) -> dict[str, Any]:
    driver = item.get("Driver", {})
    constructors = item.get("Constructors") or [{}]
    return {
        "position": int(item.get("position", 0)),
        "code": driver.get("code", ""),
        "name": f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip(),
        "team": constructors[0].get("name", ""),
        "team_id": constructors[0].get("constructorId", ""),
        "points": float(item.get("points", 0)),
        "wins": int(item.get("wins", 0)),
    }


def _parse_standings(raw: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    listing = raw["MRData"]["StandingsTable"]["StandingsLists"][0]
    drivers = [_driver_row(row) for row in listing.get("DriverStandings", [])]
    return str(listing.get("season", settings.SEASON)), str(listing.get("round", "")), drivers


def _parse_constructors(raw: dict[str, Any]) -> list[dict[str, Any]]:
    listing = raw.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists") or []
    if not listing:
        return []
    rows = []
    for item in listing[0].get("ConstructorStandings") or []:
        constructor = item.get("Constructor") or {}
        rows.append(
            {
                "position": int(item.get("position", 0)),
                "id": constructor.get("constructorId", ""),
                "name": constructor.get("name", ""),
                "points": float(item.get("points", 0)),
                "wins": int(item.get("wins", 0)),
            }
        )
    return rows


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


async def _get_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    res = await client.get(url)
    res.raise_for_status()
    return res.json()


async def _fetch_live() -> dict[str, Any]:
    timeout = httpx.Timeout(12.0, connect=4.0)
    base = f"{settings.API_BASE}/{settings.SEASON}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        standings_raw, constructors_raw, next_raw, calendar_raw = await asyncio.gather(
            _get_json(client, f"{base}/driverStandings.json"),
            _get_json(client, f"{base}/constructorStandings.json"),
            _get_json(client, f"{base}/next.json"),
            _get_json(client, f"{base}.json"),
        )
        season, round_no, drivers = _parse_standings(standings_raw)
        current = int(round_no or 0)
        form_rounds = [n for n in range(max(1, current - 4), current + 1)]
        result_payloads = []
        for n in form_rounds:
            result_payloads.append(await _get_json(client, f"{base}/{n}/results.json"))
            await asyncio.sleep(0.12)
    calendar = calendar_raw.get("MRData", {}).get("RaceTable", {}).get("Races") or []
    results: list[dict[str, Any]] = []
    for payload in result_payloads:
        results.extend(payload.get("MRData", {}).get("RaceTable", {}).get("Races") or [])
    leftover = remaining_races(calendar, int(round_no or 0))
    return {
        "season": season,
        "round": round_no,
        "source": "live",
        "drivers": drivers,
        "constructors": _parse_constructors(constructors_raw),
        "next_race": _parse_next_race(next_raw),
        "races_total": len(calendar),
        "remaining_races": leftover,
        "remaining_count": len(leftover),
        "max_remaining": max_remaining_points(leftover),
        "constructor_max_remaining": team_max_remaining_points(leftover),
        "form": form_by_code(results),
        "team_form": form_by_team(results),
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


async def get_grid() -> dict[str, Any]:
    key = f"f1:grid:v3:{settings.SEASON}"
    cached = await cache.get_json(key)
    if cached:
        cached["cache"] = cache.backend()
        return cached
    try:
        payload = await _fetch_live()
    except Exception:
        payload = load_fallback()
    payload["cache"] = cache.backend()
    await cache.set_json(key, payload, settings.CACHE_TTL_SEC)
    return payload


async def peek_standings() -> dict[str, Any]:
    timeout = httpx.Timeout(8.0, connect=4.0)
    url = f"{settings.API_BASE}/{settings.SEASON}/driverStandings.json"
    async with httpx.AsyncClient(timeout=timeout) as client:
        raw = await _get_json(client, url)
    _season, round_no, drivers = _parse_standings(raw)
    leader = drivers[0] if drivers else {}
    total = sum(int(row.get("points") or 0) for row in drivers)
    return {
        "round": str(round_no),
        "leader": leader.get("code", ""),
        "leader_points": int(leader.get("points") or 0),
        "field_points": total,
    }
