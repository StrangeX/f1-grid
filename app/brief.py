from __future__ import annotations

from typing import Any

import httpx

from app import cache, settings
from app.analytics import analyze, analyze_constructors, answer_question, attach_odds
from app.simulate import get_forecast


def _prompt(analysis: dict[str, Any], grid: dict[str, Any]) -> str:
    return (
        "You are an F1 championship analyst. Rewrite the insights in 3-5 sharp sentences. "
        "Use only these facts. Do not invent weather, quotes, or race results.\n"
        f"Season {grid.get('season')} after round {grid.get('round')}.\n"
        f"Insights: {analysis.get('insights')}\n"
        f"Alive: {analysis.get('alive_count')} / eliminated {analysis.get('eliminated')}\n"
        f"Remaining races: {analysis.get('remaining_count')}, max points {analysis.get('max_remaining')}\n"
        f"Hottest: {analysis.get('hottest')}\n"
        f"Next race: {grid.get('next_race')}"
    )


async def _llm_text(prompt: str, max_tokens: int = 220) -> str | None:
    if not settings.OPENAI_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0)) as client:
            res = await client.post(
                f"{settings.OPENAI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                json={
                    "model": settings.OPENAI_MODEL,
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": "Use only supplied championship facts."},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            res.raise_for_status()
            text = res.json()["choices"][0]["message"]["content"].strip()
            return text or None
    except Exception:
        return None


async def full_analysis(grid: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    forecast = await get_forecast(grid)
    drivers = attach_odds(analyze(grid), forecast.get("drivers") or {}, "code")
    constructors = attach_odds(analyze_constructors(grid), forecast.get("constructors") or {}, "id")
    drivers["forecast_runs"] = forecast.get("runs", 0)
    constructors["forecast_runs"] = forecast.get("runs", 0)
    if drivers.get("contenders"):
        lead = drivers["contenders"][0]
        drivers.setdefault("insights", []).append(
            f"Monte Carlo ({forecast.get('runs')} remaining-season runs): "
            f"{lead['name']} is champion in {lead.get('title_pct', 0)}% of simulations."
        )
    if constructors.get("contenders"):
        lead = constructors["contenders"][0]
        constructors.setdefault("insights", []).append(
            f"Constructors forecast: {lead['name']} takes the cup in {lead.get('title_pct', 0)}% of simulations."
        )
    return drivers, constructors, forecast


async def get_brief(grid: dict[str, Any], kind: str = "drivers") -> dict[str, Any]:
    drivers, constructors, _forecast = await full_analysis(grid)
    analysis = constructors if kind == "constructors" else drivers
    key = (
        f"f1:brief:v3:{kind}:{grid.get('season')}:{grid.get('round')}:"
        f"{analysis.get('alive_count')}:{analysis.get('clinch_needed')}"
    )
    cached = await cache.get_json(key)
    if cached:
        cached["analysis"] = analysis
        return cached

    llm = await _llm_text(_prompt(analysis, grid))
    payload = {
        "text": llm or " ".join(analysis.get("insights") or []),
        "source": "llm" if llm else "model",
        "insights": analysis.get("insights") or [],
    }
    await cache.set_json(key, payload, settings.CACHE_TTL_SEC)
    payload["analysis"] = analysis
    return payload


async def ask(grid: dict[str, Any], question: str) -> dict[str, str]:
    drivers, constructors, _forecast = await full_analysis(grid)
    drivers["constructor_contenders"] = constructors.get("contenders") or []
    local = answer_question(question, drivers, grid)
    llm = await _llm_text(
        "Answer the user in 2-4 sentences using only these facts.\n"
        f"Question: {question}\nFacts: {local}\nInsights: {drivers.get('insights')}\n",
        max_tokens=160,
    )
    return {
        "answer": llm or local,
        "source": "llm" if llm else "model",
    }
