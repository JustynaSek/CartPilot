# CartPilot 🛒🤖

**Multimodal AI shopping agent** that learns household buying habits from receipt and fridge photos, tracks purchase cadence, and matches user preferences against weekly supermarket promotions.

> **Project Status:** Active development — currently building **Phase 1 (MVP: Vision Ingestion, Reflection Loop & 3-Layer Memory)**.

---

## Why CartPilot?

Most LLM wrappers rely solely on unstructured vector search, which fails at basic grocery math (purchase intervals, receipt discounts, budget totals). CartPilot is built as a **hybrid agentic system**:

- **Deterministic code for math & cadence:** Receipt sum validation, discount handling, purchase frequency (`urgency_ratio`), and daily usage limits run in pure Python and SQL.
- **Agentic Workflow with Reflection:** Receipt OCR runs through a structured vision pipeline (`PydanticAI`) that deterministically verifies line-item sums against the receipt total, triggers a targeted reflection retry on mismatch, and falls back to Human-in-the-Loop confirmation in Telegram.
- **3-Layer Memory in one PostgreSQL + `pgvector` database:**
  1. *Transactional (SQL)* — normalized receipt items, prices, pantry snapshots, and restock cadence.
  2. *Semantic Profile (Markdown + JSONB)* — evolving store preferences, avoided chains, and custom user rules editable via chat.
  3. *Vector (`pgvector`)* — product embeddings for entity resolution between abbreviated receipt lines and promotional flyers.
- **Provider-Agnostic & Cost-Aware:** Configured via environment variables (`MODEL_FAST` / `MODEL_REASONING`), defaulting to Google Gemini API with full token/cost telemetry logged to `agent_runs`.
- **Privacy-First & Multi-Tenant:** Raw receipt/fridge images are processed strictly in RAM and never persisted. All user tables are isolated by `user_id` from day one.

---

## Architecture

```mermaid
flowchart LR
    U[Telegram Bot / Remote MCP] -->|Photo / Query| I[Ingestion Pipeline<br/>Vision + Reflection]
    U -->|Ask / Update Rules| A[Advisor & Profiler Agents<br/>PydanticAI]
    I -->|Validated JSON + Embeddings| DB[(PostgreSQL 16 + pgvector<br/>3-Layer Memory)]
    F[Flyer Provider<br/>Phase 2] -->|Structured Promotions| DB
    A <-->|SQL Tools + Vector Search| DB
    C[Scheduler / Cron<br/>Phase 3] --> A
    A -->|Shopping Plan| O[Telegram / Email / Calendar]