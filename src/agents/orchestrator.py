from __future__ import annotations

from dataclasses import dataclass

from src.agents.audit_agent import AuditAgent
from src.agents.optimizer_agent import OptimizerAgent
from src.agents.placement_agent import PlacementAgent
from src.agents.platform_agent import PlatformAgent
from src.agents.research_agent import ResearchAgent
from src.audit.scorer import MentionScore
from src.platform.open_evidence_clone import AskResult
from src.platform.placement import PlacementConfig
from src.research.company_drugs import CompanyProfile


@dataclass
class RepBriefing:
    summary: str
    audit_highlights: list[str]
    optimization_actions: list[str]
    placement_actions: list[str]
    risks: list[str]
    run_id: str | None = None


class SalesRepOrchestrator:
    """
    Coordinates specialized agents:
    Research → Placement → Platform → Audit → Optimizer
    """

    def __init__(self, client_id: str = "eli_lilly"):
        self.client_id = client_id
        self.research = ResearchAgent(client_id)
        self.placement = PlacementAgent(client_id)
        self.platform = PlatformAgent(client_id)
        self.audit = AuditAgent(client_id)
        self.optimizer = OptimizerAgent(client_id)

    def setup_company(self, company_name: str) -> tuple[CompanyProfile, PlacementConfig]:
        return self.research.discover_and_apply_placement(company_name)

    def ask(self, question: str) -> AskResult:
        return self.platform.ask(question)

    def audit_and_save(self) -> tuple[list[MentionScore], str]:
        scores, run_id = self.audit.run(save=True)
        assert run_id
        return scores, run_id

    def briefing_from_scores(
        self, scores: list[MentionScore], run_id: str | None = None
    ) -> RepBriefing:
        favorable = sum(1 for s in scores if s.favorability == "favorable")
        absent = sum(1 for s in scores if s.favorability == "absent")
        opts = self.optimizer.content_actions(scores)
        places = self.optimizer.placement_targets(opts[:5])
        plc = self.placement.get()
        summary_prompt = (
            f"Write a 3-sentence executive summary for {plc.company_name} "
            f"after {len(scores)} physician prompt audits. "
            f"Favorable: {favorable}, absent: {absent}."
        )
        summary = self.optimizer.ollama.chat(
            [
                {"role": "system", "content": self.optimizer._system()},
                {"role": "user", "content": summary_prompt},
            ]
        )
        risks = []
        if absent > len(scores) // 2:
            risks.append("High absent rate—increase placement or enrich corpus for company drugs.")
        risks.append("Review high absent-rate prompts and expand corpus coverage for featured drugs.")
        return RepBriefing(
            summary=summary,
            audit_highlights=[
                f"{s.prompt_id}: {s.favorability} (brands {s.brand_mentions})"
                for s in scores
            ],
            optimization_actions=opts[:8],
            placement_actions=places[:8],
            risks=risks,
            run_id=run_id,
        )

    def run_full_cycle(self, save_audit: bool = True) -> RepBriefing:
        scores, run_id = self.audit.run(save=save_audit)
        return self.briefing_from_scores(scores, run_id=run_id)

    def agent_roster(self) -> list[dict[str, str]]:
        return [
            {"id": a.name, "description": a.describe()}
            for a in (
                self.research,
                self.placement,
                self.platform,
                self.audit,
                self.optimizer,
            )
        ]
