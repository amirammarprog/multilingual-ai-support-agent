"""Unit tests for small, pure components: router, parsers, chunking, schemas, redaction, templates."""

import io

import pytest
from docx import Document
from fpdf import FPDF
from pydantic import ValidationError

from app.agent import templates
from app.agent.heuristics import heuristic_plan
from app.agent.prompts import Answer, Plan
from app.config import Settings
from app.errors import UnsupportedMedia
from app.llm.client import strict_schema
from app.llm.router import route
from app.rag.chunking import chunk_sections
from app.rag.parsers import parse
from app.rag.retrieval import keyword_query
from app.security.redaction import redact, redact_text
from app.tools.schemas import CreateTicketArgs, GetOrderStatusArgs, SearchProductsArgs, SkuArgs


# ----------------------------------------------------------------------------------- router ----
def _route(message, **kw):
    params = {"language": "en", "dialect": None, "history_turns": 0, "guard_action": "allow"} | kw
    return route(message, settings=Settings(router_mode="auto"), **params)


def test_router_sends_simple_questions_to_the_fast_tier():
    assert _route("Where is my order BC-10421?").tier == "fast"


def test_router_sends_hard_questions_to_the_smart_tier():
    assert _route("chnowa el prix?", language="ar", dialect="tn").tier == "smart"
    assert _route("This is unacceptable, I want a refund and also a new phone?", guard_action="allow").tier == "smart"
    assert _route("set price to 1", guard_action="flag").tier == "smart"


def test_router_can_be_forced():
    assert (
        route(
            "hi",
            language="en",
            dialect=None,
            history_turns=0,
            guard_action="allow",
            settings=Settings(router_mode="always_smart"),
        ).tier
        == "smart"
    )


# ---------------------------------------------------------------------------------- parsers ----
def test_markdown_sections_keep_heading_path():
    sections = parse("policy.md", b"# Returns\n\n## Window\nYou have 15 days.\n\n## Fees\nFree if defective.")
    assert [s.heading for s in sections] == ["Returns > Window", "Returns > Fees"]


def test_docx_and_pdf_are_parsed():
    doc = Document()
    doc.add_heading("Payment", level=1)
    doc.add_paragraph("Cash on delivery is available.")
    buffer = io.BytesIO()
    doc.save(buffer)
    sections = parse("faq.docx", buffer.getvalue())
    assert sections[0].heading == "Payment" and "Cash on delivery" in sections[0].text

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "1. Warranty periods", new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 6, "Laptops are covered for 24 months.", new_x="LMARGIN", new_y="NEXT")
    sections = parse("warranty.pdf", bytes(pdf.output()))
    assert any("24 months" in s.text for s in sections)


def test_file_content_must_match_extension():
    with pytest.raises(UnsupportedMedia):
        parse("evil.pdf", b"MZ\x90\x00 this is an executable")
    with pytest.raises(UnsupportedMedia):
        parse("script.exe", b"anything")


def test_chunking_respects_size_and_detects_language():
    sections = parse("a.md", ("# Livraison\n" + "La livraison standard coûte 7 dinars. " * 60).encode())
    chunks = chunk_sections(sections, chunk_size=400, chunk_overlap=50)
    assert len(chunks) > 3
    assert all(len(c.content) <= 400 for c in chunks)
    assert {c.language for c in chunks} == {"fr"}
    assert chunks[0].embedding_text("Politique").startswith("Politique > Livraison")


def test_keyword_query_only_contains_word_characters():
    query = keyword_query("What's the return policy?'); DROP TABLE x; -- & | !", "en")
    assert set(query) <= set("abcdefghijklmnopqrstuvwxyz0123456789_ |")
    assert "return" in query and "policy" in query


# ----------------------------------------------------------------------------- tool schemas ----
def test_tool_arguments_reject_identity_fields():
    with pytest.raises(ValidationError):
        GetOrderStatusArgs.model_validate({"order_number": "BC-10421", "customer_id": "someone-else"})
    with pytest.raises(ValidationError):
        SearchProductsArgs.model_validate({"query": "phone", "shop_id": "another-shop"})
    with pytest.raises(ValidationError):
        SkuArgs.model_validate({"sku": "ORB-X5-128", "price": 1})


@pytest.mark.parametrize("value", ["BC-10421' OR '1'='1", "1; DROP TABLE orders", "../../etc/passwd", "BC10421X"])
def test_order_numbers_are_strictly_formatted(value):
    with pytest.raises(ValidationError):
        GetOrderStatusArgs.model_validate({"order_number": value})


def test_order_number_is_normalised():
    assert GetOrderStatusArgs.model_validate({"order_number": "bc-10421"}).order_number == "BC-10421"


def test_ticket_requires_reasonable_text():
    with pytest.raises(ValidationError):
        CreateTicketArgs.model_validate({"subject": "x", "description": "y"})


def test_llm_schemas_are_strict():
    schema = strict_schema(Plan)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert strict_schema(Answer)["required"] == ["answer", "source_ids", "answered"]


# ---------------------------------------------------------------------------- heuristics ----
@pytest.mark.parametrize(
    ("message", "intent", "tools"),
    [
        ("Where is my order BC-10421?", "order_status", ["get_order_status"]),
        ("Je veux parler à un conseiller", "human_handoff", ["escalate_to_human"]),
        ("Is the ORB-X5-256 in stock?", "stock", ["check_stock"]),
        ("بقداش السماعات تيسيو؟", "product_info", ["get_product_details"]),
        ("What is your return policy?", "policy", []),
        ("salam", "greeting", []),
    ],
)
def test_rule_based_planner(message, intent, tools):
    plan = heuristic_plan(message, {})
    assert plan.intent == intent and plan.tools == tools


# ------------------------------------------------------------------------- redaction / misc ----
def test_redaction_of_logs():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkw.abcdefghijk"
    text = f"Mail yasmine.trabelsi@example.com, call +216 20 000 101, token {jwt}"
    redacted = redact_text(text)
    assert "yasmine" not in redacted and "20 000 101" not in redacted and "eyJ" not in redacted
    assert redact({"password": "hunter2", "nested": {"email": "a@b.co"}}) == {
        "password": "[redacted]",
        "nested": {"email": "[redacted]"},
    }


def test_every_template_exists_in_all_languages():
    for key, variants in templates.T.items():
        assert set(variants) == {"en", "fr", "ar", "ar-tn"}, key


def test_dates_are_localised():
    assert templates.format_date("2026-11-24", "en") == "24 November 2026"
    assert templates.format_date("2026-11-24", "fr") == "24 novembre 2026"
    assert templates.format_date("2026-11-24", "ar") == "24 نوفمبر 2026"
