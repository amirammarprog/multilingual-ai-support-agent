"""A full-mode evaluation interrupted by provider failures is resumable and never scores a case that was
answered by the no-LLM fallback."""

import pytest
from sqlalchemy import select

from app.agent.prompts import Answer, Plan
from app.db import tenant_session
from app.llm.client import LLMUnavailable, LLMUsage, set_llm
from app.models import EvaluationResult, EvaluationRun
from evals import run as eval_run
from evals.dataset import CASES
from evals.judge import Verdict
from tests.helpers import plan

pytestmark = pytest.mark.integration
IDS = ["prod-en-01", "prod-fr-01", "prod-ar-01"]
QUESTION = {c["id"]: c["question"] for c in CASES}


class FlakyLLM:
    """Plans a product lookup, answers from it, and judges; fails the planner for chosen questions."""

    available = True

    def __init__(self, failing_questions: set[str]) -> None:
        self.failing = failing_questions

    def describe(self):
        return [{"provider": "flaky", "base_url": "test", "fast": "flaky-small", "smart": "flaky-big"}]

    async def structured(self, *, messages, schema, tier, purpose, max_tokens=400):
        usage = LLMUsage(purpose, "flaky", "flaky-big", tier, prompt_tokens=10, completion_tokens=5)
        text = messages[-1]["content"]
        if schema is Plan:
            if any(q in text for q in self.failing):
                raise LLMUnavailable(
                    [
                        LLMUsage(
                            purpose, "flaky", "flaky-big", tier, success=False, error="rate limited, retry after 3600s"
                        )
                    ]
                )
            return Plan.model_validate(plan(intent="product_info", tools=["get_product_details"], sku="ORB-X5-128")), [
                usage
            ]
        if schema is Answer:
            return Answer(answer="The Orbix X5 128 GB costs 1299.000 TND.", source_ids=["T1"], answered=True), [usage]
        return Verdict(correctness=5, faithful=True, reason="matches the reference"), [usage]


async def test_interrupted_full_run_is_resumed_without_double_counting():
    flaky = FlakyLLM({QUESTION["prod-fr-01"]})
    set_llm(flaky)
    try:
        first = await eval_run.main(["--mode", "full", "--ids", *IDS, "--no-write", "--trigger", "test"])
        assert first == 3  # incomplete
        async with tenant_session(None) as session:
            run = await session.scalar(
                select(EvaluationRun).where(EvaluationRun.trigger == "test").order_by(EvaluationRun.started_at.desc())
            )
            stored = set(
                (await session.scalars(select(EvaluationResult.case_id).where(EvaluationResult.run_id == run.id))).all()
            )
        assert run.status == "incomplete"
        assert stored == {"prod-en-01", "prod-ar-01"}  # the failed case was not scored on the fallback

        flaky.failing = set()  # the quota is back
        second = await eval_run.main(["--mode", "full", "--ids", *IDS, "--no-write", "--resume", str(run.id)])
        assert second == 0
        async with tenant_session(None) as session:
            run = await session.get(EvaluationRun, run.id)
            rows = (await session.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id))).all()
        assert run.status == "completed" and run.total_cases == 3
        assert sorted(r.case_id for r in rows) == sorted(IDS)
        assert all(r.details["judge"]["correctness"] == 5 for r in rows)
        assert run.metrics["overall"]["judge_agreement"] is not None
    finally:
        set_llm(None)


async def test_max_new_cases_paces_a_daily_quota():
    set_llm(FlakyLLM(set()))
    try:
        result = await eval_run.main(
            ["--mode", "full", "--ids", *IDS, "--no-write", "--trigger", "test-pace", "--max-new-cases", "1"]
        )
        assert result == 3
        async with tenant_session(None) as session:
            run = await session.scalar(select(EvaluationRun).where(EvaluationRun.trigger == "test-pace"))
            count = len(
                (await session.scalars(select(EvaluationResult.id).where(EvaluationResult.run_id == run.id))).all()
            )
        assert count == 1 and run.status == "incomplete"
    finally:
        set_llm(None)
