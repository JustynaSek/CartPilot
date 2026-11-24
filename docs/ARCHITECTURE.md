# Shopping Agent — Architektura Systemu

## 1. Cel projektu
Wieloużytkownikowy (multi-tenant) asystent zakupowy działający docelowo przez Telegram oraz serwer MCP. System analizuje zdjęcia paragonów i zawartości lodówki/szafek, buduje 3-warstwową pamięć nawyków zakupowych użytkownika, monitoruje gazetki promocyjne wybranych sklepów (Lidl, Aldi, Delikatesy Centrum i inne) oraz doradza (na żądanie i cyklicznie), gdzie i co warto kupić danego dnia.

## 2. Główne zasady architektoniczne
1. **Hybryda deterministycznego kodu i LLM:** Matematyka (sumowanie paragonów, walidacja rabatów, obliczanie częstotliwości zakupów, limity dzienne) ZAWSZE działa w czystym Pythonie/SQL. LLM służy wyłącznie do ekstrakcji multimodalnej, normalizacji semantycznej, syntezy profilu i rozumowania doradczego.
2. **Workflow zamiast otwartej pętli tam, gdzie liczy się niezawodność:** Przetwarzanie zdjęć (Ingestion) to deterministyczny pipeline z krokiem refleksji (wzorzec Reflection), a nie otwarty agent ReAct.
3. **Czysta separacja warstw:** Interfejsy (`telegram`, `api`, `mcp`) są cienką warstwą I/O. Nie mogą zawierać promptów, logiki biznesowej ani bezpośrednich zapytań SQL. Cała logika żyje w `services/`, `domain/` i `agents/`.
4. **Multi-tenant od dnia 1:** Każda tabela należąca do użytkownika wymaga kolumny `user_id` i filtrowania po niej. Gazetki promocyjne (`offers`) są wspólne dla wszystkich użytkowników.
5. **Provider-agnostic LLM routing:** Nazwy modeli konfigurujemy przez zmienne środowiskowe w formacie PydanticAI (np. `google-gla:gemini-3.8-flash`), aby przełączenie dowolnego agenta na innego dostawcę (np. Anthropic) wymagało zmiany jednej zmiennej `.env`.
6. **Prywatność danych:** Surowe bajty zdjęć paragonów i lodówek przetwarzamy wyłącznie w pamięci RAM podczas trwania pipeline'u — nie zapisujemy ich trwale na dysku ani w bazie danych.

## 3. Stack technologiczny
- **Język i tooling:** Python 3.12+, `uv` (zarządzanie pakietami), `ruff` (linting/formatowanie), `pytest` + `pytest-asyncio`.
- **Framework agentowy:** `pydantic-ai` (silne typowanie, Dependency Injection przez `RunContext`, Structured Outputs, wsparcie dla wielu providerów i MCP).
- **Modele LLM (domyślnie Google Gemini API):**
  - `MODEL_FAST` (np. `google-gla:gemini-3.8-flash` lub `gemini-3.5-flash-lite`) — klasyfikacja zdjęć, Vision OCR paragonów i lodówki, parsowanie gazetek.
  - `MODEL_REASONING` (np. `google-gla:gemini-4-hydrogen`, opcjonalnie w przyszłości `anthropic:claude-sonnet-5.5`) — synteza profilu użytkownika, Agent Doradca.
  - `MODEL_EMBEDDING` (np. `gemini-embedding-001`, 768 wymiarów) — wektory nazw produktów do dopasowywania semantycznego.
- **Baza danych:** PostgreSQL 16 + rozszerzenie `pgvector` (lokalnie w Docker Compose), ORM `SQLAlchemy 2.0` (w pełni async z `asyncpg`), migracje `Alembic`.
- **Interfejsy:**
  - `aiogram 3.x` — bot Telegram (lokalnie long-polling, na produkcji webhook przez FastAPI).
  - `FastAPI` — warstwa HTTP (healthcheck, webhooki, endpointy pod Cron, w Fazie 4 montaż MCP).
  - `mcp` (`FastMCP`) — Faza 4: zdalny serwer MCP (Streamable HTTP).
- **Obserwowalność i koszty:** tabela `agent_runs` w bazie rejestrująca zużycie tokenów i szacowany koszt każdego wywołania + opcjonalna integracja z `logfire`.

## 4. Pamięć 3-warstwowa (PostgreSQL + pgvector)
1. **Warstwa transakcyjna (SQL):** `receipts`, `receipt_items`, `pantry_snapshots`. Źródło prawdy do wyliczania średniego cyklu zakupowego produktu (co ile dni wraca na paragon) oraz wydatków.
2. **Profil semantyczny (`user_profiles`):** Zwięzły dokument Markdown + pola strukturalne (`preferred_stores`, `avoided_stores`, `custom_rules`). Aktualizowany okresowo na bazie historii oraz ręcznie korygowany przez użytkownika na czacie.
3. **Warstwa wektorowa (`pgvector`):** Embeddingi `normalized_name` w `receipt_items` oraz `offers`, rozwiązujące problem dopasowania skrótów paragonowych do nazw w gazetkach.

## 5. Struktura katalogów
```text
shopping-agent/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── SCHEMA.sql
│   └── PHASE_1_SPEC.md
├── alembic/                 # Migracje bazy danych
├── src/
│   ├── core/
│   │   ├── config.py        # Pydantic Settings (.env)
│   │   ├── database.py      # Async engine, sessionmaker
│   │   └── models_registry.py # Konfiguracja MODEL_FAST / MODEL_REASONING
│   ├── db/
│   │   ├── models.py        # Modele SQLAlchemy 2.0
│   │   └── repositories/    # Czyste operacje DB (UserRepo, ReceiptRepo, ProfileRepo)
│   ├── domain/
│   │   ├── schemas.py       # Kontrakty Pydantic (DTO między agentami a serwisami)
│   │   ├── receipt_math.py  # Walidacja sum, rabatów i spójności paragonu
│   │   └── cadence.py       # Deterministyczne wyliczanie cykli zakupowych
│   ├── agents/
│   │   ├── classifier.py    # Router zdjęć (paragon vs lodówka vs inne)
│   │   ├── receipt_ocr.py   # Ekstrakcja paragonu + pętla refleksji
│   │   ├── pantry_vision.py # Analiza zdjęć lodówki/szafki
│   │   ├── profiler.py      # Generowanie i aktualizacja profilu użytkownika
│   │   └── advisor.py       # (Faza 2) Agent doradca zakupowy
│   ├── services/
│   │   ├── ingestion_service.py # Orkiestracja pipeline'u zdjęć + limity + zapis
│   │   └── profile_service.py   # Zarządzanie profilem i cyklami
│   ├── providers/           # (Faza 2) OfferProvider (gazetki PDF/HTML)
│   └── interfaces/
│       ├── telegram/        # Bot aiogram 3 (handlers, keyboards, middlewares)
│       ├── api/             # FastAPI app
│       └── mcp/             # (Faza 4) FastMCP server
├── evals/                   # Zestawy testowe (paragon -> złoty JSON, scenariusze)
├── tests/                   # Testy pytest (unit + integration)
├── docker-compose.yml       # PostgreSQL 16 + pgvector
├── pyproject.toml
└── .env.example