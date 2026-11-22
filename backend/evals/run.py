"""Run the evaluation suite against the real agent and database.

    python -m evals.run --mode offline           # no LLM: rule-based planner + templates (CI default)
    python -m evals.run --mode full              # LLM planner/responder + LLM judge (needs a provider)
    python -m evals.run --mode full --limit 10   # quick sample

Each case runs in a fresh conversation (earlier turns first). Results go to the evaluation_runs /
evaluation_results tables (shown in the admin dashboard) and to evals/reports/<mode>-latest.{md,json}.
Only measured numbers are written; nothing is estimated.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.agent.service import handle_turn
from app.config import get_settings
from app.db import dispose_engine, tenant_session
from app.llm.client import get_llm
from app.models import Conversation, Customer, EvaluationResult, EvaluationRun, Shop
from app.tools.registry import WIDGET_SCOPES
from evals import judge as judge_module
from evals.dataset import CASES
from evals.metrics import METRIC_KEYS, aggregate, evaluate_case
from evals.report import render

REPORTS = Path(__file__).resolve().parent / "reports"


def dataset_version() -> str:
    source = (Path(__file__).resolve().parent / "dataset.py").read_bytes()
    return hashlib.sha256(source).hexdigest()[:12]


def git_sha() -> str | None:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha[:12]
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short=12", "HEAD"],  # noqa: S607 - git from PATH, fixed arguments
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout.strip()
            or None
        )
    except Exception:
        return None


async def run_case(shop: Shop, case: dict[str, Any], use_llm: bool) -> tuple[Any, int]:
    async with tenant_session(shop.id) as session:
        customer = None
        if case.get("customer"):
            customer = await session.scalar(
                select(Customer).where(Customer.shop_id == shop.id, Customer.external_ref == case["customer"])
            )
        conversation = Conversation(shop_id=shop.id, customer_id=customer.id if customer else None)
        session.add(conversation)
        await session.commit()
        reply = None
        started = time.perf_counter()
        for text in [*case.get("turns", []), case["question"]]:
            started = time.perf_counter()
            reply = await handle_turn(
                session,
                shop=shop,
                conversation_id=conversation.id,
                customer_id=customer.id if customer else None,
                text=text,
                actor="eval",
                scopes=WIDGET_SCOPES,
                use_llm=use_llm,
            )
            await session.commit()
        return reply, int((time.perf_counter() - started) * 1000)


async def previous_overall(mode: str) -> dict[str, Any] | None:
    async with tenant_session(None) as session:
        run = await session.scalar(
            select(EvaluationRun)
            .where(EvaluationRun.mode == mode, EvaluationRun.status == "completed")
            .order_by(EvaluationRun.started_at.desc())
        )
        if run is not None:
            return run.metrics.get("overall")
    latest = REPORTS / f"{mode}-latest.json"
    if latest.exists():
        return json.loads(latest.read_text(encoding="utf-8"))["metrics"]["overall"]
    return None


def write_outputs(
    mode: str, markdown: str, summary: dict[str, Any], results: list[dict[str, Any]], write_latest: bool
) -> None:
    """Reports for the README/CI (evals/reports) and the GitHub Actions job summary."""
    if write_latest:
        REPORTS.mkdir(exist_ok=True)
        (REPORTS / f"{mode}-latest.md").write_text(markdown, encoding="utf-8")
        (REPORTS / f"{mode}-latest.json").write_text(
            json.dumps({**summary, "results": results}, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        keys = ("mode", "trigger", "started_at", "git_sha", "dataset_version", "total_cases", "passed_cases")
        entry = {k: summary[k] for k in keys} | {"overall": summary["metrics"]["overall"]}
        with (REPORTS / "history.jsonl").open("a", encoding="utf-8") as history:
            history.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as fh:
            fh.write(markdown)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run")
    parser.add_argument("--mode", choices=["offline", "full"], default="offline")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", nargs="*", default=None, help="run only these case ids")
    parser.add_argument("--trigger", default=os.environ.get("EVAL_TRIGGER", "local"))
    parser.add_argument("--no-judge", action="store_true", help="full mode without the LLM judge")
    parser.add_argument("--min-pass-rate", type=float, default=0.0, help="exit 1 below this pass rate")
    parser.add_argument("--max-hallucination-rate", type=float, default=1.0)
    parser.add_argument("--no-write", action="store_true", help="do not overwrite evals/reports/*-latest.*")
    args = parser.parse_args(argv)

    settings = get_settings()
    llm = get_llm()
    use_llm = args.mode == "full"
    if use_llm and not llm.available:
        print("full mode needs an LLM provider (LLM_PRIMARY_API_KEY or a local LLM_PRIMARY_BASE_URL)", file=sys.stderr)
        return 2
    cases = [c for c in CASES if not args.ids or c["id"] in args.ids]
    if args.limit:
        cases = cases[: args.limit]

    async with tenant_session(None) as session:
        shop = await session.scalar(select(Shop).where(Shop.slug == "demo-shop"))
    if shop is None:
        print("demo-shop not found: run `python -m app.cli seed` first", file=sys.stderr)
        return 2

    config = {
        "description": (
            "LLM planner and responder, LLM judge"
            if use_llm
            else "offline: rule-based planner and deterministic templates, no LLM"
        ),
        "models": llm.describe() if use_llm else [],
        "judge": None if (not use_llm or args.no_judge) else llm.describe()[0]["smart"],
        "router_mode": settings.router_mode,
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
        "retrieval_min_score": settings.retrieval_min_score,
    }
    started_at = datetime.now(UTC)
    async with tenant_session(None) as session:
        run = EvaluationRun(
            mode=args.mode,
            trigger=args.trigger,
            git_sha=git_sha(),
            dataset_version=dataset_version(),
            config=config,
            total_cases=len(cases),
            status="running",
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    results: list[dict[str, Any]] = []
    for i, case in enumerate(cases, start=1):
        reply, latency = await run_case(shop, case, use_llm)
        verdict = None
        if use_llm and not args.no_judge:
            verdict = await judge_module.judge(llm, case, reply.answer, reply.debug.get("evidence", ""))
        evaluated = evaluate_case(case, reply, verdict)
        cost = sum(u["cost_usd"] for u in reply.debug.get("usages", [])) + (verdict or {}).get("cost_usd", 0.0)
        results.append(
            {
                "case_id": case["id"],
                "language": case["language"],
                "category": case["category"],
                "question": case["question"],
                "answer": reply.answer,
                "outcome": reply.outcome,
                "passed": evaluated["passed"],
                "scores": evaluated["scores"],
                "failure_reasons": evaluated["reasons"],
                "latency_ms": latency,
                "cost_usd": cost,
                "details": {
                    "outcome": reply.outcome,
                    "language": reply.language,
                    "tools": [{"tool": t["tool"], "status": t["status"]} for t in reply.debug.get("tool_results", [])],
                    "plan": reply.debug.get("plan"),
                    "plan_source": reply.debug.get("plan_source"),
                    "retrieval_confidence": (reply.debug.get("retrieval") or {}).get("confidence"),
                    "judge": verdict,
                },
            }
        )
        mark = "PASS" if evaluated["passed"] else "FAIL"
        print(
            f"[{i:3}/{len(cases)}] {mark} {case['id']:<22} {latency:>6} ms  {'; '.join(evaluated['reasons'])[:110]}",
            flush=True,
        )

    metrics = aggregate(results)
    previous = await previous_overall(args.mode)
    comparison = None
    if previous:
        comparison = {
            k: {
                "previous": previous[k],
                "current": metrics["overall"][k],
                "delta": round(metrics["overall"][k] - previous[k], 4),
            }
            for k in ["pass_rate", *METRIC_KEYS]
            if previous.get(k) is not None and metrics["overall"].get(k) is not None
        }
        metrics["comparison"] = comparison
    passed = sum(1 for r in results if r["passed"])

    async with tenant_session(None) as session:
        run = await session.get(EvaluationRun, run_id)
        assert run is not None
        run.status, run.finished_at, run.passed_cases, run.metrics = "completed", datetime.now(UTC), passed, metrics
        for r in results:
            session.add(
                EvaluationResult(
                    run_id=run_id,
                    case_id=r["case_id"],
                    language=r["language"],
                    category=r["category"],
                    question=r["question"],
                    answer=r["answer"],
                    passed=r["passed"],
                    scores=r["scores"],
                    details=r["details"],
                    failure_reasons=r["failure_reasons"],
                    latency_ms=r["latency_ms"],
                    cost_usd=Decimal(str(round(r["cost_usd"], 6))),
                )
            )
        await session.commit()

    summary = {
        "id": str(run_id),
        "mode": args.mode,
        "trigger": args.trigger,
        "started_at": started_at.isoformat(),
        "git_sha": git_sha(),
        "dataset_version": dataset_version(),
        "config": config,
        "total_cases": len(cases),
        "passed_cases": passed,
        "metrics": metrics,
    }
    markdown = render(summary, results, comparison)
    write_outputs(args.mode, markdown, summary, results, write_latest=not args.no_write)
    o = metrics["overall"]
    print(
        f"\n{passed}/{len(cases)} passed · pass rate {o['pass_rate']:.3f} · hallucination rate "
        f"{o['hallucination_rate']:.3f} · run {run_id}"
    )
    await dispose_engine()
    if o["pass_rate"] < args.min_pass_rate or o["hallucination_rate"] > args.max_hallucination_rate:
        print("quality gate failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
