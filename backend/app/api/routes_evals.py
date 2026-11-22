"""Evaluation results (written by ``python -m evals.run``). Runs are platform-wide, not per shop."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import Session, Staff
from app.errors import NotFound
from app.models import EvaluationResult, EvaluationRun

router = APIRouter(prefix="/api/v1", tags=["evaluations"])


def _run(run: EvaluationRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "status": run.status,
        "mode": run.mode,
        "trigger": run.trigger,
        "git_sha": run.git_sha,
        "dataset_version": run.dataset_version,
        "config": run.config,
        "total_cases": run.total_cases,
        "passed_cases": run.passed_cases,
        "metrics": run.metrics,
    }


@router.get("/evals/runs")
async def list_runs(_: Staff, session: Session, limit: int = Query(20, ge=1, le=100)) -> list[dict[str, Any]]:
    rows = (await session.scalars(select(EvaluationRun).order_by(EvaluationRun.started_at.desc()).limit(limit))).all()
    return [_run(r) for r in rows]


@router.get("/evals/runs/{run_id}")
async def get_run(run_id: uuid.UUID, _: Staff, session: Session, failed_only: bool = False) -> dict[str, Any]:
    run = await session.get(EvaluationRun, run_id)
    if run is None:
        raise NotFound("Evaluation run not found.")
    query = select(EvaluationResult).where(EvaluationResult.run_id == run_id).order_by(EvaluationResult.case_id)
    if failed_only:
        query = query.where(EvaluationResult.passed.is_(False))
    results = (await session.scalars(query)).all()
    return {
        **_run(run),
        "results": [
            {
                "case_id": r.case_id,
                "language": r.language,
                "category": r.category,
                "question": r.question,
                "answer": r.answer,
                "passed": r.passed,
                "scores": r.scores,
                "failure_reasons": r.failure_reasons,
                "details": r.details,
                "latency_ms": r.latency_ms,
                "cost_usd": float(r.cost_usd or 0),
            }
            for r in results
        ],
    }


@router.get("/public/eval-summary", tags=["public"], summary="Latest completed evaluation, aggregated (landing page)")
async def public_summary(session: Session) -> dict[str, Any]:
    rows = (
        await session.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.status == "completed")
            .order_by(EvaluationRun.started_at.desc())
            .limit(10)
        )
    ).all()
    latest_full = next((r for r in rows if r.mode == "full"), None)
    latest_offline = next((r for r in rows if r.mode == "offline"), None)

    def summary(run: EvaluationRun | None) -> dict[str, Any] | None:
        if run is None:
            return None
        metrics = run.metrics or {}
        return {
            "started_at": run.started_at.isoformat(),
            "mode": run.mode,
            "total_cases": run.total_cases,
            "passed_cases": run.passed_cases,
            "overall": metrics.get("overall"),
            "by_language": metrics.get("by_language"),
            "models": {k: v for k, v in (run.config or {}).items() if k in ("models", "judge", "router_mode")},
        }

    return {"full": summary(latest_full), "offline": summary(latest_offline)}
