"""HTTP API: auth, widget sessions, chat, admin console and knowledge-base management."""

import asyncio
import io

import pytest
from docx import Document

from tests.conftest import DEMO_PASSWORD, auth, chat, staff_token, widget_session

pytestmark = pytest.mark.integration


async def test_health(client):
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    ready = (await client.get("/health/ready")).json()
    assert ready["database"] == "ok"


async def test_openapi_is_published(client):
    schema = (await client.get("/openapi.json")).json()
    assert "/api/v1/chat/messages" in schema["paths"]
    assert "/api/v1/admin/documents" in schema["paths"]


# ------------------------------------------------------------------------------------- auth ----
async def test_login_and_me(client):
    token = await staff_token(client)
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    assert me["shop"]["slug"] == "demo-shop" and me["user"]["role"] == "admin"


async def test_wrong_password_and_unknown_user_look_the_same(client):
    a = await client.post("/api/v1/auth/login", json={"email": "admin@brightcart.example.com", "password": "nope"})
    b = await client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": DEMO_PASSWORD})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["message"] == b.json()["error"]["message"]


async def test_admin_endpoints_require_a_staff_token(client):
    assert (await client.get("/api/v1/admin/overview")).status_code == 401
    session = await widget_session(client)
    # A widget session token is not a staff token.
    response = await client.get("/api/v1/admin/overview", headers=auth(session["session_token"]))
    assert response.status_code == 401
    assert (await client.get("/api/v1/admin/overview", headers=auth("not-a-jwt"))).status_code == 401


async def test_login_is_rate_limited(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_login_per_ip", 3)
    codes = []
    for _ in range(5):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "x@example.com", "password": "bad"},
            headers={"x-forwarded-for": "198.51.100.9"},
        )
        codes.append(r.status_code)
    assert 429 in codes
    limited = next(r for r in [r] if r.status_code == 429)
    assert int(limited.headers["retry-after"]) >= 1


# ---------------------------------------------------------------------------------- widget ----
async def test_widget_config_is_public_and_has_no_secrets(client):
    body = (await client.get("/api/v1/widget/config", params={"shop": "demo-shop"})).json()
    assert body["name"] == "Brightcart Electronics"
    assert "widget_secret" not in str(body) and "allowed_origins" not in body


async def test_session_from_unknown_origin_is_refused(client):
    response = await client.post(
        "/api/v1/widget/sessions", json={"shop": "demo-shop"}, headers={"origin": "https://evil.example.net"}
    )
    assert response.status_code == 403


async def test_forged_customer_identity_is_refused(client, casa_shop):
    from app.security.auth import sign_customer_identity

    forged = sign_customer_identity("an-attacker-guessed-this-secret-value-0000", "demo-shop", "BC-C-1001")
    response = await client.post("/api/v1/widget/sessions", json={"shop": "demo-shop", "customer_token": forged})
    assert response.status_code == 401
    # A token correctly signed by another shop is not valid here either.
    other = sign_customer_identity(casa_shop.widget_secret, "casa-lumo", "CL-C-02")
    response = await client.post("/api/v1/widget/sessions", json={"shop": "demo-shop", "customer_token": other})
    assert response.status_code == 401


async def test_chat_roundtrip_and_history(client):
    session = await widget_session(client, customer="BC-C-1001")
    assert session["customer_name"] == "Yasmine Trabelsi"
    reply = (await chat(client, session, "Where is my order BC-10421?")).json()
    assert reply["outcome"] == "answered"
    assert "SDX-4471-2290" in reply["answer"]
    history = (await client.get("/api/v1/chat/messages", headers=auth(session["session_token"]))).json()
    assert [m["role"] for m in history] == ["user", "assistant"]


async def test_chat_message_validation(client):
    session = await widget_session(client)
    assert (await chat(client, session, "")).status_code == 422
    assert (await chat(client, session, "x" * 2001)).status_code == 422
    response = await client.post(
        "/api/v1/chat/messages", json={"message": "hi", "shop_id": "casa-lumo"}, headers=auth(session["session_token"])
    )
    assert response.status_code == 422  # unknown fields are rejected


async def test_chat_is_rate_limited_per_session(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_chat_per_session", 2)
    session = await widget_session(client)
    codes = [(await chat(client, session, "hello")).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


async def test_escalate_button_creates_one_ticket(client):
    session = await widget_session(client, customer="BC-C-1006")
    first = (await client.post("/api/v1/chat/escalate", json={}, headers=auth(session["session_token"]))).json()
    second = (await client.post("/api/v1/chat/escalate", json={}, headers=auth(session["session_token"]))).json()
    assert first["ok"] and first["ticket_number"].startswith("T-")
    assert second["already_escalated"] and second["ticket_number"] == first["ticket_number"]


async def test_human_agent_reply_reaches_the_widget(client):
    session = await widget_session(client)
    await chat(client, session, "I want to talk to a human please")
    token = await staff_token(client, "agent@brightcart.example.com")
    conversations = (
        await client.get("/api/v1/admin/conversations", params={"status": "escalated"}, headers=auth(token))
    ).json()
    conversation_id = session["conversation_id"]
    assert conversation_id in [c["id"] for c in conversations["items"]]
    r = await client.post(
        f"/api/v1/admin/conversations/{conversation_id}/reply",
        json={"content": "Hello, Hedi here. How can I help?"},
        headers=auth(token),
    )
    assert r.status_code == 200
    history = (await client.get("/api/v1/chat/messages", headers=auth(session["session_token"]))).json()
    assert history[-1]["role"] == "human_agent"


# ----------------------------------------------------------------------------------- admin ----
async def test_overview_and_conversation_detail(client):
    session = await widget_session(client, customer="BC-C-1001")
    await chat(client, session, "Is the ORB-X5-256 in stock?")
    token = await staff_token(client)
    overview = (await client.get("/api/v1/admin/overview", headers=auth(token))).json()
    assert overview["conversations"]["total"] >= 1 and overview["replies"]["total"] >= 1
    detail = (await client.get(f"/api/v1/admin/conversations/{session['conversation_id']}", headers=auth(token))).json()
    assert [t["tool"] for t in detail["tool_calls"]] == ["check_stock"]
    assert detail["messages"][1]["flags"]["plan"]["intent"] == "stock"


async def test_viewer_role_cannot_upload(client):
    from app.db import tenant_session
    from app.models import User, UserRole
    from app.security.auth import hash_password
    from tests.conftest import shop_by_slug

    shop = await shop_by_slug("demo-shop")
    async with tenant_session(shop.id) as session:
        session.add(
            User(
                shop_id=shop.id,
                email="viewer@brightcart.example.com",
                full_name="Viewer",
                password_hash=hash_password(DEMO_PASSWORD),
                role=UserRole.VIEWER,
            )
        )
        await session.commit()
    token = await staff_token(client, "viewer@brightcart.example.com")
    files = {"file": ("note.txt", b"Some useful text about deliveries.", "text/plain")}
    assert (await client.post("/api/v1/admin/documents", files=files, headers=auth(token))).status_code == 403


# ------------------------------------------------------------------------------- knowledge ----
async def _wait_ready(client, token, doc_id, seconds=120):
    for _ in range(seconds * 2):
        docs = (await client.get("/api/v1/admin/documents", headers=auth(token))).json()
        doc = next(d for d in docs if d["id"] == doc_id)
        if doc["status"] in ("ready", "failed"):
            return doc
        await asyncio.sleep(0.5)
    raise AssertionError("document was not processed in time")


async def test_upload_process_search_and_delete_document(client):
    token = await staff_token(client)
    document = Document()
    document.add_heading("Gift wrapping", level=1)
    document.add_paragraph("Gift wrapping is available for 5.000 TND per order. Choose it at checkout.")
    buffer = io.BytesIO()
    document.save(buffer)
    files = {
        "file": (
            "gift-wrapping.docx",
            buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    created = await client.post("/api/v1/admin/documents", files=files, headers=auth(token))
    assert created.status_code == 202 and created.json()["status"] == "pending"
    doc = await _wait_ready(client, token, created.json()["id"])
    assert doc["status"] == "ready" and doc["chunk_count"] >= 1 and doc["title"] == "Gift wrapping"

    duplicate = await client.post("/api/v1/admin/documents", files=files, headers=auth(token))
    assert duplicate.status_code == 409

    found = (
        await client.post("/api/v1/admin/search", json={"query": "Do you offer gift wrapping?"}, headers=auth(token))
    ).json()
    assert found["chunks"][0]["title"] == "Gift wrapping"

    assert (await client.delete(f"/api/v1/admin/documents/{doc['id']}", headers=auth(token))).status_code == 204
    found = (
        await client.post("/api/v1/admin/search", json={"query": "Do you offer gift wrapping?"}, headers=auth(token))
    ).json()
    assert all(c["title"] != "Gift wrapping" for c in found["chunks"])


async def test_upload_rejects_bad_files(client):
    token = await staff_token(client)
    fake_pdf = {"file": ("report.pdf", b"MZ\x90\x00not really a pdf", "application/pdf")}
    assert (await client.post("/api/v1/admin/documents", files=fake_pdf, headers=auth(token))).status_code == 415
    exe = {"file": ("tool.exe", b"MZ\x90\x00", "application/octet-stream")}
    assert (await client.post("/api/v1/admin/documents", files=exe, headers=auth(token))).status_code == 415


async def test_unreadable_document_is_marked_failed(client):
    token = await staff_token(client)
    files = {"file": ("empty.md", b"#\n\n   \n", "text/markdown")}
    created = await client.post("/api/v1/admin/documents", files=files, headers=auth(token))
    doc = await _wait_ready(client, token, created.json()["id"])
    assert doc["status"] == "failed" and doc["error"]
