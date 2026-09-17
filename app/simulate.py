from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

from app import cache, settings

RACE_POINTS = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]
SPRINT_POINTS = [8, 7, 6, 5, 4, 3, 2, 1]
TEAM_RACE_MAX = 25 + 18
TEAM_SPRINT_MAX = 8 + 7


def team_max_remaining(races: list[dict[str, Any]]) -> int:
    return sum(TEAM_RACE_MAX + (TEAM_SPRINT_MAX if race.get("sprint") else 0) for race in races)


def _strength(driver: dict[str, Any], form: dict[str, Any], completed: int) -> float:
    season_rate = float(driver.get("points") or 0) / max(completed, 1)
    recent = (form.get(driver.get("code") or "") or {}).get("avg_points")
    if recent is None:
        recent = season_rate
    return max(0.15, 0.55 * season_rate + 0.45 * float(recent))


def _weighted_order(items: list[str], weights: dict[str, float], rng: random.Random) -> list[str]:
    remaining = [(item, max(weights.get(item, 0.15), 0.15)) for item in items]
    order: list[str] = []
    while remaining:
        total = sum(weight for _, weight in remaining)
        pick = rng.random() * total
        acc = 0.0
        chosen = 0
        for i, (_, weight) in enumerate(remaining):
            acc += weight
            if acc >= pick:
                chosen = i
                break
        order.append(remaining.pop(chosen)[0])
    return order


def _apply_points(order: list[str], table: list[int], score: dict[str, float], wins: dict[str, int] | None = None) -> None:
    for place, code in enumerate(order):
        if place < len(table):
            score[code] += table[place]
        if wins is not None and place == 0:
            wins[code] += 1


def _champion(score: dict[str, float], wins: dict[str, int]) -> str:
    return max(score, key=lambda key: (score[key], wins[key], key))


def _podium(score: dict[str, float], wins: dict[str, int], n: int = 3) -> list[str]:
    ranked = sorted(score, key=lambda key: (score[key], wins[key], key), reverse=True)
    return ranked[:n]


def simulate(grid: dict[str, Any], runs: int | None = None) -> dict[str, Any]:
    runs = runs or settings.SIMS
    leftover = grid.get("remaining_races") or []
    drivers = list(grid.get("drivers") or [])
    constructors = list(grid.get("constructors") or [])
    form = grid.get("form") or {}
    completed = max(int(grid.get("round") or 1), 1)
    codes = [d["code"] for d in drivers if d.get("code")]
    weights = {d["code"]: _strength(d, form, completed) for d in drivers if d.get("code")}
    team_of = {d["code"]: d.get("team_id") or d.get("team") for d in drivers}
    team_ids = [c.get("id") or c.get("name") for c in constructors]
    start_driver = {d["code"]: float(d["points"]) for d in drivers}
    start_team = {(c.get("id") or c.get("name")): float(c["points"]) for c in constructors}

    if not codes or not leftover:
        empty = {code: {"title": 0.0, "podium": 0.0} for code in codes}
        teams = {tid: {"title": 0.0, "podium": 0.0} for tid in team_ids}
        return {"runs": 0, "drivers": empty, "constructors": teams}

    seed = zlib_seed(str(grid.get("season")), str(grid.get("round")), int(drivers[0]["points"]), runs)
    rng = random.Random(seed)
    driver_titles: dict[str, int] = defaultdict(int)
    driver_podiums: dict[str, int] = defaultdict(int)
    team_titles: dict[str, int] = defaultdict(int)
    team_podiums: dict[str, int] = defaultdict(int)

    for _ in range(runs):
        d_score = dict(start_driver)
        d_wins = {code: 0 for code in codes}
        t_score = dict(start_team)
        t_wins = {tid: 0 for tid in team_ids}
        for race in leftover:
            order = _weighted_order(codes, weights, rng)
            _apply_points(order, RACE_POINTS, d_score, d_wins)
            if race.get("sprint"):
                sprint_order = _weighted_order(codes, weights, rng)
                _apply_points(sprint_order, SPRINT_POINTS, d_score)
            race_team: dict[str, float] = defaultdict(float)
            for place, code in enumerate(order):
                pts = RACE_POINTS[place] if place < len(RACE_POINTS) else 0
                tid = team_of.get(code)
                if tid:
                    race_team[tid] += pts
                    t_score[tid] = t_score.get(tid, 0) + pts
            if race.get("sprint"):
                for place, code in enumerate(sprint_order):
                    pts = SPRINT_POINTS[place] if place < len(SPRINT_POINTS) else 0
                    tid = team_of.get(code)
                    if tid:
                        t_score[tid] = t_score.get(tid, 0) + pts
            if race_team:
                t_wins[_champion(race_team, {k: 0 for k in race_team})] += 1
        d_champ = _champion(d_score, d_wins)
        driver_titles[d_champ] += 1
        for code in _podium(d_score, d_wins):
            driver_podiums[code] += 1
        if team_ids:
            t_champ = _champion(t_score, t_wins)
            team_titles[t_champ] += 1
            for tid in _podium(t_score, t_wins):
                team_podiums[tid] += 1

    def pack(keys: list[str], titles: dict[str, int], podiums: dict[str, int]) -> dict[str, dict[str, float]]:
        return {
            key: {
                "title": round(100.0 * titles.get(key, 0) / runs, 1),
                "podium": round(100.0 * podiums.get(key, 0) / runs, 1),
            }
            for key in keys
        }

    return {
        "runs": runs,
        "seed": seed,
        "drivers": pack(codes, driver_titles, driver_podiums),
        "constructors": pack(team_ids, team_titles, team_podiums),
    }


def zlib_seed(*parts: object) -> int:
    text = "|".join(str(part) for part in parts)
    value = 2166136261
    for char in text:
        value ^= ord(char)
        value = (value * 16777619) & 0xFFFFFFFF
    return value


async def get_forecast(grid: dict[str, Any]) -> dict[str, Any]:
    leader = (grid.get("drivers") or [{}])[0]
    key = (
        f"f1:forecast:v1:{grid.get('season')}:{grid.get('round')}:"
        f"{int(leader.get('points') or 0)}:{settings.SIMS}"
    )
    cached = await cache.get_json(key)
    if cached:
        return cached
    payload = simulate(grid)
    await cache.set_json(key, payload, settings.CACHE_TTL_SEC)
    return payload
