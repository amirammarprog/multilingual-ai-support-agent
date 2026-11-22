"""Langfuse tracing: a real chat turn is exported by the real Langfuse SDK (OpenTelemetry over HTTP) to a
local receiver standing in for the Langfuse server. Checks span names, authentication and redaction."""

import asyncio
import base64
import gzip
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import SecretStr

import app.agent.graph
import app.agent.service
import app.llm.client
import app.observability
from tests.helpers import run_turns

pytestmark = pytest.mark.integration


@pytest.fixture
def receiver():
    received: list[tuple[str, bytes, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("content-length", 0)))
            if self.headers.get("content-encoding") == "gzip":
                body = gzip.decompress(body)
            received.append((self.path, body, self.headers.get("authorization")))
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, received
    server.shutdown()


async def test_chat_turn_is_traced_to_langfuse_with_redaction(receiver, settings, monkeypatch):
    server, received = receiver
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-lf-test")
    monkeypatch.setattr(settings, "langfuse_secret_key", SecretStr("sk-lf-test"))
    monkeypatch.setattr(settings, "langfuse_host", f"http://127.0.0.1:{server.server_port}")
    tracer = app.observability.Tracer()
    for module in (app.observability, app.agent.graph, app.agent.service, app.llm.client):
        monkeypatch.setattr(module, "tracer", tracer)
    assert tracer.enabled

    await run_turns("demo-shop", ["Is the ORB-X5-256 in stock? My e-mail is karim.haddad@example.net"])
    tracer.flush()
    for _ in range(40):
        if received:
            break
        await asyncio.sleep(0.25)
    tracer.client.shutdown()  # stop the exporter before the receiver goes away

    assert received, "no trace was exported"
    paths = {path for path, _, _ in received}
    assert any(path.endswith("/api/public/otel/v1/traces") for path in paths), paths
    expected_auth = "Basic " + base64.b64encode(b"pk-lf-test:sk-lf-test").decode()
    assert all(auth == expected_auth for _, _, auth in received)
    payload = b"".join(body for _, body, _ in received)
    for span in (b"chat_turn", b"check_stock"):
        assert span in payload, span
    assert b"karim.haddad@example.net" not in payload  # inputs and outputs are redacted before export
