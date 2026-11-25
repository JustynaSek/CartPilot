"""Polish fiscal receipt OCR agent with Reflection support.

Implements the prompt rules from Section 3A of `docs/PHASE_1_SPEC.md`:
- Discount lines (`OPUST`, `RABAT`, `PROMOCJA`, `LIDL PLUS`) folded into the product's
  `discount_amount` and subtracted from its `total_price`.
- Basket-wide discounts stored as a separate `"inne"` item with a negative `total_price`.
- VAT rate letters (`A`, `B`, `C`, `PTU`) ignored.
- Weight lines (`0,452 x 19,99 = 9,04`) parsed into `quantity`, `unit`, `unit_price`, `total_price`.
- Deposits (kaucje) and shopping bags (reklamówki) mapped to category `"inne"`.
"""

from pydantic_ai import Agent, BinaryContent
from pydantic_ai.agent import AgentRunResult

from src.core.models_registry import ModelRef, resolve_model
from src.domain.schemas import ReceiptExtraction

RECEIPT_OCR_INSTRUCTIONS = """\
Jesteś precyzyjnym ekstraktorem danych z polskich paragonów fiskalnych w aplikacji CartPilot.
Analizujesz zdjęcie paragonu i zwracasz ustrukturyzowany obiekt `ReceiptExtraction`.

ZASADY SPECYFICZNE DLA POLSKICH PARAGONÓW FISKALNYCH:
1. RABATY I PROMOCJE:
   - Linie typu `OPUST`, `RABAT`, `PROMOCJA`, `LIDL PLUS`, `KUPON` występujące bezpośrednio pod \
produktem przypisz do tego produktu: wpisz dodatnią kwotę w `discount_amount` (np. `3.50` dla \
`OPUST -3,50`) oraz wpisz w `total_price` FINALNĄ kwotę PO odjęciu rabatu.
   - NIE twórz osobnej pozycji „Rabat” dla rabatu przypisanego do konkretnego produktu.
   - Wyjątek: jeśli jest to rabat na cały koszyk (np. kupon `-10,00` na końcu paragonu), zapisz go \
jako osobną pozycję w kategorii `"inne"` z ujemną wartością `total_price`.
2. STAWKI VAT:
   - Ignoruj litery stawek VAT na końcu linii (`A`, `B`, `C`, `D`, `E`, `PTU`).
3. PRODUKTY WAGOWE:
   - Rozpoznawaj zapisy wagowe typu `0,452 x 19,99 = 9,04` (`quantity=0.452`, `unit="kg"`, \
`unit_price=19.99`, `total_price=9.04`).
4. KAUCJE I REKLAMÓWKI:
   - Kaucje za butelki/skrzynki oraz torby/reklamówki przypisuj do kategorii `"inne"`.
5. NORMALIZACJA NAZW:
   - `raw_name`: dokładny zapis z paragonu (np. `"POM. MALIN. LUZ"`).
   - `normalized_name`: naturalna polska nazwa słownikowa, małymi literami, bez skrótów \
i gramatury (np. `"pomidor malinowy"`, `"filet z łososia"`, `"mleko 2%"`).
   - `store_normalized`: nazwa sieci małymi literami w `snake_case` bez polskich znaków \
(np. `lidl`, `aldi`, `biedronka`, `delikatesy_centrum`, `kaufland`, `auchan`, `dino`, `inne`).
6. KWOTA KOŃCOWA I DATA:
   - `total_amount`: dokładna kwota z linii `SUMA PLN` (używaj kropki dziesiętnej).
   - `purchased_at`: data i godzina z paragonu w formacie ISO 8601 \
(jeśli nieczytelna, zwróć `null`).
   - Jeśli jakiś fragment paragonu jest ucięty lub nieczytelny, opisz to krótko w `notes`.
"""

receipt_ocr_agent: Agent[None, ReceiptExtraction] = Agent(
    output_type=ReceiptExtraction,
    instructions=RECEIPT_OCR_INSTRUCTIONS,
)


async def extract_receipt(
    image_bytes: bytes,
    *,
    media_type: str = "image/jpeg",
    model: ModelRef | None = None,
) -> AgentRunResult[ReceiptExtraction]:
    """Pass 1: Extract structured data from a Polish fiscal receipt photo."""
    return await receipt_ocr_agent.run(
        [
            "Odczytaj wszystkie pozycje, sklep, datę oraz SUMA PLN z tego paragonu.",
            BinaryContent(data=image_bytes, media_type=media_type),
        ],
        model=resolve_model(model, tier="fast"),
    )


async def reflect_receipt(
    image_bytes: bytes,
    previous_extraction: ReceiptExtraction,
    validation_feedback: str,
    *,
    media_type: str = "image/jpeg",
    model: ModelRef | None = None,
) -> AgentRunResult[ReceiptExtraction]:
    """Pass 2 (Reflection): Re-examine the receipt image using deterministic error feedback."""
    previous_json = previous_extraction.model_dump_json(indent=2)
    prompt = (
        "Poprzednia próba odczytu tego paragonu nie przeszła walidacji matematycznej lub "
        "kompletności danych.\n\n"
        f"DIAGNOZA BŁĘDU:\n{validation_feedback}\n\n"
        f"TWÓJ POPRZEDNI WYNIK (JSON):\n{previous_json}\n\n"
        "Sprawdź ponownie zdjęcie paragonu linijka po linijce — w szczególności linie "
        "OPUST / RABAT / PROMOCJA, brakujące pozycje oraz linię SUMA PLN — i zwróć "
        "poprawiony, pełny obiekt `ReceiptExtraction`."
    )
    return await receipt_ocr_agent.run(
        [
            prompt,
            BinaryContent(data=image_bytes, media_type=media_type),
        ],
        model=resolve_model(model, tier="fast"),
    )
