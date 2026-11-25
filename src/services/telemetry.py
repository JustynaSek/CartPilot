"""LLM call telemetry wrapper — records tokens, latency, status, and cost in `agent_runs`."""

import time
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Literal

from pydantic_ai.agent import AgentRunResult

from src.core.models_registry import ModelRef
from src.db.repositories.agent_run_repo import AgentRunRepository

_SIX_PLACES = Decimal("0.000001")
_ONE_MILLION = Decimal("1000000")

# Approximate USD rates per 1M tokens (input_rate, output_rate), matched by substring.
# Unknown / local / test models safely fall back to 0.000000 USD.
_MODEL_PRICING_PER_1M: tuple[tuple[str, tuple[Decimal, Decimal]], ...] = (
    ("flash-lite", (Decimal("0.10"), Decimal("0.40"))),
    ("flash", (Decimal("0.30"), Decimal("2.50"))),
    ("gemini-4", (Decimal("1.25"), Decimal("10.00"))),
    ("gemini-2.5-pro", (Decimal("1.25"), Decimal("10.00"))),
    ("claude-sonnet", (Decimal("3.00"), Decimal("15.00"))),
    ("claude-haiku", (Decimal("0.80"), Decimal("4.00"))),
)


def describe_model(model: ModelRef) -> str:
    """Return a compact, printable model identifier for `agent_runs.model_name`."""
    if isinstance(model, str):
        return model
    model_name = getattr(model, "model_name", None)
    if isinstance(model_name, str) and model_name:
        return model_name
    return type(model).__name__


def estimate_cost_usd(model_name: str, tokens_in: int, tokens_out: int) -> Decimal:
    """Estimate call cost in USD with 6 decimal places (safe 0.000000 fallback)."""
    lowered = model_name.lower()
    for needle, (in_rate, out_rate) in _MODEL_PRICING_PER_1M:
        if needle in lowered:
            cost = (Decimal(tokens_in) * in_rate + Decimal(tokens_out) * out_rate) / _ONE_MILLION
            return cost.quantize(_SIX_PLACES)
    return Decimal("0.000000")


async def run_tracked_agent[T](
    *,
    repo: AgentRunRepository,
    user_id: uuid.UUID | None,
    trigger_type: str,
    agent_name: str,
    model: ModelRef,
    call: Callable[[], Awaitable[AgentRunResult[T]]],
    status_on_success: Literal["success", "retry"] = "success",
) -> AgentRunResult[T]:
    """Execute a PydanticAI agent call and log its telemetry to `agent_runs`.

    On failure, records an `error` row with `error_message` and re-raises the exception.
    """
    model_label = describe_model(model)
    started = time.perf_counter()
    try:
        result = await call()
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        await repo.create(
            user_id=user_id,
            trigger_type=trigger_type,
            agent_name=agent_name,
            model_name=model_label,
            tokens_in=0,
            tokens_out=0,
            estimated_cost_usd=Decimal("0.000000"),
            latency_ms=latency_ms,
            status="error",
            error_message=str(exc)[:1000],
        )
        raise

    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = result.usage
    tokens_in = int(usage.input_tokens or 0)
    tokens_out = int(usage.output_tokens or 0)
    cost = estimate_cost_usd(model_label, tokens_in, tokens_out)

    await repo.create(
        user_id=user_id,
        trigger_type=trigger_type,
        agent_name=agent_name,
        model_name=model_label,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        estimated_cost_usd=cost,
        latency_ms=latency_ms,
        status=status_on_success,
    )
    return result
