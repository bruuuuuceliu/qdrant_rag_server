"""Chat-history compression policies.

``CondenseV1Policy`` is the deterministic v1 policy (requirements FR-2.5, design
§3.3): a pure function of the input span so the same span plus the same policy
always produces the same condensed context (FR-2.6). Model-backed summarization
is a future ``ModelSummaryPolicy`` behind the same protocol.
"""

from __future__ import annotations

import re
from typing import Protocol

from memory_service.models import (
    CompressionSpan,
    CondensedOutput,
    MemoryMessage,
)

_MAX_SENTENCE_CHARS = 240

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


class CompressionPolicy(Protocol):
    """Compression seam: a span in, a condensed context out."""

    policy_name: str

    async def compress(self, span: CompressionSpan) -> CondensedOutput:
        ...


class CondenseV1Policy:
    """Deterministic sentence-boundary condensation for ``condense-v1``."""

    policy_name = "condense-v1"

    async def compress(self, span: CompressionSpan) -> CondensedOutput:
        messages = sorted(span.messages, key=lambda message: message[0])
        keep_recent = max(0, span.keep_recent)
        if keep_recent > 0 and len(messages) > keep_recent:
            compressible = messages[:-keep_recent]
            recent = messages[-keep_recent:]
        else:
            compressible = messages[: len(messages) - keep_recent] if keep_recent else list(messages)
            recent = messages[-keep_recent:] if keep_recent else []
        lines = [
            _condense_line(sequence_number, role, content)
            for sequence_number, role, content in compressible
        ]
        condensed_context = "\n".join(lines)
        covered_from = compressible[0][0] if compressible else 0
        covered_to = compressible[-1][0] if compressible else 0
        return CondensedOutput(
            condensed_context=condensed_context,
            memory_id="",
            covered_from=covered_from,
            covered_to=covered_to,
            policy=self.policy_name,
            recent_messages=[
                MemoryMessage(
                    message_id="",
                    session_id=span.session_id,
                    owner_user_id="",
                    agent_id="",
                    role=role,
                    sequence_number=sequence_number,
                    content=content,
                    created_at="",
                )
                for sequence_number, role, content in recent
            ],
        )


def _condense_line(sequence_number: int, role: str, content: str) -> str:
    condensed = _condense_text(content)
    return f"[{sequence_number}] {role}: {condensed}"


def _condense_text(text: str) -> str:
    sentences = _split_sentences(text)
    if not sentences:
        return ""
    first = sentences[0][:_MAX_SENTENCE_CHARS]
    if len(sentences) == 1:
        return first
    last = sentences[-1][:_MAX_SENTENCE_CHARS]
    return f"{first}… {last}"


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(text.strip())
    return [part.strip() for part in parts if part.strip()]
