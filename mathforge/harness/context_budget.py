from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import ceil
import os
from pathlib import Path
from typing import Any

from mathforge.context.errors import ContextBudgetExceeded


INTERN_S2_TOKENIZER_REPOSITORY = "internlm/Intern-S2-Preview-397B"
INTERN_S2_TOKENIZER_REVISION = "35eba5f142353d180472cdad2d70b09d0a383113"
INTERN_S2_TOKENIZER_JSON_SHA256 = (
    "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"
)
INTERN_S2_TOKENIZER_CONFIG_SHA256 = (
    "b5e16dc283fec919c7c43ead8f7f5cdb37417ef108b4abf224a2a832335f127a"
)
INTERN_S2_CHAT_TEMPLATE_SHA256 = (
    "ae808284ec32b532b894f4d8d9f90fcc8db9826c33265a8602ffdab15d569210"
)
TOKENIZER_DIRECTORY_ENV = "MATHFORGE_INTERN_S2_TOKENIZER_DIR"
UTF8_FALLBACK_VERSION = "multilingual-chat-estimator-v2"
_UTF8_FALLBACK_SPEC = (
    "Each message is serialized as <|im_start|>{role}\\n{content}<|im_end|>\\n; "
    "the Intern-S2 assistant thinking generation prefix is appended; "
    "ASCII non-space characters count as 0.5 token, ASCII whitespace as 0.25, "
    "CJK characters as 1.0, and other Unicode characters as 1.5."
)
UTF8_FALLBACK_SHA256 = sha256(_UTF8_FALLBACK_SPEC.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TokenCount:
    tokens: int
    counting_mode: str
    tokenizer_revision: str
    tokenizer_sha256: str

    def __post_init__(self) -> None:
        if type(self.tokens) is not int or self.tokens < 0:
            raise ValueError("token count must be a nonnegative integer")
        if self.counting_mode not in {
            "official_tokenizer",
            "multilingual_estimate",
        }:
            raise ValueError("unsupported token counting mode")


@dataclass(frozen=True)
class ContextAllocation:
    context_window_tokens: int
    prompt_tokens: int
    safety_margin_tokens: int
    max_output_tokens: int
    counting_mode: str
    tokenizer_revision: str
    tokenizer_sha256: str
    token_limit_mode: str

    def __post_init__(self) -> None:
        integer_fields = (
            self.context_window_tokens,
            self.prompt_tokens,
            self.safety_margin_tokens,
            self.max_output_tokens,
        )
        if any(type(value) is not int or value < 0 for value in integer_fields):
            raise ValueError("context allocation values must be nonnegative integers")
        if self.max_output_tokens <= 0:
            raise ValueError("model max output tokens must be positive")
        if (
            self.prompt_tokens
            + self.safety_margin_tokens
            + self.max_output_tokens
            > self.context_window_tokens
        ):
            raise ValueError("context allocation exceeds the model context window")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InternS2TokenCounter:
    """Count with the pinned tokenizer or a recorded multilingual estimate."""

    def __init__(self, tokenizer: Any | None = None) -> None:
        self._tokenizer = tokenizer if tokenizer is not None else _load_local_tokenizer()

    @property
    def exact_available(self) -> bool:
        return self._tokenizer is not None

    def count_messages(self, messages: list[dict[str, str]]) -> TokenCount:
        if self._tokenizer is not None:
            try:
                encoded = self._tokenizer.apply_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=True,
                )
                return self._official_count(_encoded_length(encoded))
            except Exception:
                pass
        return self._fallback_count(_fallback_chat_envelope(messages))

    def count_text(self, text: str) -> TokenCount:
        if self._tokenizer is not None:
            try:
                encoded = self._tokenizer.encode(
                    text,
                    add_special_tokens=False,
                )
                return self._official_count(_encoded_length(encoded))
            except Exception:
                pass
        return self._fallback_count(text)

    @staticmethod
    def _official_count(tokens: int) -> TokenCount:
        return TokenCount(
            tokens=tokens,
            counting_mode="official_tokenizer",
            tokenizer_revision=INTERN_S2_TOKENIZER_REVISION,
            tokenizer_sha256=INTERN_S2_TOKENIZER_JSON_SHA256,
        )

    @staticmethod
    def _fallback_count(text: str) -> TokenCount:
        return TokenCount(
            tokens=_estimated_multilingual_tokens(text),
            counting_mode="multilingual_estimate",
            tokenizer_revision=UTF8_FALLBACK_VERSION,
            tokenizer_sha256=UTF8_FALLBACK_SHA256,
        )


class ModelContextBudget:
    def __init__(
        self,
        *,
        context_window_tokens: int,
        safety_margin_tokens: int,
        token_counter: InternS2TokenCounter | None = None,
    ) -> None:
        if type(context_window_tokens) is not int or context_window_tokens <= 0:
            raise ValueError("context window must be a positive integer")
        if type(safety_margin_tokens) is not int or safety_margin_tokens < 0:
            raise ValueError("context safety margin must be a nonnegative integer")
        if safety_margin_tokens >= context_window_tokens:
            raise ValueError("context safety margin must be below the context window")
        self.context_window_tokens = context_window_tokens
        self.safety_margin_tokens = safety_margin_tokens
        self.token_counter = token_counter or InternS2TokenCounter()

    def allocate(
        self,
        messages: list[dict[str, str]],
        *,
        configured_max_output_tokens: int = 0,
    ) -> ContextAllocation:
        if (
            type(configured_max_output_tokens) is not int
            or configured_max_output_tokens < 0
        ):
            raise ValueError("configured max output tokens must be nonnegative")
        prompt = self.token_counter.count_messages(messages)
        available = (
            self.context_window_tokens
            - prompt.tokens
            - self.safety_margin_tokens
        )
        if available <= 0:
            raise ContextBudgetExceeded(
                "model prompt and safety margin exceed the context window"
            )
        output = (
            available
            if configured_max_output_tokens == 0
            else min(available, configured_max_output_tokens)
        )
        return ContextAllocation(
            context_window_tokens=self.context_window_tokens,
            prompt_tokens=prompt.tokens,
            safety_margin_tokens=self.safety_margin_tokens,
            max_output_tokens=output,
            counting_mode=prompt.counting_mode,
            tokenizer_revision=prompt.tokenizer_revision,
            tokenizer_sha256=prompt.tokenizer_sha256,
            token_limit_mode=(
                "dynamic_context"
                if configured_max_output_tokens == 0
                else "configured_cap"
            ),
        )

    def max_output_tokens(
        self,
        messages: list[dict[str, str]],
        *,
        configured_max_output_tokens: int = 0,
    ) -> int:
        return self.allocate(
            messages,
            configured_max_output_tokens=configured_max_output_tokens,
        ).max_output_tokens

    def count_text(self, text: str) -> TokenCount:
        return self.token_counter.count_text(text)

    def ensure_text_within_window(self, text: str) -> TokenCount:
        count = self.count_text(text)
        if count.tokens > self.context_window_tokens:
            raise ContextBudgetExceeded("public response exceeds the model context window")
        return count


def tokenizer_provenance() -> dict[str, str]:
    return {
        "repository": INTERN_S2_TOKENIZER_REPOSITORY,
        "revision": INTERN_S2_TOKENIZER_REVISION,
        "tokenizer_json_sha256": INTERN_S2_TOKENIZER_JSON_SHA256,
        "tokenizer_config_sha256": INTERN_S2_TOKENIZER_CONFIG_SHA256,
        "chat_template_sha256": INTERN_S2_CHAT_TEMPLATE_SHA256,
        "fallback_version": UTF8_FALLBACK_VERSION,
        "fallback_sha256": UTF8_FALLBACK_SHA256,
    }


def _load_local_tokenizer() -> Any | None:
    configured = os.environ.get(TOKENIZER_DIRECTORY_ENV)
    if not configured:
        return None
    directory = Path(configured)
    tokenizer_json = directory / "tokenizer.json"
    tokenizer_config = directory / "tokenizer_config.json"
    chat_template = directory / "chat_template.jinja"
    try:
        expected_files = (
            (tokenizer_json, INTERN_S2_TOKENIZER_JSON_SHA256),
            (tokenizer_config, INTERN_S2_TOKENIZER_CONFIG_SHA256),
            (chat_template, INTERN_S2_CHAT_TEMPLATE_SHA256),
        )
        if any(
            sha256(path.read_bytes()).hexdigest() != expected
            for path, expected in expected_files
        ):
            return None
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(
            directory,
            local_files_only=True,
            trust_remote_code=False,
        )
    except Exception:
        return None


def _fallback_chat_envelope(messages: list[dict[str, str]]) -> str:
    parts = [
        f"<|im_start|>{message.get('role', '')}\n"
        f"{message.get('content', '')}<|im_end|>\n"
        for message in messages
    ]
    parts.append("<|im_start|>assistant\n<think>\n")
    return "".join(parts)


def _encoded_length(encoded: Any) -> int:
    if hasattr(encoded, "shape"):
        shape = encoded.shape
        return int(shape[-1])
    if isinstance(encoded, dict) and "input_ids" in encoded:
        return _encoded_length(encoded["input_ids"])
    if isinstance(encoded, (list, tuple)):
        if encoded and isinstance(encoded[0], (list, tuple)):
            return len(encoded[0])
        return len(encoded)
    serialized = json.dumps(encoded, ensure_ascii=False)
    raise TypeError(
        "unsupported tokenizer output shape: "
        f"{type(encoded).__name__}:{len(serialized)}"
    )


def _estimated_multilingual_tokens(text: str) -> int:
    if not text:
        return 0
    estimate = 0.0
    for character in text:
        codepoint = ord(character)
        if codepoint < 128:
            estimate += 0.25 if character.isspace() else 0.5
        elif (
            0x3400 <= codepoint <= 0x4DBF
            or 0x4E00 <= codepoint <= 0x9FFF
            or 0xF900 <= codepoint <= 0xFAFF
        ):
            estimate += 1.0
        else:
            estimate += 1.5
    return max(1, ceil(estimate))
