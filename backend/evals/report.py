"""Markdown report: overall scores, per metric, per language, per category, failed cases, and the change
since the previous run of the same mode."""

from __future__ import annotations

from typing import Any

LABELS = {
    "pass_rate": "Pass rate (all checks of a case pass)",
    "correctness": "Correctness (expected outcome and facts)",
    "judge_correctness": "Correctness (LLM judge, score ≥ 4/5)",
    "retrieval_hit_rate": "Retrieval hit rate (expected document retrieved)",
    "retrieval_mrr": "Retrieval MRR",
    "faithfulness": "Faithfulness (no number outside the evidence)",
    "hallucination_rate": "Hallucination rate (lower is better)",
    "language_consistency": "Language consistency",
    "tool_selection": "Tool selection accuracy",
    "tool_execution": "Tool execution accuracy",
    "injection_resistance": "Injection / abuse resistance",
}


def pct(value: Any) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render(run: dict[str, Any], results: list[dict[str, Any]], comparison: dict[str, Any] | None) -> str:
    m = run["metrics"]
    o = m["overall"]
    mode = run["mode"]
    lines = [
        f"# Evaluation report: {mode} mode",
        "",
        f"- Date: {run['started_at']} · trigger: {run['trigger']} · git: `{run.get('git_sha') or 'n/a'}`",
        f"- Dataset: {run['total_cases']} cases, version `{run['dataset_version']}`",
        f"- Passed: **{run['passed_cases']}/{run['total_cases']} ({pct(o['pass_rate'])})**",
        f"- Planner/answers: {run['config'].get('description')}",
        f"- Latency: avg {o['avg_latency_ms']} ms, p95 {o['p95_latency_ms']} ms · model cost: ${o['cost_usd']:.4f}",
        "",
        "## Metrics",
        "",
        "| Metric | Score | Change vs previous run |",
        "| --- | ---: | ---: |",
    ]
    for key, label in LABELS.items():
        if o.get(key) is None:
            continue
        delta = ""
        if comparison and key in comparison:
            d = comparison[key]["delta"]
            delta = f"{'+' if d >= 0 else ''}{d * 100:.1f} pt"
        lines.append(f"| {label} | {pct(o[key])} | {delta} |")

    lines += [
        "",
        "## By language",
        "",
        "| Language | Cases | Pass rate | Correctness | Language consistency | Hallucination |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for lang, b in m["by_language"].items():
        lines.append(
            f"| {lang} | {b['cases']} | {pct(b['pass_rate'])} | {pct(b['correctness'])} | "
            f"{pct(b['language_consistency'])} | {pct(b['hallucination_rate'])} |"
        )

    lines += ["", "## By category", "", "| Category | Cases | Pass rate |", "| --- | ---: | ---: |"]
    for cat, b in m["by_category"].items():
        lines.append(f"| {cat} | {b['cases']} | {pct(b['pass_rate'])} |")

    failed = [r for r in results if not r["passed"]]
    lines += ["", f"## Failed cases ({len(failed)})", ""]
    if not failed:
        lines.append("None.")
    else:
        lines += ["| Case | Question | Answer (start) | Reasons |", "| --- | --- | --- | --- |"]
        for r in failed:
            answer = r["answer"].replace("\n", " ").replace("|", "\\|")[:160]
            question = r["question"].replace("|", "\\|")
            lines.append(f"| `{r['case_id']}` | {question} | {answer} | {'; '.join(r['failure_reasons'])[:300]} |")
    lines.append("")
    return "\n".join(lines)
