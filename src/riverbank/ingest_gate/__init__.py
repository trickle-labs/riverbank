from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class IngestGateConfig:
    """Editorial policy configuration for fragment acceptance.

    These values can be overridden per compiler profile via ``editorial_policy``
    in the profile YAML.
    """

    min_heading_depth: int = 0
    min_fragment_length: int = 50
    max_fragment_length: int = 8000
    allowed_languages: list[str] = field(default_factory=lambda: ["en"])
    require_heading: bool = False


@dataclass
class IngestGateResult:
    """Result of an editorial policy check."""

    accepted: bool
    reason: Optional[str] = None


class IngestGate:
    """Editorial policy gate: decides whether a fragment should be extracted.

    Checks applied (in order):

    1. Fragment length — must be within ``[min_fragment_length, max_fragment_length]``
    2. Heading requirement — if ``require_heading`` is True, fragment must have a heading
    3. Heading depth — ``heading_depth`` must be ≥ ``min_heading_depth``
    4. Language — if ``langdetect`` is available, detected language must be in
       ``allowed_languages`` (check is skipped when the library is absent or
       detection fails)
    """

    def check(self, fragment: object, config: IngestGateConfig) -> IngestGateResult:
        """Return an ``IngestGateResult`` for the given fragment and policy."""
        text: str = getattr(fragment, "text", "")
        heading_depth: int = getattr(fragment, "heading_depth", 0)
        heading_path: list = getattr(fragment, "heading_path", [])

        length = len(text.strip())

        if length < config.min_fragment_length:
            return IngestGateResult(
                accepted=False,
                reason=f"fragment too short: {length} < {config.min_fragment_length} chars",
            )

        if length > config.max_fragment_length:
            return IngestGateResult(
                accepted=False,
                reason=f"fragment too long: {length} > {config.max_fragment_length} chars",
            )

        if config.require_heading and not heading_path:
            return IngestGateResult(accepted=False, reason="fragment has no heading")

        if heading_depth < config.min_heading_depth:
            return IngestGateResult(
                accepted=False,
                reason=(
                    f"heading depth {heading_depth} < minimum {config.min_heading_depth}"
                ),
            )

        if config.allowed_languages:
            lang = _detect_language(text)
            if lang is not None and lang not in config.allowed_languages:
                return IngestGateResult(
                    accepted=False,
                    reason=(
                        f"language '{lang}' not in allowed languages {config.allowed_languages}"
                    ),
                )

        return IngestGateResult(accepted=True)


def _detect_language(text: str) -> Optional[str]:
    """Detect language using ``langdetect`` if available; return None otherwise."""
    try:
        from langdetect import detect  # noqa: PLC0415

        return detect(text)
    except ImportError:
        # langdetect not installed — language check is skipped
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("Language detection failed: %s", exc)
        return None
