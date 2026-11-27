"""The one seam between this project and a language model.

`LLMClient` is a small interface: send a system prompt, a user message and a JSON schema, get back parsed JSON plus
token counts. `AnthropicClient` implements it with the official SDK; `FakeLLMClient` implements it for tests, so no
test ever touches the network.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger(__name__)


class LLMError(Exception):
    """The model call failed or returned something unusable. Callers record it and move on."""


@dataclass(frozen=True)
class LLMResult:
    data: dict[str, Any]
    input_tokens: int
    output_tokens: int
    model: str


class LLMClient(Protocol):
    model: str

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4096) -> LLMResult:
        """Return JSON that matches `schema`. Raise LLMError on any failure."""
        ...


class AnthropicClient:
    """Structured-output calls through the Anthropic SDK (`output_config.format` = JSON schema).

    The SDK retries 408/409/429/5xx and connection errors with exponential backoff; `max_retries` and `timeout`
    are set here. Sampling parameters such as temperature are not sent: current models reject non-default values,
    and the fixed schema plus the instructions keep the output stable.
    """

    def __init__(self, api_key: str, model: str, timeout: float = 60.0, max_retries: int = 4) -> None:
        import anthropic  # imported here so the dashboard and the tests never need the package

        self._anthropic = anthropic
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=max_retries)

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4096) -> LLMResult:
        a = self._anthropic
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except (a.RateLimitError, a.APIStatusError, a.APIConnectionError, a.APITimeoutError) as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        if resp.stop_reason in ("refusal", "max_tokens"):
            raise LLMError(f"stopped early: {resp.stop_reason}")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("response was not valid JSON") from exc
        if not isinstance(data, dict):
            raise LLMError("response JSON was not an object")
        return LLMResult(data, resp.usage.input_tokens, resp.usage.output_tokens, self.model)


@dataclass
class FakeLLMClient:
    """Test double. Give it a list of responses (dicts, or exceptions to raise) or a function of the user message.

    Every call is recorded in `calls` as (system, user, schema)."""

    responses: Iterable[dict[str, Any] | Exception] | Callable[[str], dict[str, Any]] = ()
    model: str = "fake-model"
    input_tokens: int = 100
    output_tokens: int = 50
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._queue = None if callable(self.responses) else list(self.responses)

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4096) -> LLMResult:
        self.calls.append((system, user, schema))
        if self._queue is None:
            item: Any = self.responses(user)  # type: ignore[operator]
        elif self._queue:
            item = self._queue.pop(0)
        else:
            raise LLMError("fake client has no responses left")
        if isinstance(item, Exception):
            raise item
        return LLMResult(item, self.input_tokens, self.output_tokens, self.model)


def get_client(settings=None) -> LLMClient | None:
    """The real client when a key is configured, else None (the layer is off)."""
    from app.config import load_settings

    settings = settings or load_settings()
    if not settings.enabled:
        return None
    return AnthropicClient(settings.api_key, settings.model)
