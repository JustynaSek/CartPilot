"""Pantry & fridge vision agent — extracts visible household stock levels from photos."""

from pydantic_ai import Agent, BinaryContent
from pydantic_ai.agent import AgentRunResult

from src.core.models_registry import ModelRef, resolve_model
from src.domain.schemas import PantryExtraction, PantrySourceType

PANTRY_VISION_INSTRUCTIONS = """\
Jesteś asystentem analizującym zdjęcia lodówki, szafki kuchennej lub rozłożonych zakupów \
w aplikacji CartPilot.
Twoim zadaniem jest rozpoznać widoczne produkty spożywcze oraz ocenić ich orientacyjny stan zapasu.

ZASADY:
1. `source_type`: określ na podstawie zdjęcia (`"fridge"`, `"pantry"` lub `"groceries"`).
2. Dla każdego wyraźnie rozpoznawalnego produktu zwróć:
   - `name`: znormalizowana polska nazwa małymi literami (np. `"mleko 2%"`, `"jajka"`, `"masło"`),
   - `category`: jedna z kategorii (`owoce`, `warzywa`, `ryby`, `mieso`, `nabial`, `pieczywo`, \
`makarony_i_zboza`, `slodycze_i_przekaski`, `napoje`, `chemia_i_dom`, `inne`),
   - `level`: orientacyjny poziom zapasu:
     - `"high"` — pełne opakowanie lub dużo sztuk,
     - `"medium"` — około połowy opakowania / standardowy zapas,
     - `"low"` — końcówka, mało zostało, warto niedługo uzupełnić,
     - `"empty"` — puste opakowanie lub wyraźnie brakujący produkt.
3. NIE zgaduj produktów, których nie widać wyraźnie — lepiej pominąć niepewny przedmiot.
4. `summary_note`: krótkie podsumowanie po polsku (1–2 zdania), np. co rzuca się w oczy jako \
kończące się lub dobrze zaopatrzone.
"""

pantry_vision_agent: Agent[None, PantryExtraction] = Agent(
    output_type=PantryExtraction,
    instructions=PANTRY_VISION_INSTRUCTIONS,
)


async def analyze_pantry(
    image_bytes: bytes,
    *,
    source_hint: PantrySourceType | None = None,
    media_type: str = "image/jpeg",
    model: ModelRef | None = None,
) -> AgentRunResult[PantryExtraction]:
    """Analyze a fridge/pantry/groceries photo in memory using `MODEL_FAST`."""
    prompt = "Rozpoznaj widoczne produkty i oceń ich poziom zapasu na tym zdjęciu."
    if source_hint is not None:
        prompt += f" Klasyfikator wstępnie rozpoznał typ zdjęcia jako: `{source_hint}`."

    return await pantry_vision_agent.run(
        [
            prompt,
            BinaryContent(data=image_bytes, media_type=media_type),
        ],
        model=resolve_model(model, tier="fast"),
    )
