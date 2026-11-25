"""User profiler agent — synthesizes buying habits and applies manual chat preferences.

Uses `MODEL_REASONING` (`src/core/models_registry.py`) and preserves explicit user rules
across periodic profile refreshes (Section 3C of `docs/PHASE_1_SPEC.md`).
"""

from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult

from src.core.models_registry import ModelRef, resolve_model
from src.domain.schemas import UserProfileOutput

PROFILER_INSTRUCTIONS = """\
Jesteś agentem profilującym nawyki zakupowe użytkownika w aplikacji CartPilot.
Tworzysz i aktualizujesz zwięzły profil zakupowy (`UserProfileOutput`).

ZASADY:
1. `profile_markdown`: 4–8 zwięzłych zdań po polsku opisujących nawyki zakupowe użytkownika \
(ulubione sklepy, typowe kategorie, częste produkty, preferencje dietetyczne / budżetowe).
2. `preferred_stores` i `avoided_stores`: nazwy sieci w formacie `snake_case` bez polskich znaków \
(np. `"lidl"`, `"aldi"`, `"biedronka"`, `"delikatesy_centrum"`).
3. `custom_rules`: zwięzłe reguły użytkownika po polsku (np. `"ograniczamy słodycze"`, \
`"kupujemy mleko bez laktozy"`).
4. ZACHOWYWANIE REGUŁ UŻYTKOWNIKA:
   - Podczas okresowej syntezy z historii paragonów NIGDY nie usuwaj dotychczasowych \
`preferred_stores`, `avoided_stores` ani `custom_rules` dodanych ręcznie przez użytkownika, \
chyba że użytkownik wprost poprosił o ich zmianę.
   - Podczas ręcznej korekty z wiadomości czatowej wprowadź dokładnie tę zmianę, o którą prosi \
użytkownik, zachowując pozostałe dotychczasowe preferencje.
"""

profiler_agent: Agent[None, UserProfileOutput] = Agent(
    output_type=UserProfileOutput,
    instructions=PROFILER_INSTRUCTIONS,
)


async def synthesize_profile(
    stats_summary: str,
    current_profile: UserProfileOutput | None = None,
    *,
    model: ModelRef | None = None,
) -> AgentRunResult[UserProfileOutput]:
    """Synthesize or refresh a user's shopping profile from aggregated purchase statistics."""
    current_block = (
        current_profile.model_dump_json(indent=2)
        if current_profile is not None
        else "Brak dotychczasowego profilu (pierwsza synteza)."
    )
    prompt = (
        "Zaktualizuj profil zakupowy użytkownika na podstawie poniższych zagregowanych statystyk "
        "z historii paragonów.\n\n"
        f"DOTYCHCZASOWY PROFIL:\n{current_block}\n\n"
        f"STATYSTYKI ZAKUPÓW:\n{stats_summary}"
    )
    return await profiler_agent.run(
        prompt,
        model=resolve_model(model, tier="reasoning"),
    )


async def update_profile_from_message(
    user_message: str,
    current_profile: UserProfileOutput,
    *,
    model: ModelRef | None = None,
) -> AgentRunResult[UserProfileOutput]:
    """Apply a natural-language preference update from Telegram chat to the user's profile."""
    prompt = (
        "Użytkownik wysłał wiadomość na czacie z korektą swoich preferencji zakupowych. "
        "Zaktualizuj jego profil, zachowując dotychczasowe niezmienione ustawienia.\n\n"
        f"DOTYCHCZASOWY PROFIL:\n{current_profile.model_dump_json(indent=2)}\n\n"
        f"WIADOMOŚĆ UŻYTKOWNIKA:\n{user_message}"
    )
    return await profiler_agent.run(
        prompt,
        model=resolve_model(model, tier="reasoning"),
    )
