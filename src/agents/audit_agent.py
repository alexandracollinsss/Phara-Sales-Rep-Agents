from __future__ import annotations

from src.agents.base import BaseAgent
from src.agents.platform_agent import PlatformAgent
from src.audit.scorer import MentionScore, score_answer
from src.audit.store import save_run
from src.config import load_audit_battery
from src.platform.placement import load_placement


class AuditAgent(BaseAgent):
    """Runs prompt battery against the platform and scores brand visibility."""

    name = "audit"

    def describe(self) -> str:
        return "Measures how often company drugs appear vs competitors in AI answers."

    def run(self, save: bool = True) -> tuple[list[MentionScore], str | None]:
        platform = PlatformAgent(self.client_id)
        plc = load_placement(self.client_id)
        battery = load_audit_battery()
        results: list[MentionScore] = []

        for item in battery:
            answer = platform.ask(item["text"], placement=plc).answer
            results.append(
                score_answer(
                    item["id"],
                    item["text"],
                    answer,
                    self.client,
                    extra_brands=plc.audit_brands(),
                )
            )

        run_id = save_run(self.client_id, results) if save else None
        return results, run_id
