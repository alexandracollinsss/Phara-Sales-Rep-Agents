from __future__ import annotations

from collections.abc import Iterator

from src.agents.base import BaseAgent
from src.platform.open_evidence_clone import AskResult, OpenEvidenceClone
from src.platform.placement import PlacementConfig, load_placement


class PlatformAgent(BaseAgent):
    """Physician Q&A platform with RAG and citations."""

    name = "platform"

    def describe(self) -> str:
        return "Answers clinical questions like Open Evidence (Ollama + corpus RAG)."

    def _clone(self, placement: PlacementConfig | None = None) -> OpenEvidenceClone:
        plc = placement or load_placement(self.client_id)
        return OpenEvidenceClone(self.ollama, placement=plc, client_id=self.client_id)

    def ask(self, question: str, placement: PlacementConfig | None = None) -> AskResult:
        return self._clone(placement).ask(question)

    def ask_stream(
        self, question: str, placement: PlacementConfig | None = None
    ) -> tuple[Iterator[str], list[dict]]:
        return self._clone(placement).ask_stream(question)
