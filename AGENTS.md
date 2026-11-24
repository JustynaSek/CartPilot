# AGENTS.md — Instrukcje współpracy i reguły projektu

## 1. Źródła prawdy w tym repozytorium
Zanim zaprojektujesz lub zmodyfikujesz kod, trzymaj się założeń opisanych w:
- `docs/ARCHITECTURE.md` — architektura, podział warstw i stack technologiczny
- `docs/SCHEMA.sql` — docelowy schemat PostgreSQL + `pgvector`
- `docs/PHASE_1_SPEC.md` — bieżący zakres MVP i kryteria akceptacji

Nie implementuj funkcji z przyszłych faz (gazetki, Agent Doradca, Cron, MCP), dopóki wyraźnie o to nie poproszę.

---

## 2. Profil programistki (poziom wyjaśnień)
Jestem doświadczoną programistką **Angular / TypeScript**, która przebranżawia się na **AI Agents Developer (Python)**.

### Co już znam — NIE tłumacz podstaw:
- Podstawy inżynierii oprogramowania (OOP, SOLID, wzorce projektowe, REST API, Git, testy jednostkowe, zmienne środowiskowe).
- TypeScript, JavaScript, asynchroniczność w JS (`async/await`, `Promise`), Dependency Injection (Angular).
- Podstawową składnię Pythona.
- Teoretyczne podstawy agentów AI (wzorce z kursu Andrew Ng: Reflection, Tool Use, Planning, Multi-agent; podstawy koncepcji MCP).

### Czego się uczę — TŁUMACZ dokładnie, co robisz i dlaczego:
- **Tooling Pythona:** `uv`, `pyproject.toml`, `ruff`, `pytest` + `pytest-asyncio` (fixtures, mockowanie async).
- **Asynchroniczny Python w praktyce:** pułapki `asyncio` (np. blokowanie event loopa, zarządzanie cyklem życia połączeń).
- **Warstwa bazy danych:** `SQLAlchemy 2.0` (styl async z `asyncpg`, `Mapped`, `mapped_column`, `select()`, sesje i transakcje), migracje `Alembic` (szczególnie z typem `vector`), `pgvector` (embeddingi, podobieństwo kosinusowe, indeksy HNSW).
- **Framework agentowy i LLM:** `Pydantic v2` (walidatory, `Decimal`, `Settings`), `PydanticAI` (`Agent`, `RunContext`, Dependency Injection dla narzędzi, `output_type` / Structured Outputs, obsługa multimodalnych wejść, `TestModel`, odczyt użycia tokenów), projektowanie promptów i pętli refleksji, ewaluacje (Evals).
- **Interfejsy Pythona:** `aiogram 3.x` (Router, Dispatcher, Middleware, filtry, callback query dla przycisków inline, pobieranie bajtów zdjęcia w pamięci), `FastAPI` (lifespan, `Depends`, webhooki), a w późniejszej fazie `FastMCP`.

**Styl tłumaczenia:** Kiedy wprowadzasz nowy element z listy powyżej, używaj krótkich analogii do **Angulara / TypeScriptu** (np. *„`RunContext` w PydanticAI działa podobnie do serwisu wstrzykiwanego przez DI w Angularze”*). Tłumacz **dlaczego** wybierasz dane rozwiązanie, a nie tylko przepisywanie kodu na polskie słowa.

---

## 3. Tryb pracy i komunikacji
1. **Język:** Odpowiadaj po polsku. Kod, nazwy zmiennych, klas, tabel i komunikaty commitów pisz po angielsku (poza polskimi tekstami UX bota Telegram i nazwami kategorii produktów zgodnie ze specyfikacją).
2. **Najpierw krótki plan, potem kod:** Przy każdym nietrywialnym zadaniu wypisz w 3–6 punktach, jakie pliki utworzysz/zmienisz i jaka jest logika rozwiązania. Poczekaj na moje „ok” przed edycją plików (chyba że wprost napiszę „zaimplementuj od razu”).
3. **Małe, atomowe kroki:** Pracuj wyłącznie nad jednym podzadaniem naraz. Nie refaktoruj przy okazji niezwiązanych plików.
4. **Krótkie podsumowanie edukacyjne na koniec:** Po wykonaniu zadania dodaj krótką sekcję **„Co nowego w tym kroku”** (maks. 3–5 punktów), wyjaśniając najciekawsze decyzje z Pythona/AI w tym konkretnym kodzie oraz ewentualne pułapki, na które warto zwrócić uwagę.
5. **Uczciwość przy niejasnościach:** Jeśli w specyfikacji brakuje decyzji (np. obsługa edge-case’u na paragonie), najpierw zapytaj lub zaproponuj 2 opcje z rekomendacją zamiast zgadywać po cichu.

---

## 4. Twarde standardy techniczne (nie używaj przestarzałych wzorców)
- **Python 3.12+:** pełne typowanie (`list[str]`, `X | None` — bez `typing.List`, `typing.Optional`).
- **SQLAlchemy 2.0 ONLY:** wyłącznie `select(...)`, `Mapped[...]`, `mapped_column(...)` i `AsyncSession`. Zakaz używania starego API `session.query(...)`.
- **Pydantic v2 ONLY:** `model_validate`, `model_dump`, `ConfigDict` (bez przestarzałego `class Config:` z v1).
- **PydanticAI & Gemini:** konfiguracja modeli wyłącznie przez zmienne środowiskowe (`MODEL_FAST`, `MODEL_REASONING`) bez hardcodowania nazw modeli w plikach agentów.
- **aiogram 3.x ONLY:** `Router`, `F.photo`, nowoczesne middleware (bez wzorców z `aiogram 2.x`).
- **Czysta architektura:** zero logiki AI i zapytań SQL w handlerach Telegrama (`src/interfaces/telegram/`). Handlery wyłącznie wołają serwisy z `src/services/`.
- **Prywatność:** obrazy z Telegrama trzymaj wyłącznie jako `bytes` w pamięci RAM; nigdy nie zapisuj plików zdjęć na dysk ani do bazy.

---

## 5. Bezpieczeństwo, koszty API i weryfikacja
- **Zero płatnych wywołań API w testach automatycznych:** testy `pytest` MUSZĄ mockować modele (np. `pydantic_ai.models.test.TestModel` / `FunctionModel`). Nigdy nie uruchamiaj skryptów uderzających w prawdziwe Gemini API bez mojej wyraźnej zgody.
- **Sekrety:** nigdy nie wpisuj kluczy API ani tokenów bota w kodzie; nie edytuj ani nie commituj pliku `.env` (aktualizuj wyłącznie `.env.example`).
- **Komendy destrukcyjne:** zanim zaproponujesz lub uruchomisz komendę usuwającą dane (np. `rm -rf`, `docker compose down -v`, `alembic downgrade`, reset bazy), wyraźnie ostrzeż i poczekaj na potwierdzenie.
- **Checklista przed zakończeniem zadania:** po zmianach w kodzie zawsze uruchom i napraw błędy z:
  1. `uv run ruff check .`
  2. `uv run pytest`

  ---

## 6. Zasady pracy z Git
- **Brak automatycznych commitów i pushy:** NIGDY nie wykonuj `git commit` ani `git push` z własnej inicjatywy. Po zakończeniu kroku i przejściu testów (`ruff` + `pytest`) pokaż `git status`, podsumuj zmiany i zaproponuj gotową treść commita — wykonaj commit dopiero po moim potwierdzeniu.
- **Zakaz destrukcyjnych operacji:** NIGDY nie uruchamiaj `git reset --hard`, `git push --force`, `git checkout -- .`, `git clean -fd` ani `git rebase` na wypchniętych gałęziach bez wyraźnej zgody.
- **Konwencja commitów (Conventional Commits, po angielsku):** Używaj zwięzłych komunikatów z zakresem, np.:
  - `feat(db): add SQLAlchemy models and initial pgvector migration`
  - `feat(ocr): implement receipt extraction with reflection loop`
  - `test(cadence): add unit tests for purchase interval calculation`
  - `docs: update Phase 1 spec`
- **Gałęzie (opcjonalnie per krok):** Przed rozpoczęciem większego kroku (np. nowego kroku z `PHASE_1_SPEC.md`) zaproponuj utworzenie krótkiej gałęzi roboczej (np. `feat/phase1-infra`, `feat/phase1-ocr`), zamiast wrzucać wszystko bezpośrednio na `main`.
- **Higiena stagingu i prywatność:** Zamiast ślepego `git add .` zawsze najpierw sprawdź `git status`. Upewnij się, że w repozytorium nigdy nie znajdą się: `.env`, `.venv/`, `__pycache__/`, bazy lokalne ani żadne prywatne zdjęcia paragonów używane do testów (np. katalog `tmp/` lub `local_receipts/`).