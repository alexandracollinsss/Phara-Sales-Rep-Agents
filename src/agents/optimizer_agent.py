from __future__ import annotations

from src.agents.base import BaseAgent
from src.audit.scorer import MentionScore
from src.platform.placement import load_placement

REP_SYSTEM = """You are a digital pharmaceutical sales representative for {company_name}.
Brands: {brands}
Rules: evidence-based, fair balance, cite sources. No patient-specific dosing."""


class OptimizerAgent(BaseAgent):
    """Suggests content and placement improvements from audit gaps."""

    name = "optimizer"

    def describe(self) -> str:
        return "Proposes corpus and placement optimizations from audit results."

    def _system(self) -> str:
        plc = load_placement(self.client_id)
        brands = ", ".join(d.brand for d in plc.ensure_drugs()) or "N/A"
        return REP_SYSTEM.format(company_name=plc.company_name, brands=brands)

    def content_actions(self, scores: list[MentionScore]) -> list[str]:
        gaps = []
        for s in scores:
            tb = s.company_mentions
            tc = s.competitor_mentions_total
            if s.favorability in ("absent", "unfavorable") or tb < tc:
                gaps.append(f"[{s.prompt_id}] {s.favorability} brand={tb} comp={tc}")
        prompt = (
            "List 5 content optimization actions (trial citations, corpus chunks) "
            "for our brands. One bullet per line.\n\n"
            + "\n".join(gaps or ["No major gaps."])
        )
        raw = self.ollama.chat(
            [{"role": "system", "content": self._system()}, {"role": "user", "content": prompt}]
        )
        return [ln.lstrip("-• ").strip() for ln in raw.splitlines() if ln.strip()]

    def placement_targets(self, optimizations: list[str]) -> list[str]:
        prompt = (
            "List 5 placement targets (RAG stores, monographs, guideline mirrors). "
            "One bullet per line.\n\n" + "\n".join(f"- {o}" for o in optimizations[:5])
        )
        raw = self.ollama.chat(
            [{"role": "system", "content": self._system()}, {"role": "user", "content": prompt}]
        )
        return [ln.lstrip("-• ").strip() for ln in raw.splitlines() if ln.strip()]
