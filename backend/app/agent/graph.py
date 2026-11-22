"""The support agent as a LangGraph state machine.

guard ──blocked──> refuse
  │
route (cheap vs capable model)
  │
plan (LLM structured output; rule-based planner if no model is reachable)
  ├─ greeting / out of scope ──> canned reply
  │
execute (tools through the permission-checked registry + hybrid retrieval)
  │
respond (LLM writes from evidence only; deterministic replies for identity checks,
  │        hand-offs and the "I don't know" path)
validate (numbers, contact data, promises, prompt leaks, language)
  ├─ problems, first time ──> respond again with feedback
  └─ problems twice ──> fallback (template built from tool data, or "I don't know")
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import templates
from app.agent.heuristics import _YES, EMAIL_RE, ORDER_RE, SKU_RE, find_order_number, find_sku, heuristic_plan
from app.agent.prompts import Answer, Plan, planner_messages, responder_messages
from app.config import Settings
from app.language import detect_language
from app.llm.client import LLMClient, LLMUnavailable
from app.llm.router import route
from app.models import ToolCallStatus
from app.observability import tracer
from app.rag.retrieval import RetrievalResult, retrieve
from app.security.guardrails import check_output, normalize_input, scan_input
from app.tools.registry import ToolContext, ToolRegistry, ToolResult

MAX_TOOLS_PER_TURN = 3
INFO_ERRORS = {
    "verification_required",
    "verification_failed",
    "verification_locked",
    "order_not_found_for_customer",
    "order_number_missing",
    "product_not_identified",
    "contact_email_required",
    "ticket_limit_reached",
}


class AgentState(TypedDict, total=False):
    message: str
    history: list[dict[str, str]]
    memory: dict[str, Any]
    language: str
    dialect: str | None
    guard: dict[str, Any]
    route: dict[str, Any]
    plan: dict[str, Any]
    plan_source: str
    tool_results: list[dict[str, Any]]
    retrieval: dict[str, Any] | None
    evidence: str
    answer: str
    source_ids: list[str]
    outcome: str
    attempts: int
    feedback: str | None
    validation: dict[str, Any]
    usages: list[dict[str, Any]]
    degraded: bool
    products: list[dict[str, Any]]
    sources: list[dict[str, Any]]


@dataclass
class AgentDeps:
    session: AsyncSession
    ctx: ToolContext
    shop: dict[str, Any]
    llm: LLMClient
    registry: ToolRegistry
    settings: Settings
    prior_language: str | None = None
    customer_email: str | None = None
    use_llm: bool = True
    canary: str = field(default_factory=lambda: f"ref-{uuid.uuid4().hex[:12]}")
    retrieval_cache: dict[str, RetrievalResult] = field(default_factory=dict)


def _key(state: AgentState) -> str:
    return templates.lang_key(state.get("language", "en"), state.get("dialect"))


def _user_texts(state: AgentState) -> str:
    return "\n".join([m["content"] for m in state.get("history", []) if m["role"] == "user"] + [state["message"]])


# --------------------------------------------------------------------------------------- nodes ----
async def guard(state: AgentState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    deps = runtime.context
    message = normalize_input(state["message"], deps.settings.max_message_chars)
    detected = detect_language(message, prior=deps.prior_language)
    verdict = scan_input(message)
    deps.ctx.language = detected.tag
    return {
        "message": message,
        "language": detected.code,
        "dialect": detected.dialect,
        "guard": verdict.as_dict(),
        "attempts": 0,
        "usages": [],
        "tool_results": [],
        "degraded": False,
    }


async def refuse(state: AgentState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    return {
        "answer": templates.render("refuse", state["language"], state.get("dialect")),
        "outcome": "refused",
        "source_ids": [],
        "plan": {},
        "route": {},
    }


async def route_node(state: AgentState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    decision = route(
        state["message"],
        language=state["language"],
        dialect=state.get("dialect"),
        history_turns=len(state.get("history", [])) // 2,
        guard_action=state["guard"]["action"],
        settings=runtime.context.settings,
    )
    return {"route": decision.as_dict()}


def _sanitise_plan(plan: Plan, state: AgentState) -> Plan:
    """Never trust identifiers the model produced: keep only those the customer actually wrote
    (or that come from the server-side conversation memory)."""
    user_text = _user_texts(state)
    memory = state.get("memory", {})
    data = plan.model_dump()

    known_orders = {f"{m.group(1).upper()}-{m.group(2)}" for m in ORDER_RE.finditer(user_text)}
    if memory.get("last_order_number"):
        known_orders.add(memory["last_order_number"])
    candidate = find_order_number(data["order_number"] or "") if data["order_number"] else None
    data["order_number"] = candidate if candidate in known_orders else None

    emails = {e.lower() for e in EMAIL_RE.findall(user_text)}
    data["email"] = data["email"].strip().lower() if data["email"] and data["email"].strip().lower() in emails else None

    if data["sku"]:
        sku = data["sku"].strip().upper()
        data["sku"] = sku if SKU_RE.fullmatch(sku) else None

    tools: list[str] = []
    for name in data["tools"]:
        if name not in tools:
            tools.append(name)
    intent_tool = {
        "order_status": "get_order_status",
        "human_handoff": "escalate_to_human",
        "create_ticket": "create_support_ticket",
    }.get(data["intent"])
    if intent_tool and intent_tool not in tools:
        tools.insert(0, intent_tool)
    if data["intent"] in ("greeting", "out_of_scope"):
        tools = []
    data["tools"] = tools[:MAX_TOOLS_PER_TURN]

    # Deterministic backstop for small models that pick the right tool but forget an identifier the
    # customer clearly wrote in this message (or that the conversation memory already holds).
    message = state["message"]
    if not data["order_number"] and {"get_order_status", "create_support_ticket"} & set(data["tools"]):
        data["order_number"] = find_order_number(message) or (
            memory.get("last_order_number") if data["intent"] == "order_status" else None
        )
    if not data["email"] and EMAIL_RE.search(message):
        data["email"] = EMAIL_RE.search(message).group(0).lower()
    if not data["sku"] and {"get_product_details", "check_stock"} & set(data["tools"]):
        data["sku"] = find_sku(message)
    return Plan.model_validate(data)


async def plan_node(state: AgentState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    deps = runtime.context
    memory = state.get("memory", {})
    usages: list[dict[str, Any]] = []
    degraded = False
    if memory.get("offered_human") and _YES.search(state["message"]) and len(state["message"].split()) <= 4:
        plan, source = heuristic_plan(state["message"], memory), "rule"
    elif deps.use_llm and deps.llm.available:
        try:
            plan, calls = await deps.llm.structured(
                messages=planner_messages(
                    shop_name=deps.shop["name"],
                    message=state["message"],
                    history=state.get("history", []),
                    memory=memory,
                    flagged=state["guard"]["action"] == "flag",
                ),
                schema=Plan,
                tier=state["route"]["tier"],
                purpose="plan",
                max_tokens=350,
            )
            usages += [u.as_dict() for u in calls]
            source = "llm"
        except LLMUnavailable as exc:
            usages += [u.as_dict() for u in exc.usages]
            plan, source, degraded = heuristic_plan(state["message"], memory), "heuristic", True
    else:
        plan, source = heuristic_plan(state["message"], memory), "heuristic"
        degraded = deps.use_llm  # a model was expected but none is configured
    plan = _sanitise_plan(plan, state)
    return {
        "plan": plan.model_dump(),
        "plan_source": source,
        "usages": state.get("usages", []) + usages,
        "degraded": degraded,
    }


async def canned(state: AgentState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    deps = runtime.context
    intent = state["plan"]["intent"]
    if intent == "greeting":
        key, outcome = "greeting", "answered"
    elif "price_manipulation" in state["guard"]["categories"]:
        key, outcome = "no_price_change", "refused"
    else:
        key, outcome = "out_of_scope", "refused" if state["guard"]["action"] != "allow" else "out_of_scope"
    return {
        "answer": templates.render(key, state["language"], state.get("dialect"), shop=deps.shop["name"]),
        "outcome": outcome,
        "source_ids": [],
    }


def _synthetic(name: str, code: str) -> dict[str, Any]:
    return {
        "tool": name,
        "ok": False,
        "status": ToolCallStatus.INVALID.value,
        "error": code,
        "data": {},
        "executed": False,
    }


def _record(result: ToolResult) -> dict[str, Any]:
    return {
        **result.for_model(),
        "status": result.status.value,
        "executed": True,
        "latency_ms": result.latency_ms,
    }


async def _run_tool(deps: AgentDeps, name: str, args: dict[str, Any]) -> ToolResult:
    with tracer.span(name, as_type="tool", input=args) as span:
        result = await deps.registry.execute(deps.session, name, args, deps.ctx)
        span.update(output=result.for_model())
    return result


async def execute(state: AgentState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    deps = runtime.context
    plan = state["plan"]
    memory = state.get("memory", {})
    results: list[dict[str, Any]] = []
    resolved_sku: str | None = plan.get("sku")

    async def resolve_sku() -> str | None:
        nonlocal resolved_sku
        if resolved_sku:
            return resolved_sku
        query = plan.get("product_query")
        if not query:
            return memory.get("last_sku")
        search = await _run_tool(deps, "search_products", {"query": query[:200], "limit": 3})
        results.append(_record(search))
        if search.ok and search.data and search.data["results"]:
            resolved_sku = search.data["results"][0]["sku"]
        # "And how much is it?": nothing matches the words, so it is about the product just discussed.
        return resolved_sku or memory.get("last_sku")

    for name in plan["tools"]:
        if name == "search_products":
            args: dict[str, Any] = {
                "query": (plan.get("product_query") or state["message"])[:200],
                "limit": 5,
            }
            if plan.get("max_price"):
                args["max_price"] = plan["max_price"]
            results.append(_record(await _run_tool(deps, name, args)))
        elif name in ("get_product_details", "check_stock"):
            sku = await resolve_sku()
            if not sku:
                results.append(_synthetic(name, "product_not_identified"))
                continue
            args = {"sku": sku}
            if name == "check_stock" and plan.get("quantity"):
                args["quantity"] = max(1, min(100, int(plan["quantity"])))
            result = await _run_tool(deps, name, args)
            if result.status == ToolCallStatus.NOT_FOUND and plan.get("sku") and not plan.get("product_query"):
                # A SKU that does not exist (typo, or invented by the model): try a catalogue search instead.
                plan = {**plan, "sku": None, "product_query": state["message"]}
                resolved_sku = None
                sku = await resolve_sku()
                if sku:
                    result = await _run_tool(deps, name, {**args, "sku": sku})
            results.append(_record(result))
        elif name == "get_order_status":
            if not plan.get("order_number"):
                results.append(_synthetic(name, "order_number_missing"))
                continue
            args = {"order_number": plan["order_number"]}
            if plan.get("email"):
                args["email"] = plan["email"]
            results.append(_record(await _run_tool(deps, name, args)))
        elif name == "create_support_ticket":
            summary = (plan.get("ticket_summary") or state["message"])[:200]
            args = {
                "subject": summary if len(summary) >= 3 else "Customer request",
                "description": state["message"][:2000] if len(state["message"]) >= 5 else summary,
                "category": {"order_status": "order", "product_info": "product"}.get(plan["intent"], "other"),
            }
            if re.search(r"warrant|garantie|ضمان|broken|cass|panne|défaut|defect|عطل|مكسور", state["message"], re.I):
                args["category"] = "warranty"
            elif re.search(r"return|retour|refund|rembours|إرجاع|استرجاع|ترجيع", state["message"], re.I):
                args["category"] = "return"
            if plan.get("order_number"):
                args["order_number"] = plan["order_number"]
            if plan.get("email"):
                args["contact_email"] = plan["email"]
            results.append(_record(await _run_tool(deps, name, args)))
        elif name == "escalate_to_human":
            args = {
                "reason": (plan.get("ticket_summary") or state["message"])[:500] or "Customer asked for a person",
                "urgency": "high" if plan.get("urgent") else "normal",
            }
            if plan.get("email"):
                args["contact_email"] = plan["email"]
            results.append(_record(await _run_tool(deps, name, args)))

    retrieval: RetrievalResult | None = None
    wants_kb = plan.get("knowledge_query") or plan["intent"] in ("policy", "product_info")
    if wants_kb and plan["intent"] not in ("human_handoff",):
        query = plan.get("knowledge_query") or state["message"]
        translations = {lang: plan.get(f"translation_{lang}") for lang in ("en", "fr", "ar")}
        with tracer.span("retrieve", as_type="retriever", input={"query": query, "translations": translations}) as span:
            retrieval = await retrieve(
                deps.session,
                deps.ctx.shop_id,
                query,
                state["language"],
                translations={k: v for k, v in translations.items() if v},
                settings=deps.settings,
            )
            span.update(output={"confidence": retrieval.confidence, "chunks": len(retrieval.chunks)})
    return {
        "tool_results": results,
        "retrieval": retrieval.as_dict() if retrieval else None,
        "evidence": _evidence(results, retrieval),
        "products": _products(results),
    }


def _evidence(results: list[dict[str, Any]], retrieval: RetrievalResult | None) -> str:
    parts = []
    for i, r in enumerate([r for r in results if r["ok"]], start=1):
        parts.append(f"[T{i}] {r['tool']}: {json.dumps(r['data'], ensure_ascii=False, default=str)}")
    if retrieval and retrieval.answerable:
        for c in retrieval.chunks:
            heading = f" > {c.heading}" if c.heading else ""
            parts.append(f"[{c.source_id}] {c.title}{heading}:\n{c.content}")
    return "\n\n".join(parts)


def _products(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for r in results:
        if not r["ok"]:
            continue
        data = r["data"] or {}
        rows = data.get("results") if r["tool"] == "search_products" else [data] if "sku" in data else []
        for row in rows or []:
            entry = seen.setdefault(row["sku"], {"sku": row["sku"]})
            for key in ("name", "price", "currency", "stock_status"):
                if row.get(key) is not None:
                    entry[key] = row[key]
    return list(seen.values())[:6]


def _info_reply(state: AgentState, deps: AgentDeps) -> tuple[str, str] | None:
    """Deterministic replies for identity checks and missing details."""
    for r in state.get("tool_results", []):
        code = r.get("error")
        if r["ok"] or code not in INFO_ERRORS:
            continue
        order = state["plan"].get("order_number") or ""
        lang, dialect = state["language"], state.get("dialect")
        if code == "order_not_found_for_customer":
            return templates.render("order_not_found", lang, dialect, order=order), "needs_info"
        if code == "verification_locked":
            return templates.render("verification_locked", lang, dialect, email=deps.shop["support_email"]), "refused"
        return templates.render(code, lang, dialect, order=order), "needs_info"
    return None


def template_answer(state: AgentState, deps: AgentDeps) -> str | None:
    """Answer built only from tool data (used for hand-offs, tickets and as the safe fallback)."""
    lang, dialect = state["language"], state.get("dialect")
    parts: list[str] = []
    for r in state.get("tool_results", []):
        if not r["ok"]:
            continue
        d = r["data"]
        if r["tool"] == "get_order_status":
            text = templates.render(
                "order_status", lang, dialect, order=d["order_number"], status_label=d["status_label"]
            )
            if d.get("carrier") and d.get("tracking_number"):
                text += templates.render(
                    "order_tracking", lang, dialect, carrier=d["carrier"], tracking=d["tracking_number"]
                )
            if d.get("delivered_on"):
                text += templates.render(
                    "order_delivered_on", lang, dialect, date=templates.format_date(d["delivered_on"], lang)
                )
            elif d.get("estimated_delivery_date"):
                text += templates.render(
                    "order_eta", lang, dialect, eta=templates.format_date(d["estimated_delivery_date"], lang)
                )
            elif d["status"] in ("shipped", "processing", "paid", "out_for_delivery", "pending"):
                text += templates.render("order_no_eta", lang, dialect)
            parts.append(text)
        elif r["tool"] == "check_stock":
            text = templates.render("stock", lang, dialect, name=d["name"], sku=d["sku"], label=d["stock_label"])
            if d.get("quantity_available"):
                text += templates.render("stock_low", lang, dialect, qty=d["quantity_available"])
            if d["stock_status"] == "out_of_stock":
                text += (
                    templates.render("restock_date", lang, dialect, date=templates.format_date(d["restock_date"], lang))
                    if d.get("restock_date")
                    else templates.render("restock_unknown", lang, dialect)
                )
            parts.append(text)
        elif r["tool"] == "get_product_details":
            parts.append(
                templates.render(
                    "product",
                    lang,
                    dialect,
                    name=d["name"],
                    sku=d["sku"],
                    price=d["price"],
                    currency=d["currency"],
                    warranty=d["warranty_months"],
                    label=d["stock_label"],
                )
            )
        elif r["tool"] == "search_products" and not any(
            x["tool"] in ("get_product_details", "check_stock") and x["ok"] for x in state["tool_results"]
        ):
            if d["results"]:
                lines = [f"- {p['name']} ({p['sku']}): {p['price']} {p['currency']}" for p in d["results"]]
                parts.append(templates.render("search_results", lang, dialect) + "\n" + "\n".join(lines))
            else:
                parts.append(templates.render("search_empty", lang, dialect))
        elif r["tool"] == "create_support_ticket":
            parts.append(
                templates.render(
                    "ticket_created", lang, dialect, ticket=d["ticket_number"], hours=d["reply_within_hours"]
                )
            )
        elif r["tool"] == "escalate_to_human":
            parts.append(
                templates.render(
                    "handoff",
                    lang,
                    dialect,
                    ticket=d["ticket_number"],
                    hours=d["reply_within_hours"],
                    support_hours=d["support_hours"],
                )
            )
    return " ".join(parts) if parts else None


async def respond(state: AgentState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    deps = runtime.context
    lang, dialect = state["language"], state.get("dialect")
    info = _info_reply(state, deps)
    retrieval_state = state.get("retrieval") or {}
    kb_answerable = bool(retrieval_state.get("chunks")) and retrieval_state.get("confidence", 0) >= retrieval_state.get(
        "threshold", 1
    )
    only_product_unclear = all(
        r.get("error") in (None, "product_not_identified") for r in state.get("tool_results", []) if not r["ok"]
    )
    # "Which product do you mean?" is only useful when nothing else answers the question.
    if info and kb_answerable and only_product_unclear:
        info = None
    if info:
        return {
            "answer": info[0],
            "outcome": info[1],
            "source_ids": [],
            "validation": {"ok": True, "skipped": True},
        }

    results = state.get("tool_results", [])
    if any(r["ok"] and r["tool"] in ("escalate_to_human", "create_support_ticket") for r in results):
        outcome = (
            "escalated" if any(r["ok"] and r["tool"] == "escalate_to_human" for r in results) else "ticket_created"
        )
        return {
            "answer": template_answer(state, deps) or "",
            "outcome": outcome,
            "source_ids": [],
            "validation": {"ok": True, "skipped": True},
        }

    retrieval = state.get("retrieval") or {}
    kb_ok = bool(retrieval) and retrieval["confidence"] >= retrieval["threshold"] and bool(retrieval["chunks"])
    has_tool_evidence = any(r["ok"] for r in results)
    if not has_tool_evidence and not kb_ok:
        return {
            "answer": templates.render("unknown", lang, dialect),
            "outcome": "unknown",
            "source_ids": [],
            "validation": {"ok": True, "skipped": True},
        }

    if not (deps.use_llm and deps.llm.available) or state.get("degraded"):
        # An empty product search says nothing; a relevant document section is the better answer.
        only_empty_search = all(
            r["tool"] == "search_products" and not (r.get("data") or {}).get("results") for r in results if r["ok"]
        )
        text = None if (kb_ok and only_empty_search) else template_answer(state, deps)
        if text:
            return {
                "answer": text,
                "outcome": "answered",
                "source_ids": [],
                "validation": {"ok": True, "skipped": True},
            }
        top = retrieval["chunks"][0]
        text = (
            templates.render("degraded", lang, dialect)
            + templates.render("source_hint", lang, dialect, title=top["title"])
            + f"\n«{top['content'][:500]}»\n"
            + templates.render("unknown", lang, dialect)
        )
        return {
            "answer": text,
            "outcome": "answered",
            "source_ids": [top["source_id"]],
            "validation": {"ok": True, "skipped": True},
        }

    try:
        answer, calls = await deps.llm.structured(
            messages=responder_messages(
                shop=deps.shop,
                message=state["message"],
                history=state.get("history", []),
                evidence=state.get("evidence", ""),
                language=templates.lang_key(lang, dialect),
                canary=deps.canary,
                feedback=state.get("feedback"),
            ),
            schema=Answer,
            tier=state["route"]["tier"],
            purpose="respond",
            max_tokens=450,
        )
    except LLMUnavailable as exc:
        usages = state.get("usages", []) + [u.as_dict() for u in exc.usages]
        text = template_answer(state, deps) or templates.render("unknown", lang, dialect)
        return {
            "answer": text,
            "outcome": "answered" if template_answer(state, deps) else "unknown",
            "source_ids": [],
            "usages": usages,
            "degraded": True,
            "validation": {"ok": True, "skipped": True},
        }
    usages = state.get("usages", []) + [u.as_dict() for u in calls]
    if not answer.answered or not answer.answer.strip():
        return {
            "answer": templates.render("unknown", lang, dialect),
            "outcome": "unknown",
            "source_ids": [],
            "usages": usages,
            "validation": {"ok": True, "skipped": True},
        }
    return {
        "answer": answer.answer.strip(),
        "outcome": "answered",
        "source_ids": answer.source_ids,
        "usages": usages,
        "attempts": state.get("attempts", 0) + 1,
        "validation": {},
    }


async def validate(state: AgentState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    deps = runtime.context
    if state.get("validation", {}).get("skipped"):
        return {}
    shop = deps.shop
    evidence = "\n".join(
        [
            state.get("evidence", ""),
            _user_texts(state),
            shop["support_email"],
            str(shop["support_hours"]),
            str(shop["handoff_sla_hours"]),
        ]
    )
    contacts = {shop["support_email"]} | ({deps.customer_email} if deps.customer_email else set())
    check = check_output(state["answer"], evidence, contacts, deps.canary)
    problems = list(check.problems)
    detected = detect_language(state["answer"]).code
    if len(state["answer"].split()) >= 4 and detected != state["language"]:
        problems.append("wrong_language")
    result = {
        "ok": not problems,
        "problems": problems,
        "unsupported_numbers": check.unsupported_numbers,
        "attempts": state.get("attempts", 0),
    }
    if not problems:
        return {"validation": result}
    feedback = ", ".join(problems)
    if check.unsupported_numbers:
        feedback += f" (numbers not in evidence: {', '.join(check.unsupported_numbers[:5])})"
    if "wrong_language" in problems:
        feedback += f"; the reply must be in {templates.lang_key(state['language'], state.get('dialect'))}"
    return {"validation": result, "feedback": feedback}


async def fallback(state: AgentState, runtime: Runtime[AgentDeps]) -> dict[str, Any]:
    text = template_answer(state, runtime.context)
    if text:
        return {"answer": text, "outcome": "answered", "source_ids": []}
    return {
        "answer": templates.render("unknown", state["language"], state.get("dialect")),
        "outcome": "unknown",
        "source_ids": [],
    }


# --------------------------------------------------------------------------------------- edges ----
def after_guard(state: AgentState) -> str:
    return "refuse" if state["guard"]["action"] == "block" else "route"


def after_plan(state: AgentState) -> str:
    plan = state["plan"]
    return "canned" if plan["intent"] in ("greeting", "out_of_scope") and not plan["tools"] else "execute"


def after_validate(state: AgentState) -> str:
    validation = state.get("validation", {})
    if validation.get("ok", True):
        return END
    return "respond" if state.get("attempts", 0) < 2 else "fallback"


def build_graph():
    graph = StateGraph(AgentState, context_schema=AgentDeps)
    graph.add_node("guard", guard)
    graph.add_node("refuse", refuse)
    graph.add_node("route", route_node)
    graph.add_node("plan", plan_node)
    graph.add_node("canned", canned)
    graph.add_node("execute", execute)
    graph.add_node("respond", respond)
    graph.add_node("validate", validate)
    graph.add_node("fallback", fallback)
    graph.add_edge(START, "guard")
    graph.add_conditional_edges("guard", after_guard, ["refuse", "route"])
    graph.add_edge("refuse", END)
    graph.add_edge("route", "plan")
    graph.add_conditional_edges("plan", after_plan, ["canned", "execute"])
    graph.add_edge("canned", END)
    graph.add_edge("execute", "respond")
    graph.add_edge("respond", "validate")
    graph.add_conditional_edges("validate", after_validate, ["respond", "fallback", END])
    graph.add_edge("fallback", END)
    return graph.compile()


agent_graph = build_graph()
