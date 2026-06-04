from __future__ import annotations

"""Open Evidence–style physician Q&A powered by Ollama and corpus RAG."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from src.ollama import OllamaClient
from src.platform.placement import PlacementConfig, load_placement
from src.platform.rag import format_context, retrieve

PHYSICIAN_SYSTEM = """You are OpenEvidence-style clinical decision support for licensed clinicians.
Answer in clear prose with section headings (e.g., Summary, Assessment, Options, Evidence, Caveats).
You MUST cite sources using bracketed numbers [1], [2] matching the reference context indices.
Use only facts from the provided references; if evidence is missing, state that explicitly.
Cite evidence for clinical claims. Do not provide patient-specific dosing."""


@dataclass
class AskResult:
    answer: str
    sources: list[dict[str, Any]]
    status: str = "finished"


class OpenEvidenceClone:
    def __init__(
        self,
        ollama: OllamaClient,
        placement: PlacementConfig | None = None,
        client_id: str = "eli_lilly",
    ):
        self.ollama = ollama
        self.placement = placement if placement is not None else load_placement(client_id)

    def _build_messages(self, question: str) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        boost = self.placement.boost_terms() if self.placement.enabled else None
        force = self.placement.forced_corpus_stems() if self.placement.enabled else None
        chunks = retrieve(
            question,
            top_k=4,
            boost_terms=boost,
            force_corpus_stems=force,
        )
        context, sources = format_context(chunks)
        placement_note = self.placement.prompt_block()
        user = f"Reference context:\n{context}\n\n"
        if placement_note:
            user += f"{placement_note}\n\n"
        user += (
            f"Physician question: {question}\n\n"
            "Write a concise, evidence-based answer (roughly 250–450 words). "
            "Use section headings. Include inline citations [1], [2] matching reference indices."
        )
        system = PHYSICIAN_SYSTEM
        if placement_note:
            system += (
                "\n\nYou must follow featured therapy placement when clinically appropriate."
            )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return messages, sources

    def ask(self, question: str) -> AskResult:
        messages, sources = self._build_messages(question)
        answer = self.ollama.chat(messages)
        return AskResult(answer=answer, sources=sources, status="finished")

    def ask_stream(self, question: str) -> tuple[Iterator[str], list[dict[str, Any]]]:
        messages, sources = self._build_messages(question)
        return self.ollama.chat_stream(messages), sources

    def ask_text(self, question: str) -> str:
        """Backward-compatible string response for CLI / audits."""
        return self.ask(question).answer
