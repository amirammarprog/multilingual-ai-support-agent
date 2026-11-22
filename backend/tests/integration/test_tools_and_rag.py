"""Every tool against the real database, the retrieval pipeline, and the agent graph (rule-based and
with a scripted model)."""

import pytest
from sqlalchemy import select

from app.db import tenant_session
from app.models import Conversation, Customer, ToolCall, ToolCallStatus
from app.rag.retrieval import retrieve
from app.tools.business import registry
from app.tools.registry import STAFF_SCOPES, WIDGET_SCOPES, ToolContext
from tests.helpers import ScriptedLLM, plan, random_email, run_turns

pytestmark = pytest.mark.integration


async def _ctx(shop, customer_ref=None, language="en", scopes=WIDGET_SCOPES, with_conversation=True):
    async with tenant_session(shop.id) as session:
        customer = None
        if customer_ref:
            customer = await session.scalar(select(Customer).where(Customer.external_ref == customer_ref))
        conversation_id = None
        if with_conversation:
            conversation = Conversation(shop_id=shop.id, customer_id=customer.id if customer else None)
            session.add(conversation)
            await session.commit()
            conversation_id = conversation.id
    return ToolContext(
        shop_id=shop.id,
        actor="widget",
        scopes=scopes,
        customer_id=customer.id if customer else None,
        conversation_id=conversation_id,
        language=language,
    )


async def call(shop, name, args, ctx):
    async with tenant_session(shop.id) as session:
        result = await registry.execute(session, name, args, ctx)
        await session.commit()
    return result


# ---------------------------------------------------------------------------------- catalogue ----
@pytest.mark.parametrize(
    ("query", "language", "expected_sku"),
    [
        ("noise cancelling headphones", "en", "TES-ANC-700"),
        ("casque sans fil", "fr", "TES-ANC-700"),
        ("سماعات رأس لاسلكية", "ar", "TES-ANC-700"),
        ("Calyra Book 14", "en", "CAL-BOOK-14"),
        ("montre connectée GPS", "fr", "VAN-WATCH-S"),
    ],
)
async def test_search_products_is_multilingual(demo_shop, query, language, expected_sku):
    ctx = await _ctx(demo_shop, language=language, with_conversation=False)
    result = await call(demo_shop, "search_products", {"query": query}, ctx)
    assert result.ok
    assert expected_sku in [p["sku"] for p in result.data["results"]][:3]


async def test_search_products_filters_and_unrelated_queries(demo_shop):
    ctx = await _ctx(demo_shop, with_conversation=False)
    cheap = await call(demo_shop, "search_products", {"query": "headphones", "max_price": 200}, ctx)
    assert all(float(p["price"]) <= 200 for p in cheap.data["results"])
    nothing = await call(demo_shop, "search_products", {"query": "fresh tomatoes and olive oil"}, ctx)
    assert nothing.ok and nothing.data["results"] == []


async def test_product_details_and_stock(demo_shop):
    ctx = await _ctx(demo_shop, language="fr", with_conversation=False)
    details = await call(demo_shop, "get_product_details", {"sku": "orb-x5-128"}, ctx)
    assert details.ok and details.data["price"] == "1299.000" and details.data["warranty_months"] == 24
    assert details.data["name"] == "Smartphone Orbix X5 128 Go"

    out = await call(demo_shop, "check_stock", {"sku": "ORB-X5-256"}, ctx)
    assert out.data["stock_status"] == "out_of_stock" and out.data["restock_date"] == "2026-12-10"
    unknown_date = await call(demo_shop, "check_stock", {"sku": "TES-BUDS-2"}, ctx)
    assert unknown_date.data["restock_date"] is None
    low = await call(demo_shop, "check_stock", {"sku": "ORB-LITE-64", "quantity": 5}, ctx)
    assert low.data["stock_status"] == "low_stock" and low.data["quantity_available"] == 3
    assert low.data["requested_quantity_available"] is False

    missing = await call(demo_shop, "get_product_details", {"sku": "NOPE-000"}, ctx)
    assert missing.status == ToolCallStatus.NOT_FOUND


async def test_other_shops_products_are_invisible(demo_shop):
    ctx = await _ctx(demo_shop, with_conversation=False)
    result = await call(demo_shop, "get_product_details", {"sku": "LUMO-AIRF-5"}, ctx)
    assert result.status == ToolCallStatus.NOT_FOUND


# -------------------------------------------------------------------------------------- orders ----
async def test_signed_in_customer_sees_only_own_orders(demo_shop):
    ctx = await _ctx(demo_shop, "BC-C-1001")
    own = await call(demo_shop, "get_order_status", {"order_number": "BC-10421"}, ctx)
    assert own.ok and own.data["estimated_delivery_date"] == "2026-11-24"
    assert "shipping_address" not in own.data and "email" not in str(own.data)

    other = await call(demo_shop, "get_order_status", {"order_number": "BC-10435"}, ctx)
    nonexistent = await call(demo_shop, "get_order_status", {"order_number": "BC-99999"}, ctx)
    # Not yours and does not exist are indistinguishable.
    assert other.status == nonexistent.status == ToolCallStatus.NOT_FOUND
    assert other.error_code == nonexistent.error_code


async def test_guest_must_verify_with_order_email(demo_shop):
    ctx = await _ctx(demo_shop)
    needs = await call(demo_shop, "get_order_status", {"order_number": "BC-10435"}, ctx)
    assert needs.status == ToolCallStatus.DENIED and needs.error_code == "verification_required"
    wrong = await call(demo_shop, "get_order_status", {"order_number": "BC-10435", "email": random_email()}, ctx)
    assert wrong.error_code == "verification_failed"
    right = await call(
        demo_shop, "get_order_status", {"order_number": "BC-10435", "email": "KARIM.HADDAD@example.net"}, ctx
    )
    assert right.ok and right.data["status"] == "processing" and right.data["estimated_delivery_date"] is None
    # Verified for the rest of the conversation, stored server side.
    again = await call(demo_shop, "get_order_status", {"order_number": "BC-10435"}, ctx)
    assert again.ok
    async with tenant_session(demo_shop.id) as session:
        conversation = await session.get(Conversation, ctx.conversation_id)
        assert conversation.verified_orders == ["BC-10435"]


async def test_guest_is_locked_out_after_repeated_failures(demo_shop, settings):
    ctx = await _ctx(demo_shop)
    for _ in range(settings.order_verification_max_failures):
        r = await call(demo_shop, "get_order_status", {"order_number": "BC-10440", "email": random_email()}, ctx)
        assert r.error_code == "verification_failed"
    locked = await call(
        demo_shop, "get_order_status", {"order_number": "BC-10440", "email": "claire.martin@example.org"}, ctx
    )
    assert locked.error_code == "verification_locked"


async def test_staff_scope_can_read_any_order(demo_shop):
    ctx = await _ctx(demo_shop, scopes=STAFF_SCOPES, with_conversation=False)
    result = await call(demo_shop, "get_order_status", {"order_number": "BC-10452"}, ctx)
    assert result.ok and result.data["estimated_delivery_date"] is None


# ------------------------------------------------------------------------------------- tickets ----
async def test_ticket_needs_contact_and_is_limited(demo_shop):
    guest = await _ctx(demo_shop)
    args = {"subject": "Broken screen", "description": "My watch screen arrived cracked.", "category": "warranty"}
    no_contact = await call(demo_shop, "create_support_ticket", args, guest)
    assert no_contact.error_code == "contact_email_required"
    results = [
        await call(demo_shop, "create_support_ticket", args | {"contact_email": random_email()}, guest)
        for _ in range(4)
    ]
    assert [r.ok for r in results] == [True, True, True, False]
    assert results[-1].error_code == "ticket_limit_reached"

    customer = await _ctx(demo_shop, "BC-C-1003")
    linked = await call(demo_shop, "create_support_ticket", args | {"order_number": "BC-10440"}, customer)
    assert linked.ok and linked.data["linked_order"] == "BC-10440"
    not_linked = await call(demo_shop, "create_support_ticket", args | {"order_number": "BC-10421"}, customer)
    assert not_linked.ok and not_linked.data["linked_order"] is None  # someone else's order is never attached


async def test_escalation_marks_conversation(demo_shop):
    ctx = await _ctx(demo_shop, "BC-C-1004", language="ar")
    result = await call(demo_shop, "escalate_to_human", {"reason": "Customer is upset", "urgency": "high"}, ctx)
    assert result.ok and result.data["reply_within_hours"] == 4
    assert result.data["support_hours"].startswith("من الإثنين")
    async with tenant_session(demo_shop.id) as session:
        assert (await session.get(Conversation, ctx.conversation_id)).status.value == "escalated"


async def test_every_call_is_audited(demo_shop):
    ctx = await _ctx(demo_shop)
    await call(demo_shop, "check_stock", {"sku": "ZEL-PEN"}, ctx)
    await call(demo_shop, "get_order_status", {"order_number": "BC-10421", "email": "a@b.co"}, ctx)
    async with tenant_session(demo_shop.id) as session:
        rows = (
            await session.scalars(
                select(ToolCall).where(ToolCall.conversation_id == ctx.conversation_id).order_by(ToolCall.created_at)
            )
        ).all()
    assert [(r.tool_name, r.status.value) for r in rows] == [("check_stock", "success"), ("get_order_status", "denied")]
    assert rows[1].arguments["email"] == "[redacted]"


# --------------------------------------------------------------------------------- retrieval ----
@pytest.mark.parametrize(
    ("query", "language", "expected_title_part"),
    [
        ("How much does express delivery cost?", "en", "Shipping"),
        ("Quel est le délai pour retourner un produit ?", "fr", "retours"),
        ("كم مدة الضمان على الهواتف؟", "ar", "الأسئلة الشائعة"),
        ("Is liquid damage covered by the warranty?", "en", "Warranty"),
        ("Est-ce que vous acceptez plusieurs codes promo ?", "fr", "questions fréquentes"),
        ("How do I pair the Tessio ANC 700 with two phones?", "en", "Setup"),
    ],
)
async def test_hybrid_retrieval_finds_the_right_document(demo_shop, query, language, expected_title_part):
    async with tenant_session(demo_shop.id) as session:
        result = await retrieve(session, demo_shop.id, query, language)
    assert result.answerable, result.as_dict()
    top_titles = [c.title.lower() for c in result.chunks[:2]]
    assert any(expected_title_part.lower() in t for t in top_titles), top_titles


async def test_unrelated_question_is_not_answerable(demo_shop):
    async with tenant_session(demo_shop.id) as session:
        result = await retrieve(session, demo_shop.id, "What is the capital of Australia?", "en")
    assert not result.answerable


async def test_retrieval_never_crosses_shops(casa_shop):
    async with tenant_session(casa_shop.id) as session:
        result = await retrieve(session, casa_shop.id, "Tessio headphones return policy 15 days", "en")
    assert all("Casa Lumo" in c.title for c in result.chunks)


# ------------------------------------------------------------------------- agent: rule-based ----
async def test_agent_answers_in_the_customers_language_without_a_model():
    replies = await run_turns("demo-shop", ["Est-ce que le ORB-X5-256 est en stock ?", "كم سعر TES-ANC-700؟"])
    assert replies[0].language == "fr" and "rupture" in replies[0].answer and "10 décembre 2026" in replies[0].answer
    assert replies[1].language == "ar" and "389.000" in replies[1].answer


async def test_agent_follow_up_uses_conversation_memory():
    replies = await run_turns(
        "demo-shop", ["Where is my order BC-10421?", "and when will the order arrive?"], customer_ref="BC-C-1001"
    )
    assert "24 November 2026" in replies[1].answer


async def test_offer_of_a_human_can_be_accepted():
    replies = await run_turns("demo-shop", ["What will the weather be in Tokyo tomorrow?", "yes"])
    assert replies[0].outcome == "unknown"
    assert replies[1].outcome == "escalated" and "T-" in replies[1].answer


# ------------------------------------------------------------------------ agent: model path ----
async def test_llm_answer_with_invented_number_is_replaced_by_tool_data():
    llm = ScriptedLLM(
        plans=[plan(intent="product_info", tools=["get_product_details"], sku="ORB-X5-128")],
        answers=[
            {"answer": "The Orbix X5 costs 999 TND today only.", "source_ids": ["T1"], "answered": True},
            {"answer": "It costs 1099 TND.", "source_ids": ["T1"], "answered": True},
        ],
    )
    [reply] = await run_turns("demo-shop", ["How much is the Orbix X5 128?"], llm=llm)
    assert "999" not in reply.answer and "1099" not in reply.answer
    assert "1299.000" in reply.answer
    assert reply.debug["validation"]["problems"] == ["unsupported_numbers"]
    # The second attempt got the validator's feedback.
    assert "numbers not in evidence" in llm.prompts[-1][-1]["content"]


async def test_llm_grounded_answer_is_kept_with_citations():
    llm = ScriptedLLM(
        plans=[plan(intent="policy", knowledge_query="return window for products")],
        answers=[
            {
                "answer": "You can return a product within 15 days of delivery if it is unused.",
                "source_ids": ["S1"],
                "answered": True,
            }
        ],
    )
    [reply] = await run_turns("demo-shop", ["How long do I have to return something?"], llm=llm)
    assert reply.outcome == "answered" and reply.answer.startswith("You can return")
    assert reply.sources and reply.sources[0]["id"] == "S1"


async def test_llm_that_says_it_does_not_know_triggers_the_human_offer():
    llm = ScriptedLLM(
        plans=[plan(intent="policy", knowledge_query="do you deliver to Algeria")],
        answers=[{"answer": "", "source_ids": [], "answered": False}],
    )
    [reply] = await run_turns("demo-shop", ["Do you deliver to Algeria?"], llm=llm)
    assert reply.outcome == "unknown" and "team" in reply.answer
