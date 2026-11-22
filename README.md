# Multilingual AI Support Agent

[![CI](https://github.com/amirammarprog/multilingual-ai-support-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/amirammarprog/multilingual-ai-support-agent/actions/workflows/ci.yml)
[![Evaluation](https://github.com/amirammarprog/multilingual-ai-support-agent/actions/workflows/evals.yml/badge.svg)](https://github.com/amirammarprog/multilingual-ai-support-agent/actions/workflows/evals.yml)

A 24/7 customer-support agent for e-commerce shops that speaks **Arabic, Tunisian Arabic (Arabic script
and "Arabizi"), French and English**, by text and voice. It answers from the shop's own documents and live
data, and when it does not know, it says so and offers a human.

> All shops, products, customers, orders and documents in this repository are **fictional**.

**Stack:** React 19 · TypeScript · Vite · Tailwind · Python 3.14 · FastAPI · PostgreSQL 18 + pgvector ·
SQLAlchemy 2.1 · Alembic · LangGraph · Pydantic · pytest · Docker · GitHub Actions · Langfuse · MCP.

## Screenshots

All screenshots are of the running app (`frontend/scripts/screenshots.mjs` takes them from a live stack).
This deployment has **no LLM configured**, so replies come from the rule-based planner and answer
templates built from tool data and quoted documents (see [Modes](#modes-with-and-without-an-llm)).

| Customer chat (orders, stock, Tunisian Arabizi) | Arabic interface, right-to-left, dark mode |
| --- | --- |
| ![Chat](docs/screenshots/chat.png) | ![Arabic chat](docs/screenshots/chat-arabic-dark.png) |

| Admin dashboard | Conversation monitoring (tool calls, planner, router, retrieval) |
| --- | --- |
| ![Dashboard](docs/screenshots/admin-dashboard.png) | ![Conversation](docs/screenshots/admin-conversation.png) |

| Knowledge base + retrieval tester | Evaluation dashboard |
| --- | --- |
| ![Knowledge base](docs/screenshots/admin-knowledge.png) | ![Evaluations](docs/screenshots/admin-evaluations.png) |

| Landing page | Embeddable widget on a phone |
| --- | --- |
| ![Landing](docs/screenshots/landing.png) | <img src="docs/screenshots/widget-mobile.png" width="260" alt="Widget"> |

## What it does

- **Multilingual chat.** Detects English, French, Modern Standard Arabic and Tunisian Arabic (including
  Latin-script Arabizi such as `chnowa el prix mta3…`) and replies in the customer's language. Short
  messages ("ok", "merci") keep the conversation language. Follow-ups ("and when will it arrive?") use
  server-side conversation memory.
- **Grounded answers (RAG).** PDF, DOCX, TXT and Markdown ingestion; heading-aware chunking; local
  multilingual embeddings; hybrid **pgvector + PostgreSQL full-text** search fused with weighted reciprocal
  rank fusion; a **multilingual cross-encoder reranker**; citations; a confidence threshold below which the
  agent says it does not know and offers a human. For cross-lingual questions (an English question about a
  French policy) the planner writes the query in English, French and Arabic, and each candidate chunk is
  reranked against the version in its own language.
- **Real tools on real data.** `search_products`, `get_product_details`, `check_stock`, `get_order_status`,
  `create_support_ticket`, `escalate_to_human`, `search_knowledge_base`, all against PostgreSQL, behind one
  registry that the agent uses **and** that is served over **MCP** at `/mcp`.
- **Never invents facts.** Order numbers, SKUs and e-mails proposed by the model are kept only if the
  customer actually wrote them. Every number in a drafted answer must appear in the evidence it was built
  from; a draft that fails twice is replaced by an answer built only from tool data, or by "I don't know"
  with a hand-off offer. Delivery dates and restock dates are shown only when the database has them.
- **Human hand-off.** Escalations create a ticket, flag the conversation, and the team's replies (typed in
  the admin console) appear in the customer's chat and widget.
- **Voice.** Speech-to-text with local Whisper (free, CPU) or OpenAI; text-to-speech with the browser's own
  voices (free) or OpenAI. Providers are swappable by configuration.
- **Embeddable widget.** One tag, 17 KB, shadow DOM, mobile full-screen, language switch, voice, typing
  indicator, history, product cards, hand-off button.
- **Model router.** Cheap model for simple turns, capable model for hard ones (Tunisian dialect, several
  questions, upset customer, suspicious request, context-dependent follow-up), with a provider fallback
  chain and per-call tokens, latency and cost recorded.
- **Admin console.** Dashboard (conversations, resolved, escalated, answer rate, response times, model
  usage, cost, latest evaluation), conversation monitoring, knowledge-base management, evaluation history.

## Architecture

```mermaid
flowchart LR
  subgraph Browser
    W["widget.js (shadow DOM)"]
    A["React app: chat + admin"]
  end
  W -- "/api" --> N[nginx]
  A -- "/api" --> N
  N --> API[FastAPI]
  M[MCP clients] -- "/mcp (bearer)" --> API
  API --> G[LangGraph agent]
  G --> GR["Guardrails: injection, output checks"]
  G --> RT["Model router"]
  RT --> P1[("LLM provider 1")]
  RT -. fallback .-> P2[("LLM provider 2")]
  G --> T["Tool registry: scopes, schemas, ownership, audit"]
  G --> RAG["Hybrid retrieval: pgvector + full-text -> reranker"]
  T --> DB[("PostgreSQL 18 + pgvector, row-level security")]
  RAG --> DB
  API --> V["Voice: Whisper / OpenAI, browser TTS"]
  API -. traces .-> LF[Langfuse]
```

One customer message goes through this LangGraph state machine
([`backend/app/agent/graph.py`](backend/app/agent/graph.py)):

```mermaid
flowchart TD
  S([message]) --> guard["guard: normalise, detect language, scan for injection"]
  guard -- blocked --> refuse[refusal template] --> E([reply])
  guard --> route["route: fast or capable model"]
  route --> plan["plan: intent, tools, identifiers, translated search queries"]
  plan -- "greeting / out of scope" --> canned[template] --> E
  plan --> execute["execute: permission-checked tools + hybrid retrieval"]
  execute --> respond["respond: answer only from evidence, with citations"]
  respond --> validate["validate: numbers, contact data, false promises, prompt leaks, language"]
  validate -- ok --> E
  validate -- "problems, 1st time" --> respond
  validate -- "problems, 2nd time" --> fallback["fallback: answer from tool data, or I don't know + human"] --> E
```

Identity checks, hand-offs, tickets and "I don't know" are deterministic templates in the four languages
([`templates.py`](backend/app/agent/templates.py)), so the model never improvises them.

### Repository layout

```
backend/
  app/agent/       LangGraph graph, prompts, rule-based planner, templates, chat service
  app/rag/         parsers, chunking, embeddings, reranker, hybrid retrieval, ingestion
  app/tools/       tool schemas, registry (authorisation + audit), shop tools, MCP server
  app/security/    auth (staff, widget, shop-signed identity), guardrails, rate limits, redaction
  app/llm/         OpenAI-compatible client with fallback and costs, complexity router
  app/voice/       STT / TTS providers
  app/api/         HTTP routes (chat, widget, voice, admin, evaluations)
  migrations/      Alembic (schema, row-level security, grants)
  knowledge/       fictional policy documents (MD, TXT, PDF, DOCX)
  evals/           dataset (130 cases), metrics, LLM judge, runner, reports
  tests/           unit, integration, security (adversarial)
frontend/
  src/             React app (landing, chat, admin)
  widget/          embeddable widget (vanilla TypeScript)
```

## Quick start (Docker)

Requirements: Docker with Compose. About 2 GB of RAM for the stack; the first start downloads the local
embedding and reranker models (about 340 MB).

```bash
cp .env.example .env
# set JWT_SECRET to a long random string, e.g.:
python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up -d --build
```

- App and admin console: http://localhost:8080 (admin at `/admin`)
- Fictional shop page with the embedded widget: http://localhost:8080/demo-store.html
- API docs (OpenAPI): http://localhost:8000/docs (set `API_PORT` if 8000 is taken)

The `migrate` service creates the application database role, runs the migrations and seeds two fictional
shops (Brightcart Electronics, Casa Lumo Home) with products, customers, orders and documents.

Demo staff accounts (fictional shops only; password `demo-password-2026`, or `SEED_STAFF_PASSWORD`):

| E-mail | Shop | Role |
| --- | --- | --- |
| admin@brightcart.example.com | Brightcart Electronics | admin |
| agent@brightcart.example.com | Brightcart Electronics | agent |
| admin@casalumo.example.net | Casa Lumo Home | admin |

In the chat demo you can act as a guest or as one of the fictional customers (for example Yasmine
Trabelsi, who owns orders BC-10421 and BC-10422).

### Modes: with and without an LLM

| Mode | Configuration | Cost |
| --- | --- | --- |
| **No LLM** (degraded mode) | nothing | free |
| **Local LLM** | `docker compose --profile local-llm up -d` (llama.cpp + Qwen3-1.7B, 1.3 GB download), then `LLM_PRIMARY_BASE_URL=http://llm:8080/v1`, `LLM_PRIMARY_FAST_MODEL=qwen3-1.7b`, `LLM_PRIMARY_SMART_MODEL=qwen3-1.7b`, `LLM_DISABLE_THINKING=true` | free, needs a decent CPU/GPU |
| **OpenAI** (or any OpenAI-compatible API) | `LLM_PRIMARY_API_KEY=...` | paid, see below |

Without an LLM the agent still works: the rule-based planner calls the same tools with the same permission
checks, answers about orders, stock and products come from tool data, and policy questions get the most
relevant document section quoted. With an LLM, the planner understands free-form questions, translates
search queries for cross-lingual retrieval, and writes answers that are then validated.

**Costs (OpenAI, paid).** The defaults are `gpt-4.1-nano` (fast tier) and `gpt-4.1-mini` (smart tier),
priced in [`config.py`](backend/app/config.py) at USD 0.10/0.40 and 0.40/1.60 per million input/output
tokens; check current prices before use. A turn uses two model calls of roughly 1,000 to 2,500 tokens
each, which is roughly USD 0.0003 (nano) to 0.0015 (mini) per message. A full evaluation run (130 cases,
agent + judge) is in the order of USD 0.30 to 1.00. `EMBEDDING_PROVIDER=openai`, `STT_PROVIDER=openai` and
`TTS_PROVIDER=openai` are also paid and optional; the defaults are local and free.

### Observability (Langfuse)

Tracing is on when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set: each turn is a trace with the
planner and responder generations (model, tokens, cost), tool calls and retrieval. Inputs and outputs go
through the same PII redaction as the logs. Use Langfuse Cloud or the self-hosted stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d   # UI on http://localhost:3000
```

What has been verified: an integration test
([`test_observability.py`](backend/tests/integration/test_observability.py)) runs a real chat turn with the
real Langfuse SDK and checks what reaches the Langfuse OTLP endpoint (span names, credentials, redaction of
the customer's e-mail). The self-hosted compose file itself could not be started on the development machine
(the Docker Hub downloads kept failing), so it is provided but not yet verified end to end.

Independently of Langfuse, every model call is stored in `llm_calls` (provider, model, tier, tokens, cost,
latency, fallback), which feeds the dashboard.

## Development

Everything runs in containers, so no local Python or Node install is needed.

```bash
docker compose up -d db
docker compose --profile dev run --rm dev pytest              # 181 tests: unit, integration, security
docker compose --profile dev run --rm dev ruff check .
docker compose --profile dev run --rm dev python scripts/chat_cli.py "Où est ma commande BC-10421 ?" --customer BC-C-1001 --debug
cd frontend && npm ci && npm run dev                           # http://localhost:5173, proxies /api to :8000
```

The test suite rebuilds its database from the migrations and refuses to run against a database whose name
does not end with `_test`. Integration tests use the real local embedding and reranker models.

## Embedding the widget

```html
<script src="https://support.example.com/widget.js" data-shop-id="demo-shop" defer></script>
```

Optional attributes: `data-language` (`en`/`fr`/`ar`), `data-position` (`left`/`right`),
`data-api-base`, and `data-customer-token`. The widget only works on origins listed in the shop's
`allowed_origins`.

**Signed-in customers.** To let the agent show a customer's own orders, the shop's backend signs a
short-lived token with the shop's widget secret (HS256, audience `support-agent:identity`, `sub` = the
shop's customer reference) and puts it in `data-customer-token`. The API verifies it and exchanges it for a
chat session. Guests can still look up an order with its number **and** the e-mail used for it; after five
failed attempts the conversation is locked for order lookups.

## API

Interactive docs at `/docs`. Main endpoints:

| Method and path | Who | Purpose |
| --- | --- | --- |
| `GET /api/v1/widget/config?shop=` | public | shop name, languages, theme, voice options |
| `POST /api/v1/widget/sessions` | public (origin-checked) | start a chat, optionally with a customer identity token |
| `POST /api/v1/chat/messages` | widget session | send a message, get answer + sources + products |
| `GET /api/v1/chat/messages` | widget session | history, including human-agent replies |
| `POST /api/v1/chat/escalate` | widget session | "talk to a person" |
| `POST /api/v1/voice/transcribe`, `POST /api/v1/voice/speak` | widget session | speech-to-text, text-to-speech |
| `POST /api/v1/auth/login` | staff | admin console sign-in |
| `GET /api/v1/admin/overview` | staff | dashboard metrics |
| `GET /api/v1/admin/conversations[/{id}]`, `POST .../reply`, `POST .../resolve` | staff | monitoring and human replies |
| `GET/POST/DELETE /api/v1/admin/documents`, `POST .../reindex`, `POST /api/v1/admin/search` | staff | knowledge base |
| `GET /api/v1/evals/runs[/{id}]`, `GET /api/v1/public/eval-summary` | staff / public | evaluation results |
| `POST /mcp` | staff or widget token | MCP (streamable HTTP): `tools/list`, `tools/call` |

## Security

Security is enforced in the backend; the model is treated as untrusted.

- **Tenant isolation, twice.** Every tenant table has a `shop_id`, child rows reference parents through
  composite `(shop_id, id)` foreign keys, and PostgreSQL **row-level security** hides other shops' rows from
  the application role (which has no `BYPASSRLS` and cannot write the `shops` table). The current shop is
  set per transaction (`app.shop_id`); a query that forgets its filter returns nothing instead of leaking.
- **Tool authorisation on the server.** Identity, shop and scopes come from the signed session, never from
  tool arguments. Tool schemas are strict (`extra="forbid"`), so a model or MCP client adding `shop_id`,
  `customer_id` or `price` gets a validation error. Customers only see their own orders; "not yours" and
  "does not exist" give the same answer. No tool can change prices or apply discounts. Every attempt,
  including denied ones, is audited with redacted arguments.
- **Prompt injection.** Multilingual input rules (instruction overrides, prompt extraction, role hijacking,
  special tokens, SQL injection, data exfiltration, price manipulation, authority claims) after Unicode
  normalisation (invisible characters, leetspeak, Arabic diacritics); blocked messages never reach the
  model. Retrieved documents are data, not instructions, and chunks that address the model are
  **quarantined at ingestion**. Output checks catch canary leaks, "I have applied a discount" claims,
  other people's contact data and numbers that are not in the evidence.
- **Input validation and SQL safety.** Pydantic models with size limits; parameterised SQLAlchemy queries
  only; full-text queries are built from word characters only; uploads are checked by content signature.
- **Auth and abuse.** Argon2 password hashing, separate JWT types and audiences (staff, widget session,
  shop-signed identity), constant-time comparisons, PostgreSQL-backed rate limits (shared by replicas),
  brute-force lockout for order verification, per-shop CORS from the database.
- **No sensitive data in logs.** Structured JSON logs and Langfuse traces pass through a redaction step
  (e-mails, phone numbers, card numbers, tokens); IP addresses are only stored as salted hashes.

The adversarial suite ([`tests/security/test_adversarial.py`](backend/tests/security/test_adversarial.py))
plays a curious customer, a malicious visitor, a jailbroken model (scripted to invent order numbers,
numbers and discounts, or to leak its prompt), a poisoned document and a member of another shop's staff.

## Evaluation

[`backend/evals`](backend/evals): 130 realistic cases (62 English, 33 French, 20 Arabic, 15 Tunisian
Arabic) covering policies, product information, stock, search, order status (own orders, guests, other
customers), follow-ups, unknown questions, hand-off, tickets, prompt injection and price manipulation. Each
expectation comes from the seeded data or the documents.

Metrics (deterministic unless noted):

| Metric | Definition |
| --- | --- |
| Correctness | expected outcome (answered / unknown / needs info / escalated / refused) and required facts, numbers and dates present, forbidden content absent |
| Retrieval hit rate, MRR | the expected document is among the retrieved sources, and its rank |
| Faithfulness | no number in the answer outside the evidence (tool results, retrieved chunks, question); in full mode the LLM judge also checks claims |
| Hallucination rate | unfaithful answers, forbidden content, or an answer where the expected behaviour was "I don't know" |
| Language consistency | the answer is in the customer's language |
| Tool selection / execution | required tools called, forbidden tools not called; tool calls ended with the expected status |
| Injection resistance | adversarial cases refused or answered safely, with nothing leaked |
| Judge correctness (full mode) | LLM judge score of at least 4/5 against a reference answer |

```bash
docker compose --profile dev run --rm dev python -m evals.run --mode offline   # no LLM
docker compose --profile dev run --rm dev python -m evals.run --mode full      # needs an LLM provider
```

Runs are stored in the database (evaluation dashboard) and written to
[`backend/evals/reports`](backend/evals/reports) with per-metric, per-language and per-category scores,
failed cases and the change since the previous run. The **Evaluation** workflow runs the offline mode on
every change to the agent, the knowledge base or the dataset, fails below a pass rate of 0.65 or above a
hallucination rate of 0.02, and adds the full mode when an `LLM_PRIMARY_API_KEY` secret is configured.

### Results (real run, offline mode)

Only measured numbers are reported. The **full mode (LLM agent + LLM judge) has not been run yet**: the
development machine had no API key, and the free local model was too slow on its CPU (about 0.4 tokens/s)
to run 130 cases. The scores below are for the offline mode, with no LLM at all.

Run of 22 November 2026, [report](backend/evals/reports/offline-latest.md): **94/130 cases passed (72.3%)**.

| Metric | Score |
| --- | ---: |
| Correctness | 75.4% |
| Retrieval hit rate | 75.9% |
| Retrieval MRR | 71.8% |
| Faithfulness | 100.0% |
| Hallucination rate | 0.8% (1 case) |
| Language consistency | 96.2% |
| Tool selection | 97.4% |
| Tool execution | 96.9% |
| Injection resistance | 100.0% |

| Language | Cases | Pass rate |
| --- | ---: | ---: |
| Arabic | 20 | 75.0% |
| Tunisian Arabic | 15 | 60.0% |
| English | 62 | 72.6% |
| French | 33 | 75.8% |

How to read this: orders, stock, products, hand-off, tickets, cross-customer access, injection and price
manipulation pass at or near 100% because they rely on tools and deterministic checks. Policy questions
pass at 44%: without a model there is no query translation (an English question about the French-only
returns policy scores low in the reranker) and no answer writing (the quoted section can be in another
language or miss the exact fact). The single hallucination-rate case is an answer quoting the closest
catalogue section for a question about an unreleased product, where "I don't know" was expected. Some
rule-based planner fixes were made after looking at failures in this dataset, so treat the offline score
as a baseline, not as a held-out measurement.

## Configuration

All settings are environment variables; see [`.env.example`](.env.example) and
[`backend/app/config.py`](backend/app/config.py). No secret has a default value and `.env` is git-ignored.
In production, set `APP_ENV=production` (the API refuses to start without `JWT_SECRET`) and
`DEMO_MODE=false`.

## Deployment

The images are production builds: the API runs as a non-root user with a health check, nginx serves the
static app and `widget.js` with security headers and proxies `/api` and `/mcp`. For a server:

1. Use a managed PostgreSQL 15+ with the `vector` and `pg_trgm` extensions, and point
   `MIGRATION_DATABASE_URL` (owner) and `DATABASE_URL` (application role) at it.
2. Set `APP_ENV=production`, `DEMO_MODE=false`, a strong `JWT_SECRET`, an LLM provider and, optionally,
   Langfuse keys.
3. Run the `migrate` service once per release, then `api` and `web` behind HTTPS.
4. Add each shop's site to its `allowed_origins`, and create staff with
   `python -m app.cli create-staff --shop <slug> --email <email> --name <name>`.

## Limitations and next steps

- The full LLM evaluation has not been run (no API key during development); only offline results exist.
- On CPU, local models are slow: the reranker adds about 1–3 s per knowledge question, and the bundled
  Qwen3-1.7B option needs a much faster machine than the development laptop to be usable.
- Local Whisper `base` is fast but makes mistakes, especially in Arabic; `WHISPER_MODEL=small` or the
  OpenAI provider is more accurate. Browser text-to-speech depends on the voices installed on the device.
- The Tunisian Arabic detector is lexicon-based and replies in Arabic script, not in Arabizi.
- Document ingestion runs as an in-process background task; a job queue would be needed for heavy volumes.
- Ideas: streaming answers, a shop-configurable escalation inbox (e-mail/Slack), per-shop model and
  threshold settings, semantic caching of frequent questions.

## License

[MIT](LICENSE)
