from __future__ import annotations

from src.agents.base import BaseAgent
from src.platform.placement import PlacementConfig, load_placement, save_placement


class PlacementAgent(BaseAgent):
    """Manages company-based drug placement on the platform."""

    name = "placement"

    def describe(self) -> str:
        return "Configures which company drugs are prioritized in AI answers."

    def get(self) -> PlacementConfig:
        return load_placement(self.client_id)

    def apply_company(self, company_name: str, enabled: bool = True) -> PlacementConfig:
        from src.agents.research_agent import ResearchAgent

        _, plc = ResearchAgent(self.client_id).discover_and_apply_placement(
            company_name, enabled=enabled, refresh=True
        )
        return plc

    def save(self, config: PlacementConfig) -> PlacementConfig:
        save_placement(config)
        return config
