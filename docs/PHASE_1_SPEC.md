# Faza 1: MVP — Paragon, Lodówka i Pamięć Zakupowa

## 1. Zakres Fazy 1

### Wchodzi w zakres (IN SCOPE)
- Lokalna infrastruktura: Docker Compose (`pgvector/pgvector:pg16`), `uv`, SQLAlchemy 2.0 async, pierwsza migracja Alembic zgodna z `docs/SCHEMA.sql`.
- Bot Telegram (`aiogram 3`, tryb long-polling na czas developmentu) z prostą whitelistą `telegram_id` (plus lista `ADMIN_TELEGRAM_IDS` w `.env`, która jest automatycznie aktywowana).
- Pipeline przetwarzania zdjęć (`IngestionService`):
  - Limit dzienny zdjęć per `user_id` (`users.daily_image_limit`).
  - Klasyfikator zdjęcia (`receipt` / `fridge_or_pantry` / `unsupported`).
  - Ekstrakcja polskich paragonów z **krokami walidacji deterministycznej i refleksji (max 1 retry)** oraz trybem `Human-in-the-loop` (przyciski inline w Telegramie przy rozbieżności sumy).
  - Ekstrakcja zawartości lodówki/szafki do `pantry_snapshots`.
  - Generowanie embeddingów dla `receipt_items.normalized_name` (możliwość wyłączenia flagą w testach).
- Deterministyczny moduł cykli zakupowych (`src/domain/cadence.py`).
- Agent Profilera (`src/agents/profiler.py`): synteza profilu z historii paragonów (automatycznie co 5 zatwierdzonych paragonów lub na komendę) + obsługa ręcznej korekty preferencji przez czat.
- Rejestrowanie każdego wywołania LLM w `agent_runs`.
- Testy jednostkowe (`pytest`) dla walidacji matematycznej paragonu i wyliczania cykli zakupowych.

### NIE wchodzi w zakres (OUT OF SCOPE — nie implementuj teraz)
- Scrapowanie ani parsowanie gazetek promocyjnych (`OfferProvider` i tabela `offers` czekają na Fazę 2).
- Agent Doradca porównujący oferty sklepów (Faza 2).
- Harmonogram Cron, wysyłka e-maili, Google Calendar (Faza 3).
- Serwer MCP i panel webowy (Faza 4).

---

## 2. Kontrakty Pydantic (`src/domain/schemas.py`)
Zaimplementuj najpierw te kontrakty jako sztywne modele wejścia/wyjścia agentów i serwisów:

- **`ImageClassification`**:
  - `image_type: Literal["receipt", "fridge", "pantry", "groceries", "unsupported"]`
  - `confidence: float` (0.0–1.0)
  - `reason: str`

- **`ReceiptItemExtraction`**:
  - `raw_name: str` — oryginalny zapis z paragonu (np. `"POM. MALIN. LUZ"`)
  - `normalized_name: str` — ustandaryzowana polska nazwa w liczbie pojedynczej lub naturalnej formie słownikowej, małymi literami (np. `"pomidor malinowy"`, `"filet z łososia"`, `"mleko 2%"`)
  - `category: Literal["owoce", "warzywa", "ryby", "mieso", "nabial", "pieczywo", "makarony_i_zboza", "slodycze_i_przekaski", "napoje", "chemia_i_dom", "inne"]`
  - `quantity: Decimal` (domyślnie `1`)
  - `unit: Literal["szt", "kg", "g", "l", "ml"]`
  - `unit_price: Decimal | None`
  - `discount_amount: Decimal` (wartość dodatnia lub 0, np. `3.50` dla linii `OPUST -3,50`)
  - `total_price: Decimal` — **finalna kwota po rabacie za tę pozycję** (uwzględniająca `discount_amount`)

- **`ReceiptExtraction`**:
  - `store_name: str | None`
  - `store_normalized: str | None` (snake_case bez polskich znaków, np. `lidl`, `aldi`, `biedronka`, `delikatesy_centrum`, `kaufland`, `auchan`, `dino`, `inne`)
  - `purchased_at: datetime | None`
  - `total_amount: Decimal | None` (kwota z linii `SUMA PLN`)
  - `items: list[ReceiptItemExtraction]`
  - `notes: str | None` (np. nieczytelny fragment paragonu)

- **`PantryItem`**:
  - `name: str` (znormalizowana nazwa po polsku)
  - `category: str`
  - `level: Literal["high", "medium", "low", "empty"]`

- **`PantryExtraction`**:
  - `source_type: Literal["fridge", "pantry", "groceries"]`
  - `items: list[PantryItem]`
  - `summary_note: str`

- **`CadenceItem`**:
  - `normalized_name: str`
  - `category: str`
  - `purchase_count: int`
  - `avg_interval_days: float`
  - `days_since_last: float`
  - `urgency_ratio: float` (`days_since_last / avg_interval_days`)
  - `last_purchased_at: datetime`

- **`UserProfileOutput`**:
  - `profile_markdown: str` (zwięzły opis w 4–8 zdaniach po polsku)
  - `preferred_stores: list[str]`
  - `avoided_stores: list[str]`
  - `custom_rules: list[str]`

---

## 3. Szczegóły kluczowej logiki

### A. Ekstrakcja polskich paragonów + Pętla Refleksji (`src/agents/receipt_ocr.py` + `src/domain/receipt_math.py`)
Prompt dla `receipt_ocr` MUSI jawnie instruować model o specyfice polskich paragonów fiskalnych:
1. Linie typu `OPUST`, `RABAT`, `PROMOCJA`, `LIDL PLUS` występujące bezpośrednio pod produktem należy przypisać jako `discount_amount` do właściwego produktu i odjąć od `total_price` tej pozycji (nie tworzyć osobnej pozycji „Rabat” z ujemną ceną, chyba że jest to rabat na cały koszyk — wtedy zapisać jako osobną pozycję z kategorią `"inne"`).
2. Ignorować litery stawek VAT na końcu linii (`A`, `B`, `C`, `PTU`).
3. Rozpoznawać zapisy wagowe (np. `0,452 x 19,99 = 9,04`).
4. Kaucje za butelki/skrzynki i reklamówki mapować do kategorii `"inne"`.

**Algorytm refleksji (wykonywany w `IngestionService`):**
1. **Przebieg 1:** Wywołaj `receipt_ocr` na obrazie -> otrzymaj `ReceiptExtraction`.
2. **Walidacja deterministyczna (`receipt_math.validate_receipt`):**
   - Oblicz `computed_sum = sum(item.total_price for item in items)`.
   - Oblicz `sum_diff = abs(total_amount - computed_sum)` (jeśli `total_amount` jest `None`, oznacz błąd).
   - Sprawdź, czy `store_name` i `purchased_at` są obecne oraz czy `items` nie jest puste.
   - Próg tolerancji: `SUM_TOLERANCE_PLN = Decimal("0.50")`.
3. **Przebieg 2 (Reflection — max 1 ponowienie):**
   - Jeśli `sum_diff > 0.50` LUB brakuje `total_amount` / `store_name`, wywołaj ponownie model z oryginalnym obrazem, poprzednim JSON-em oraz precyzyjną diagnozą błędu (np. *"Suma Twoich pozycji to 114.20 PLN, ale SUMA PLN na paragonie to 108.70 PLN. Różnica wynosi 5.50 PLN. Sprawdź pominięte linie OPUST/RABAT lub błędnie odczytane kwoty."*).
4. **Decyzja po refleksji:**
   - Jeśli po walidacji wszystko mieści się w progu -> zapisz paragon ze `status = 'confirmed'`, `needs_review = False`.
   - Jeśli nadal występuje rozbieżność -> zapisz paragon ze `status = 'pending_review'`, `needs_review = True`, wpisz `review_reason` i wyślij użytkownikowi na Telegramie podsumowanie z przyciskami inline:
     - `[Zatwierdź mimo różnicy]` (zmienia status na `confirmed`)
     - `[Odrzuć paragon]` (zmienia status na `rejected`)

### B. Deterministyczne cykle zakupowe (`src/domain/cadence.py`)
Dla danego `user_id` bierzemy wyłącznie pozycje z paragonów o `status = 'confirmed'`:
- Grupujemy zakupy po `normalized_name` oraz dacie paragonu (jeśli produkt pojawił się 2 razy na jednym paragonie, liczy się jako 1 dzień zakupowy).
- Dla produktów kupionych co najmniej **2 razy** w różnych dniach:
  - `avg_interval_days` = średnia liczba dni między kolejnymi zakupami.
  - `days_since_last` = liczba dni od ostatniego zakupu do `NOW()`.
  - `urgency_ratio = days_since_last / max(avg_interval_days, 1.0)`.
- Produkty z `urgency_ratio >= 0.85` traktujemy jako **„prawdopodobnie kończące się / czas uzupełnić”**.

### C. Profil użytkownika (`src/agents/profiler.py`)
- **Tryb syntezy:** na wejściu dostaje agregat SQL (top sklepy z liczbą wizyt i średnim koszykiem, top 30 produktów z częstotliwością, rozkład wydatków na kategorie) + dotychczasowy `user_profiles` (żeby nie nadpisywać ręcznych reguł użytkownika).
- **Tryb ręcznej korekty:** gdy użytkownik napisze zwykłą wiadomość tekstową typu *"unikam Biedronki"*, *"kupuję głównie w Lidlu i czasem w Aldi"*, *"nie jedzmy już słodyczy"*, lekki agent aktualizuje pola `preferred_stores` / `avoided_stores` / `custom_rules` oraz `profile_markdown` i odpisuje, co dokładnie zapamiętał.

---

## 4. Komendy i UX bota Telegram (`src/interfaces/telegram/`)
- `/start` — rejestruje użytkownika w `users` (jeśli jego `telegram_id` jest w `ADMIN_TELEGRAM_IDS`, ustawia `is_active = True`). Nieautoryzowanemu użytkownikowi odpisuje z jego `telegram_id` i informacją, że konto czeka na aktywację.
- **Wysłanie zdjęcia** — wysyła akcję `typing` / krótką wiadomość *"Analizuję zdjęcie..."*, uruchamia `IngestionService` i odpisuje zwięzłym podsumowaniem:
  - dla paragonu: sklep, data, liczba pozycji, suma (oraz ewentualne ostrzeżenie + przyciski potwierdzenia);
  - dla lodówki/szafki: lista wykrytych produktów z poziomem zapasu.
- `/co_kupuje` — wyświetla 2 krótkie sekcje:
  1. Produkty, które prawdopodobnie się kończą (`urgency_ratio >= 0.85`).
  2. Najczęściej kupowane produkty (top 10 wraz ze średnim cyklem w dniach).
- `/profil` — wyświetla aktualny profil zakupowy, preferowane i omijane sklepy oraz reguły (z przyciskiem inline `[Odśwież profil z paragonów]`).
- `/statystyki` — podsumowanie z ostatnich 30 dni: wydatki łącznie, rozbicie na sklepy i top kategorie + szacowany koszt API (`agent_runs`).
- **Zwykły tekst** — interpretowany jako korekta preferencji profilu lub proste pytanie o własną historię zakupów.

---

## 5. Sugerowana kolejność implementacji w Antigravity
Realizuj krok po kroku — po każdym etapie uruchom testy przed przejściem dalej:
1. **Krok 1 (Infra & DB):** `pyproject.toml`, `docker-compose.yml`, `.env.example`, `src/core/config.py`, `src/core/database.py`, modele SQLAlchemy + migracja Alembic zgodna z `docs/SCHEMA.sql`.
2. **Krok 2 (Kontrakty & Matematyka):** `src/domain/schemas.py`, `src/domain/receipt_math.py`, `src/domain/cadence.py` + testy `pytest` pokrywające rabaty, błędy sumowania i wyliczanie `urgency_ratio`.
3. **Krok 3 (Agenci PydanticAI & Telemetria):** `classifier.py`, `receipt_ocr.py`, `pantry_vision.py`, `profiler.py` + wrapper logujący tokeny do `agent_runs` + `IngestionService` z pętlą refleksji.
4. **Krok 4 (Bot Telegram):** middleware whitelisty i limitu dziennego, handlery zdjęć, komendy `/start`, `/co_kupuje`, `/profil`, `/statystyki`, przyciski inline potwierdzania paragonu.
5. **Krok 5 (Weryfikacja na żywych danych):** test na 3–5 prawdziwych polskich paragonach (w tym jednym z rabatami `OPUST` i jednym lekko pogniecionym).

---

## 6. Kryteria akceptacji (Definition of Done Fazy 1)
- [ ] `docker compose up -d` i `uv run alembic upgrade head` stawiają bazę bez błędów.
- [ ] `uv run pytest` przechodzi w 100% (testy walidacji paragonów i wyliczania cykli).
- [ ] Wysłanie zdjęcia polskiego paragonu na Telegrama zapisuje sklep, pozycje z prawidłowymi kwotami po rabatach oraz wpis w `agent_runs`.
- [ ] Przy rozbieżności sumy powyżej `0.50 PLN` uruchamia się krok refleksji, a przy utrzymaniu błędu bot pyta użytkownika o potwierdzenie przyciskami inline.
- [ ] Surowe pliki zdjęć nie pozostają na dysku ani w bazie danych po zakończeniu przetwarzania.
- [ ] Po wrzuceniu min. 2 paragonów z tym samym produktem w różnych dniach komenda `/co_kupuje` poprawnie wylicza średni odstęp dni.
- [ ] Komenda `/profil` oraz korekta preferencji zwykłą wiadomością tekstową aktualizują `user_profiles` w bazie.