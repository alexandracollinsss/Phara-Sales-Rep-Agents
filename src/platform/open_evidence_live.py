from __future__ import annotations

"""
Stub adapter for production OpenEvidence API access.

When OpenEvidence (or a partner) provides API credentials, implement:
  - authenticate()
  - create_visit() / list_visits()
  - ask(question, visit_id) -> structured response + citations
  - export_audit_transcript(visit_id)

Until then, use OpenEvidenceClone (local Ollama + corpus RAG).
"""

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class LiveConfig:
    base_url: str
    api_key: str | None
    enabled: bool


class OpenEvidenceLive:
    """Placeholder for live OpenEvidence integration."""

    def __init__(self, config: LiveConfig | None = None):
        self.config = config or LiveConfig(
            base_url=os.environ.get("OPENEVIDENCE_API_URL", "https://api.openevidence.com"),
            api_key=os.environ.get("OPENEVIDENCE_API_KEY"),
            enabled=os.environ.get("OPENEVIDENCE_API_ENABLED", "").lower() == "true",
        )

    @property
    def is_available(self) -> bool:
        return bool(self.config.enabled and self.config.api_key)

    def ask(self, question: str, visit_id: str | None = None) -> dict[str, Any]:
        if not self.is_available:
            raise NotImplementedError(
                "OpenEvidence live API is not configured. "
                "Set OPENEVIDENCE_API_ENABLED=true and OPENEVIDENCE_API_KEY, "
                "or use the built-in platform via OpenEvidenceClone."
            )
        # Future: httpx POST to partner endpoint
        raise NotImplementedError("Live OpenEvidence ask() not yet implemented.")

    def create_visit(self, title: str | None = None) -> str:
        if not self.is_available:
            raise NotImplementedError("OpenEvidence live API is not configured.")
        raise NotImplementedError("Live OpenEvidence create_visit() not yet implemented.")
