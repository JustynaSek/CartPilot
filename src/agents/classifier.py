"""Image classifier agent — routes incoming photos to the right pipeline branch.

Decides whether a photo shows a `receipt`, `fridge`, `pantry`, `groceries`, or `unsupported`.
Raw image bytes are passed strictly in RAM via `BinaryContent`.
"""

from pydantic_ai import Agent, BinaryContent
from pydantic_ai.agent import AgentRunResult

from src.core.models_registry import ModelRef, resolve_model
from src.domain.schemas import ImageClassification

CLASSIFIER_INSTRUCTIONS = """\
Jesteś klasyfikatorem zdjęć w aplikacji asystenta zakupowego CartPilot.
Twoim zadaniem jest określić, co przedstawia przesłane zdjęcie i zwrócić jedną z kategorii:
- "receipt" — paragon fiskalny, faktura uproszczona lub potwierdzenie zakupów ze sklepu.
- "fridge" — wnętrze otwartej lodówki lub zamrażarki.
- "pantry" — szafka kuchenna, spiżarnia lub półka z zapasami spożywczymi.
- "groceries" — rozłożone zakupy spożywcze (np. na blacie, stole lub w torbie).
- "unsupported" — każde inne zdjęcie (np. selfie, dokument osobisty, ekran bez paragonu, \
nieczytelne rozmazane zdjęcie).

Zwróć:
- `image_type`: dokładnie jedną z powyższych wartości,
- `confidence`: pewność od 0.0 do 1.0,
- `reason`: krótkie (1 zdanie po polsku) uzasadnienie decyzji.
"""

classifier_agent: Agent[None, ImageClassification] = Agent(
    output_type=ImageClassification,
    instructions=CLASSIFIER_INSTRUCTIONS,
)


async def classify_image(
    image_bytes: bytes,
    *,
    media_type: str = "image/jpeg",
    model: ModelRef | None = None,
) -> AgentRunResult[ImageClassification]:
    """Classify raw image bytes in memory using `MODEL_FAST` (or an explicit override)."""
    return await classifier_agent.run(
        [
            "Sklasyfikuj to zdjęcie.",
            BinaryContent(data=image_bytes, media_type=media_type),
        ],
        model=resolve_model(model, tier="fast"),
    )
