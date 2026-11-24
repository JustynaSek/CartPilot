---

## `docs/SCHEMA.sql`

```sql
-- Docelowy schemat PostgreSQL 16 + pgvector
-- Źródło prawdy dla modeli SQLAlchemy 2.0 i migracji Alembic.
-- Uwaga: tabela `offers` jest przygotowana pod Fazę 2 (można ją utworzyć od razu w pierwszej migracji).

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Użytkownicy (multi-tenant + whitelista + bezpiecznik kosztów)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id BIGINT UNIQUE NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    daily_image_limit INT NOT NULL DEFAULT 15,
    notification_prefs JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Warstwa pamięci semantycznej: żywy profil zakupowy użytkownika
CREATE TABLE user_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    profile_markdown TEXT NOT NULL DEFAULT '',
    preferred_stores TEXT[] NOT NULL DEFAULT '{}',
    avoided_stores TEXT[] NOT NULL DEFAULT '{}',
    custom_rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    receipts_since_last_update INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Warstwa transakcyjna: nagłówki paragonów
CREATE TABLE receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    store_name VARCHAR(120) NOT NULL,
    store_normalized VARCHAR(80) NOT NULL, -- np. 'lidl', 'aldi', 'delikatesy_centrum'
    purchased_at TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'PLN',
    total_amount NUMERIC(10, 2) NOT NULL,
    computed_sum NUMERIC(10, 2) NOT NULL,
    sum_diff NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    review_reason TEXT,
    status VARCHAR(24) NOT NULL DEFAULT 'confirmed'
        CHECK (status IN ('pending_review', 'confirmed', 'rejected')),
    raw_extraction JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_receipts_user_date ON receipts (user_id, purchased_at DESC);
CREATE INDEX idx_receipts_user_status ON receipts (user_id, status);

-- 4. Pozycje paragonów + warstwa wektorowa (pgvector)
CREATE TABLE receipt_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_id UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    raw_name VARCHAR(255) NOT NULL,        -- np. 'ŁOS. ATL. FIL. 300G'
    normalized_name VARCHAR(160) NOT NULL, -- np. 'filet z łososia'
    category VARCHAR(60) NOT NULL,         -- np. 'ryby', 'owoce', 'warzywa', 'nabial', 'slodycze'
    quantity NUMERIC(10, 3) NOT NULL DEFAULT 1.000,
    unit VARCHAR(20) NOT NULL DEFAULT 'szt', -- 'szt', 'kg', 'g', 'l', 'ml'
    unit_price NUMERIC(10, 2),
    discount_amount NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    total_price NUMERIC(10, 2) NOT NULL,   -- finalna cena po rabacie dla tej pozycji
    embedding vector(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_receipt_items_user_norm ON receipt_items (user_id, normalized_name);
CREATE INDEX idx_receipt_items_user_cat ON receipt_items (user_id, category);
CREATE INDEX idx_receipt_items_receipt ON receipt_items (receipt_id);
CREATE INDEX idx_receipt_items_embedding
    ON receipt_items USING hnsw (embedding vector_cosine_ops);

-- 5. Migawki stanu lodówki / szafek / zakupów ze zdjęć
CREATE TABLE pantry_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type VARCHAR(24) NOT NULL DEFAULT 'fridge'
        CHECK (source_type IN ('fridge', 'pantry', 'groceries')),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    detected_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- Format elementu JSONB: {"name": "mleko", "category": "nabial", "level": "low|medium|high|empty"}
    summary_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pantry_user_captured ON pantry_snapshots (user_id, captured_at DESC);

-- 6. [FAZA 2] Wspólna tabela promocji z gazetek
CREATE TABLE offers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_name VARCHAR(80) NOT NULL,       -- np. 'lidl', 'aldi', 'delikatesy_centrum'
    product_name VARCHAR(255) NOT NULL,
    normalized_name VARCHAR(160) NOT NULL,
    category VARCHAR(60) NOT NULL,
    promo_price NUMERIC(10, 2) NOT NULL,
    regular_price NUMERIC(10, 2),
    unit_price_normalized NUMERIC(10, 2),  -- cena w przeliczeniu na 1 kg / 1 l / 1 szt
    unit VARCHAR(20) NOT NULL DEFAULT 'szt',
    conditions TEXT,                       -- np. 'z aplikacją Lidl Plus, przy zakupie 2 szt.'
    valid_from DATE NOT NULL,
    valid_to DATE NOT NULL,
    source_hash VARCHAR(64) UNIQUE NOT NULL,
    embedding vector(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_offers_store_dates ON offers (store_name, valid_from, valid_to);
CREATE INDEX idx_offers_embedding
    ON offers USING hnsw (embedding vector_cosine_ops);

-- 7. Telemetria wywołań LLM i kontrola kosztów
CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    trigger_type VARCHAR(32) NOT NULL,     -- 'telegram_photo', 'telegram_chat', 'cron', 'mcp'
    agent_name VARCHAR(64) NOT NULL,       -- 'classifier', 'receipt_ocr', 'pantry_vision', 'profiler'
    model_name VARCHAR(80) NOT NULL,
    tokens_in INT NOT NULL DEFAULT 0,
    tokens_out INT NOT NULL DEFAULT 0,
    estimated_cost_usd NUMERIC(10, 6) NOT NULL DEFAULT 0.000000,
    latency_ms INT NOT NULL DEFAULT 0,
    status VARCHAR(24) NOT NULL DEFAULT 'success'
        CHECK (status IN ('success', 'retry', 'error')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agent_runs_user_date ON agent_runs (user_id, created_at DESC);