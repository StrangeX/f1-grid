from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app import cache, settings

log = logging.getLogger("f1.refresh")
META_KEY = "f1:meta:refresh"
LOCK_KEY = "f1:lock:refresh"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def poll_interval(next_race_date: str | None) -> int:
    if next_race_date:
        try:
            race_day = datetime.fromisoformat(next_race_date[:10]).date()
            delta = (race_day - datetime.now(timezone.utc).date()).days
            if -1 <= delta <= 1:
                return settings.POLL_RACE_SEC
        except ValueError:
            pass
    return settings.POLL_IDLE_SEC


async def _meta() -> dict[str, Any]:
    return await cache.get_json(META_KEY) or {}


async def _save_meta(payload: dict[str, Any]) -> None:
    await cache.set_json(META_KEY, payload)


async def _sync_standings(force: bool, previous: dict[str, Any]) -> dict[str, Any]:
    from app.brief import full_analysis
    from app.grid import get_grid, peek_standings

    try:
        live = await peek_standings()
    except Exception as exc:
        result = {
            **previous,
            "status": "error",
            "checked_at": _now(),
            "error": str(exc)[:180],
            "interval_sec": settings.POLL_IDLE_SEC,
        }
        await _save_meta(result)
        return result

    fingerprint = f"{live['round']}:{live['field_points']}:{live['leader']}"
    cached_grid = await cache.get_json(f"f1:grid:v3:{settings.SEASON}") or {}
    cached_total = sum(int(row.get("points") or 0) for row in cached_grid.get("drivers") or [])
    same_cache = (
        str(cached_grid.get("round") or "") == live["round"]
        and cached_total == live["field_points"]
    )
    if not force and (previous.get("fingerprint") == fingerprint or same_cache):
        nxt = cached_grid.get("next_race") or {}
        result = {
            **previous,
            "status": "unchanged",
            "checked_at": _now(),
            "round": live["round"],
            "leader": live["leader"],
            "leader_points": live["leader_points"],
            "field_points": live["field_points"],
            "fingerprint": fingerprint,
            "updated_at": previous.get("updated_at") or cached_grid.get("fetched_at"),
            "interval_sec": poll_interval(nxt.get("date")),
        }
        await _save_meta(result)
        return result

    cleared = 0
    for prefix in ("f1:grid:", "f1:forecast:", "f1:brief:"):
        cleared += await cache.delete_prefix(prefix)

    grid = await get_grid()
    await full_analysis(grid)
    nxt = grid.get("next_race") or {}
    result = {
        "status": "updated",
        "checked_at": _now(),
        "updated_at": _now(),
        "round": live["round"],
        "leader": live["leader"],
        "leader_points": live["leader_points"],
        "field_points": live["field_points"],
        "fingerprint": fingerprint,
        "cleared": cleared,
        "fetched_at": grid.get("fetched_at"),
        "interval_sec": poll_interval(nxt.get("date")),
        "reason": "forced" if force else "new-results",
    }
    await _save_meta(result)
    log.info("standings refreshed round=%s leader=%s", live["round"], live["leader"])
    return result


async def sync_standings(force: bool = False) -> dict[str, Any]:
    previous = await _meta()
    locked = force or await cache.acquire_lock(LOCK_KEY, ttl=90)
    if not locked:
        return {
            "status": "busy",
            "checked_at": _now(),
            "interval_sec": 30,
            "round": previous.get("round"),
        }

    try:
        return await _sync_standings(force=force, previous=previous)
    finally:
        if not force:
            await cache.release_lock(LOCK_KEY)


async def poll_forever() -> None:
    await asyncio.sleep(8)
    while True:
        try:
            result = await sync_standings(force=False)
            wait = int(result.get("interval_sec") or settings.POLL_IDLE_SEC)
            if result.get("status") == "busy":
                wait = 30
        except Exception:
            log.exception("refresh poll failed")
            wait = settings.POLL_IDLE_SEC
        await asyncio.sleep(max(wait, 30))
