from __future__ import annotations

from src.agents.base import BaseAgent
from src.platform.placement import PlacementConfig, save_placement
from src.research.company_drugs import CompanyProfile, discover_company_drugs


class ResearchAgent(BaseAgent):
    """Discovers a company's drugs via openFDA + curated data."""

    name = "research"

    def describe(self) -> str:
        return "Looks up GLP-1 therapies for a pharma company (openFDA API)."

    def discover(
        self,
        company_name: str,
        therapeutic_focus: str = "glp1",
        refresh: bool = False,
    ) -> CompanyProfile:
        return discover_company_drugs(
            company_name,
            therapeutic_focus=therapeutic_focus,
            use_cache=not refresh,
        )

    def discover_and_apply_placement(
        self,
        company_name: str,
        enabled: bool = True,
        *,
        refresh: bool = False,
    ) -> tuple[CompanyProfile, PlacementConfig]:
        profile = self.discover(company_name, refresh=refresh)
        if not profile.drugs:
            raise ValueError(
                f"No GLP-1 therapies found for '{company_name}'. "
                "Try a major pharma company name (e.g. Novo Nordisk, Eli Lilly) or check spelling."
            )
        plc = PlacementConfig(
            client_id=self.client_id,
            company_name=profile.company_name,
            company_key=profile.company_key,
            drugs=profile.drugs,
            enabled=enabled,
        )
        save_placement(plc)
        return profile, plc
