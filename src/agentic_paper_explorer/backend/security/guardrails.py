"""Lightweight, in-process guardrails for the query and retrieved context.

Responsibility split (see docs/phases/phase-8-security-guardrails.md):
- The LiteLLM proxy owns model-facing PII masking (Presidio, pre_call and post_call), so every
  prompt and answer crossing the gateway is covered in one place.
- This module owns the checks that must happen *before* the gateway: rejecting oversized or
  obviously adversarial queries before retrieval runs, redacting PII before the query reaches
  the Redis cache key, embeddings, or logs, and dropping retrieved chunks that carry injected
  instructions (indirect prompt injection).

Detection here is deliberately heuristic (regex, no ML models): cheap, deterministic, and easy to
test. It catches common, low-effort attacks, not determined adversaries; the hardened system
prompt and the proxy-side guardrails are the other layers.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from agentic_paper_explorer.backend.retrieval.service import RetrievedChunk

logger = logging.getLogger(__name__)


INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    # ignore instructions pattern
    "ignore_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|above|earlier|all|your)"
        r"\b.{0,20}\b(instructions?|prompts?|rules|directions|guidelines)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    # reveal system prompt pattern
    "reveal_system_prompt": re.compile(
        r"\b(reveal|print|show|repeat|output|leak)\b.{0,30}\b(system|hidden|initial)\s+"
        r"(prompt|instructions?|message)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    # role override pattern
    "role_override": re.compile(
        r"\b(you are now|from now on,? you are|act as|pretend (to be|you are))\b.{0,40}"
        r"\b(DAN|unrestricted|unfiltered|jailbroken|evil|without (any )?(rules|restrictions|"
        r"filters))\b",
        re.IGNORECASE | re.DOTALL,
    ),
    # known jailbreak pattern
    "known_jailbreak": re.compile(
        r"\b(do anything now|developer mode (enabled|on)|jailbreak mode)\b", re.IGNORECASE
    ),
    # Chat-template tokens only: plain "Assistant:" lines appear in legitimate paper transcripts.
    "fake_role_marker": re.compile(r"<\|im_start\|>|<\|im_end\|>|\[/?INST\]", re.IGNORECASE),
}

# PII patterns for lightweight, in-process detection and redaction.
PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL_ADDRESS": re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b"),
    "CREDIT_CARD": re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,4}\b"),
    "PHONE_NUMBER": re.compile(
        r"(\+\d{1,3}[\s.-]?\(?\d{1,4}\)?([\s.-]?\d{2,4}){2,3}"
        r"|\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4})\b"
    ),
    "IP_ADDRESS": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
    ),
}


@dataclass(slots=True, frozen=True)
class QueryCheck:
    """Outcome of screening one user query."""

    allowed: bool
    sanitized_query: str
    reason: str | None = None
    redacted_entities: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ContextCheck:
    """Retrieved chunks that passed screening, plus the reasons for any that were dropped."""

    chunks: list[RetrievedChunk]
    dropped_reasons: list[str] = field(default_factory=list)


def detect_injection(text: str | None) -> str | None:
    """
    Return the name of the first matching injection pattern, or None if the text looks clean.
    args:
        text: The text to check for injection patterns. None or empty text is treated as clean.

    Returns:
        The name of the first matching injection pattern, or None if the text looks clean.
    """

    if not text:
        return None
    for name, pattern in INJECTION_PATTERNS.items():
        if pattern.search(text):
            return name
    return None


def redact_pii(text: str) -> tuple[str, tuple[str, ...]]:
    """
    Replace PII matches with `<ENTITY>` placeholders; return the text and entity types found.

    args:
        text: The text to check for PII patterns.

    Returns:
        A tuple containing the sanitized text and a tuple of the entity types found.
    """
    found: list[str] = []
    for entity, pattern in PII_PATTERNS.items():
        text, count = pattern.subn(f"<{entity}>", text)
        if count:
            found.append(entity)
    return text, tuple(found)


class GuardrailService:
    """Screen user queries and retrieved context before they reach the generation prompt."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_query_chars: int = 1000,
        drop_suspicious_chunks: bool = True,
    ) -> None:
        self._enabled = enabled
        self._max_query_chars = max_query_chars
        self._drop_suspicious_chunks = drop_suspicious_chunks

    def check_query(self, query: str) -> QueryCheck:
        """
        Reject oversized or adversarial queries and redact PII from the rest.

        args:
            query: The user query to check.

        Returns:
            A QueryCheck object indicating whether the query is allowed, the sanitized query, and any redacted entities.
        """
        # check query length
        if not self._enabled:
            return QueryCheck(allowed=True, sanitized_query=query)
        # Blank queries get their own reason so they are distinguishable from oversized ones in metrics.
        if not query.strip():
            logger.warning("Guardrail blocked query reason=empty")
            return QueryCheck(allowed=False, sanitized_query="", reason="empty")
        if len(query) > self._max_query_chars:
            logger.warning("Guardrail blocked query reason=length chars=%d", len(query))
            return QueryCheck(allowed=False, sanitized_query="", reason="length")

        # check for injection patterns
        pattern_name = detect_injection(query)
        if pattern_name:
            # Log the pattern name only: persisting the raw payload would store the attack.
            logger.warning("Guardrail blocked query reason=injection pattern=%s", pattern_name)
            return QueryCheck(allowed=False, sanitized_query="", reason="injection")

        # redact PII from the query
        sanitized, entities = redact_pii(query)
        if entities:
            logger.info("Guardrail redacted PII entities=%s", ",".join(entities))
        return QueryCheck(allowed=True, sanitized_query=sanitized, redacted_entities=entities)

    def check_context(
        self,
        chunks: list[RetrievedChunk],
    ) -> ContextCheck:
        """
        Drop retrieved chunks carrying injected instructions (indirect prompt injection).

        args:
            chunks: A list of RetrievedChunk objects to check.

        Returns:
            A ContextCheck object indicating which chunks are kept and which are dropped, along with the reasons for dropping.
        """
        if not self._enabled or not self._drop_suspicious_chunks:
            return ContextCheck(chunks=list(chunks))
        kept: list[RetrievedChunk] = []
        dropped: list[str] = []
        for chunk in chunks:
            pattern_name = detect_injection(chunk.text)
            if pattern_name is None:
                kept.append(chunk)
                continue
            dropped.append(pattern_name)
            logger.warning(
                "Guardrail dropped chunk paper_id=%s pattern=%s", chunk.paper_id, pattern_name
            )
        return ContextCheck(chunks=kept, dropped_reasons=dropped)
