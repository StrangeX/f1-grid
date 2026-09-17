from __future__ import annotations

from typing import Any

RACE_WIN = 25
SPRINT_WIN = 8
TEAM_RACE_MAX = 25 + 18
TEAM_SPRINT_MAX = 8 + 7
FORM_WINDOW = 5


def attach_odds(analysis: dict[str, Any], odds: dict[str, dict[str, float]], key: str) -> dict[str, Any]:
    for row in analysis.get("contenders") or []:
        stats = odds.get(row.get(key) or "") or {}
        row["title_pct"] = stats.get("title", 0.0)
        row["podium_pct"] = stats.get("podium", 0.0)
    return analysis


def remaining_races(calendar: list[dict[str, Any]], current_round: int) -> list[dict[str, Any]]:
    leftover = []
    for race in calendar:
        round_no = int(race.get("round") or 0)
        if round_no <= current_round:
            continue
        leftover.append(
            {
                "round": str(round_no),
                "name": race.get("raceName", ""),
                "sprint": bool(race.get("Sprint")),
            }
        )
    return leftover


def max_remaining_points(races: list[dict[str, Any]]) -> int:
    return sum(RACE_WIN + (SPRINT_WIN if race.get("sprint") else 0) for race in races)


def team_max_remaining_points(races: list[dict[str, Any]]) -> int:
    return sum(TEAM_RACE_MAX + (TEAM_SPRINT_MAX if race.get("sprint") else 0) for race in races)


def form_by_code(results_races: list[dict[str, Any]], window: int = FORM_WINDOW) -> dict[str, dict[str, Any]]:
    recent = sorted(results_races, key=lambda r: int(r.get("round") or 0))[-window:]
    board: dict[str, dict[str, Any]] = {}
    for race in recent:
        for row in race.get("Results") or []:
            driver = row.get("Driver") or {}
            code = driver.get("code") or ""
            if not code:
                continue
            entry = board.setdefault(code, {"points": [], "positions": [], "races": []})
            entry["points"].append(float(row.get("points") or 0))
            try:
                entry["positions"].append(int(row.get("position") or 0))
            except (TypeError, ValueError):
                entry["positions"].append(0)
            entry["races"].append(str(race.get("round")))
    for entry in board.values():
        pts = entry["points"]
        entry["avg_points"] = round(sum(pts) / len(pts), 1) if pts else 0.0
        entry["spark"] = _sparkline(entry["positions"])
    return board


def form_by_team(results_races: list[dict[str, Any]], window: int = FORM_WINDOW) -> dict[str, dict[str, Any]]:
    recent = sorted(results_races, key=lambda r: int(r.get("round") or 0))[-window:]
    board: dict[str, dict[str, Any]] = {}
    for race in recent:
        round_pts: dict[str, float] = {}
        for row in race.get("Results") or []:
            constructor = row.get("Constructor") or {}
            tid = constructor.get("constructorId") or constructor.get("name") or ""
            if not tid:
                continue
            round_pts[tid] = round_pts.get(tid, 0.0) + float(row.get("points") or 0)
        for tid, points in round_pts.items():
            entry = board.setdefault(tid, {"points": [], "races": []})
            entry["points"].append(points)
            entry["races"].append(str(race.get("round")))
    for entry in board.values():
        pts = entry["points"]
        entry["avg_points"] = round(sum(pts) / len(pts), 1) if pts else 0.0
        entry["spark"] = _sparkline_values(pts, peak=TEAM_RACE_MAX)
    return board


def _sparkline_values(values: list[float], peak: float, width: float = 72, height: float = 20) -> str:
    if not values or peak <= 0:
        return ""
    n = len(values)
    pts: list[str] = []
    for i, value in enumerate(values):
        x = 0 if n == 1 else i * (width / (n - 1))
        y = (1 - min(max(value, 0.0), peak) / peak) * (height - 2) + 1
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _sparkline(positions: list[int], width: float = 72, height: float = 20) -> str:
    if not positions:
        return ""
    n = len(positions)
    pts: list[str] = []
    for i, pos in enumerate(positions):
        x = 0 if n == 1 else i * (width / (n - 1))
        clamped = min(max(pos or 20, 1), 20)
        y = ((clamped - 1) / 19) * (height - 2) + 1
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def analyze(grid: dict[str, Any]) -> dict[str, Any]:
    drivers = list(grid.get("drivers") or [])
    leftover = grid.get("remaining_races") or []
    max_left = int(grid.get("max_remaining") or max_remaining_points(leftover))
    remaining_count = int(grid.get("remaining_count") or len(leftover))
    races_total = int(grid.get("races_total") or (int(grid.get("round") or 0) + remaining_count))
    form = grid.get("form") or {}

    if not drivers:
        return {
            "remaining_count": remaining_count,
            "races_total": races_total,
            "max_remaining": max_left,
            "contenders": [],
            "eliminated": 0,
            "clinch_needed": None,
            "hottest": None,
            "insights": [],
        }

    leader = drivers[0]
    contenders = []
    for driver in drivers:
        gap = int(leader["points"] - driver["points"])
        ceiling = int(driver["points"] + max_left)
        still = ceiling >= int(leader["points"])
        needed_per_race = None
        if still and remaining_count and gap > 0:
            needed_per_race = round(gap / remaining_count, 1)
        code = driver["code"]
        driver_form = form.get(code) or {}
        contenders.append(
            {
                "code": code,
                "name": driver["name"],
                "team": driver["team"],
                "points": int(driver["points"]),
                "gap": gap,
                "ceiling": ceiling,
                "still_in": still,
                "needed_per_race": needed_per_race,
                "form_avg": driver_form.get("avg_points"),
                "spark": driver_form.get("spark", ""),
                "form_points": driver_form.get("points") or [],
            }
        )

    alive = [row for row in contenders if row["still_in"]]
    p2 = contenders[1] if len(contenders) > 1 else None
    clinch_needed = None
    if p2:
        clinch_needed = max(0, int(p2["points"] + max_left - leader["points"] + 1))

    hottest = None
    scored = [row for row in contenders[:8] if row.get("form_avg") is not None]
    if scored:
        hottest = max(scored, key=lambda row: (row["form_avg"], -row["gap"]))

    return {
        "remaining_count": remaining_count,
        "races_total": races_total,
        "max_remaining": max_left,
        "sprint_weekends_left": sum(1 for race in leftover if race.get("sprint")),
        "contenders": contenders,
        "alive_count": len(alive),
        "eliminated": len(contenders) - len(alive),
        "clinch_needed": clinch_needed,
        "hottest": hottest,
        "insights": _insights(leader, p2, alive, remaining_count, max_left, clinch_needed, hottest),
    }


def analyze_constructors(grid: dict[str, Any]) -> dict[str, Any]:
    teams = list(grid.get("constructors") or [])
    leftover = grid.get("remaining_races") or []
    max_left = int(grid.get("constructor_max_remaining") or team_max_remaining_points(leftover))
    remaining_count = int(grid.get("remaining_count") or len(leftover))
    races_total = int(grid.get("races_total") or (int(grid.get("round") or 0) + remaining_count))
    form = grid.get("team_form") or {}
    if not teams:
        return {
            "remaining_count": remaining_count,
            "races_total": races_total,
            "max_remaining": max_left,
            "contenders": [],
            "alive_count": 0,
            "eliminated": 0,
            "clinch_needed": None,
            "hottest": None,
            "insights": [],
        }

    leader = teams[0]
    contenders = []
    for team in teams:
        gap = int(leader["points"] - team["points"])
        ceiling = int(team["points"] + max_left)
        still = ceiling >= int(leader["points"])
        tid = team.get("id") or team.get("name")
        team_form = form.get(tid) or {}
        needed_per_race = round(gap / remaining_count, 1) if still and remaining_count and gap > 0 else None
        contenders.append(
            {
                "id": tid,
                "name": team["name"],
                "points": int(team["points"]),
                "wins": int(team.get("wins") or 0),
                "gap": gap,
                "ceiling": ceiling,
                "still_in": still,
                "needed_per_race": needed_per_race,
                "form_avg": team_form.get("avg_points"),
                "spark": team_form.get("spark", ""),
            }
        )
    alive = [row for row in contenders if row["still_in"]]
    p2 = contenders[1] if len(contenders) > 1 else None
    clinch_needed = None
    if p2:
        clinch_needed = max(0, int(p2["points"] + max_left - leader["points"] + 1))
    hottest = None
    scored = [row for row in contenders if row.get("form_avg") is not None]
    if scored:
        hottest = max(scored, key=lambda row: (row["form_avg"], -row["gap"]))
    insights = []
    if remaining_count:
        insights.append(
            f"{len(alive)} constructors can still win: {remaining_count} races left, "
            f"{max_left} points still available (max 43 per GP, +15 if sprint)."
        )
        if p2 and clinch_needed is not None:
            insights.append(
                f"{leader['name']} clinches with {clinch_needed} more points "
                f"if {p2['name']} scores the remaining maximum. Gap is {p2['gap']}."
            )
        if hottest:
            insights.append(
                f"Best recent constructor form: {hottest['name']} at {hottest['form_avg']} pts/race "
                f"over the last {FORM_WINDOW} GPs."
            )
    return {
        "remaining_count": remaining_count,
        "races_total": races_total,
        "max_remaining": max_left,
        "contenders": contenders,
        "alive_count": len(alive),
        "eliminated": len(contenders) - len(alive),
        "clinch_needed": clinch_needed,
        "hottest": hottest,
        "insights": insights,
    }


def _insights(
    leader: dict[str, Any],
    p2: dict[str, Any] | None,
    alive: list[dict[str, Any]],
    remaining_count: int,
    max_left: int,
    clinch_needed: int | None,
    hottest: dict[str, Any] | None,
) -> list[str]:
    notes: list[str] = []
    if remaining_count == 0:
        notes.append(f"{leader['name']} has completed the {leader.get('season', '')} season on {int(leader['points'])} points.")
        return notes

    notes.append(
        f"{len(alive)} drivers can still win mathematically: "
        f"{remaining_count} races left, {max_left} points still on the table "
        f"(25 for a win, +8 if the weekend has a sprint)."
    )
    if p2 and clinch_needed is not None:
        if clinch_needed == 0:
            notes.append(
                f"{leader['name']} has already clinched: {p2['name']} cannot catch "
                f"{int(leader['points'])} even with a perfect run."
            )
        else:
            notes.append(
                f"{leader['name']} clinches the title with {clinch_needed} more points "
                f"if {p2['name']} takes maximum remaining score. Gap is {p2['gap']}."
            )
            notes.append(
                f"To overhaul the lead, {p2['name']} must outscore {leader['name']} "
                f"by {p2['gap']} points across {remaining_count} weekends "
                f"({p2['needed_per_race']} per race if the leader stalls)."
            )
    if hottest and hottest["code"] != leader.get("code"):
        notes.append(
            f"Best recent form in the top group: {hottest['name']} at "
            f"{hottest['form_avg']} pts/race over the last {FORM_WINDOW} GPs."
        )
    elif hottest:
        notes.append(
            f"{leader['name']} also leads recent form ({hottest['form_avg']} pts/race "
            f"over the last {FORM_WINDOW} GPs)."
        )
    return notes


def answer_question(question: str, analysis: dict[str, Any], grid: dict[str, Any]) -> str:
    q = question.lower().strip()
    if not q:
        return "Ask who can still win, how the gap looks, or who is in form."

    contenders = analysis.get("contenders") or []
    mentioned = next((row for row in contenders if row["code"].lower() in q or row["name"].split()[-1].lower() in q), None)
    teams = analysis.get("constructor_contenders") or []
    mentioned_team = next((row for row in teams if str(row.get("name", "")).lower() in q or str(row.get("id", "")).lower() in q), None)

    if any(word in q for word in ("chance", "odds", "probab", "percent", "%", "forecast", "simulat")):
        target = mentioned or mentioned_team
        if target and target.get("title_pct") is not None:
            kind = "driver" if mentioned else "constructor"
            return (
                f"{target['name']} wins the {kind} title in {target['title_pct']}% of remaining-season simulations "
                f"({target.get('podium_pct', 0)}% for a top-3 finish)."
            )

    if mentioned_team and not mentioned:
        if not mentioned_team.get("still_in", True):
            return (
                f"{mentioned_team['name']} is mathematically out of the constructors' championship. "
                f"Ceiling {mentioned_team['ceiling']} vs leader {teams[0]['points']}."
            )
        return (
            f"{mentioned_team['name']} has {mentioned_team['points']} points "
            f"({mentioned_team['gap']} from the lead). Title odds: {mentioned_team.get('title_pct', 0)}%."
        )

    if mentioned:
        if not mentioned["still_in"]:
            return (
                f"{mentioned['name']} is mathematically out. Even a maximum of "
                f"{mentioned['ceiling']} ends short of {contenders[0]['points']}."
            )
        if mentioned["gap"] == 0:
            return (
                f"{mentioned['name']} leads the championship. "
                f"{analysis['alive_count']} drivers remain mathematically in the fight."
            )
        return (
            f"{mentioned['name']} is still in the title fight: {mentioned['gap']} points behind, "
            f"ceiling {mentioned['ceiling']} vs leader {contenders[0]['points']} "
            f"with {analysis['max_remaining']} points left."
        )

    if any(word in q for word in ("who can", "still win", "title", "contender", "eliminat")):
        if any(word in q for word in ("constructor", "team", "cup")) and teams:
            names = ", ".join(row["name"] for row in teams if row.get("still_in"))
            alive = sum(1 for row in teams if row.get("still_in"))
            return f"{alive} constructors can still win: {names}."
        names = ", ".join(row["name"] for row in contenders if row["still_in"])
        return (
            f"{analysis['alive_count']} drivers can still win: {names}. "
            f"{analysis['eliminated']} are out with {analysis['remaining_count']} weekends remaining."
        )

    if any(word in q for word in ("form", "hot", "recent", "last")):
        hot = analysis.get("hottest")
        if not hot:
            return "Recent race results are not in the cache yet, so form is empty."
        return (
            f"{hot['name']} has the best recent clip among the top group: "
            f"{hot['form_avg']} points per race over the last {FORM_WINDOW} GPs."
        )

    if any(word in q for word in ("next", "baku", "weekend", "race")):
        nxt = grid.get("next_race") or {}
        return (
            f"Next: {nxt.get('name')} at {nxt.get('circuit')} on {nxt.get('date')}. "
            f"{analysis['remaining_count']} races remain, {analysis['max_remaining']} points available."
        )

    insights = analysis.get("insights") or []
    return insights[0] if insights else "No championship model yet."
