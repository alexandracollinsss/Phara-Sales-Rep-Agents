from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from src.config import CONFIG_DIR, ROOT
from src.research.company_drugs import CompanyProfile, DiscoveredDrug, discover_company_drugs

PLACEMENT_DIR = ROOT / "data" / "placement"

# Corpus files to boost when Lilly GLP-1 drugs are featured
CORPUS_BY_COMPANY_KEY: dict[str, list[str]] = {
    "eli lilly": ["surpass", "surmount", "glp1_basics"],
    "novo nordisk": ["select", "surmount", "glp1_basics"],
    "lilly": ["surpass", "surmount", "glp1_basics"],
}


@dataclass
class PlacementConfig:
    """Company-based placement — user only enters pharma company name."""

    client_id: str = "eli_lilly"
    company_name: str = ""
    company_key: str = ""
    drugs: list[DiscoveredDrug] | None = None
    enabled: bool = True
    therapeutic_focus: str = "glp1"

    def ensure_drugs(self) -> list[DiscoveredDrug]:
        if self.drugs:
            return self.drugs
        if not (self.company_name or "").strip():
            return []
        profile = discover_company_drugs(self.company_name, self.therapeutic_focus)
        self.drugs = profile.drugs
        self.company_key = profile.company_key
        return self.drugs

    def ranked_drugs(self) -> list[tuple[int, DiscoveredDrug]]:
        drugs = self.ensure_drugs()
        return [(i + 1, d) for i, d in enumerate(drugs)]

    def boost_terms(self) -> list[tuple[str, float]]:
        if not self.enabled:
            return []
        weights = [4.0, 3.0, 2.5, 2.0, 1.5, 1.2]
        terms: list[tuple[str, float]] = []
        for i, (_, drug) in enumerate(self.ranked_drugs()):
            w = weights[i] if i < len(weights) else 1.0
            for t in drug.brand_terms():
                terms.append((t, w))
        key = self.company_key
        if key in CORPUS_BY_COMPANY_KEY or "lilly" in key:
            for stem in CORPUS_BY_COMPANY_KEY.get(key, CORPUS_BY_COMPANY_KEY.get("eli lilly", [])):
                terms.append((stem, 2.0))
        return terms

    def forced_corpus_stems(self) -> list[str]:
        if not self.enabled:
            return []
        key = self.company_key
        stems = CORPUS_BY_COMPANY_KEY.get(key, [])
        if not stems and "lilly" in key:
            stems = CORPUS_BY_COMPANY_KEY["eli lilly"]
        if not stems and "novo" in key:
            stems = CORPUS_BY_COMPANY_KEY["novo nordisk"]
        return stems or ["glp1_basics"]

    def prompt_block(self) -> str:
        if not self.enabled:
            return ""
        drugs = self.ensure_drugs()
        if not drugs:
            return ""
        lines = [
            f"Featured therapies for {self.company_name} (platform placement — when clinically relevant):"
        ]
        for rank, d in self.ranked_drugs()[:6]:
            gen = f" ({d.generic})" if d.generic else ""
            lines.append(f"  Priority {rank}: {d.brand}{gen}")
        lines.append(
            f"When the clinical question relates to this therapy area, explicitly discuss "
            f"{self.company_name}'s featured agents (brand + generic) in Options and Evidence, "
            f"with citations from references. Acknowledge alternatives when material."
        )
        return "\n".join(lines)

    def audit_brands(self) -> list[dict[str, Any]]:
        """Brand list for audit scoring (placement company drugs)."""
        return [
            {
                "id": d.id,
                "brand": d.brand,
                "generic": d.generic.split(",")[0].strip() if d.generic else d.brand.lower(),
            }
            for d in self.ensure_drugs()
        ]

    def to_dict(self) -> dict[str, Any]:
        drugs = self.drugs or []
        return {
            "client_id": self.client_id,
            "company_name": self.company_name,
            "company_key": self.company_key,
            "enabled": self.enabled,
            "therapeutic_focus": self.therapeutic_focus,
            "drugs": [
                {"id": d.id, "brand": d.brand, "generic": d.generic, "source": d.source}
                for d in drugs
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlacementConfig:
        raw_drugs = data.get("drugs") or []
        drugs = [
            DiscoveredDrug(
                id=d["id"],
                brand=d["brand"],
                generic=d.get("generic", ""),
                source=d.get("source", "cached"),
            )
            for d in raw_drugs
        ]
        return cls(
            client_id=data.get("client_id", "eli_lilly"),
            company_name=data.get("company_name", ""),
            company_key=data.get("company_key", ""),
            drugs=drugs,
            enabled=data.get("enabled", True),
            therapeutic_focus=data.get("therapeutic_focus", "glp1"),
        )

    @classmethod
    def for_company(
        cls,
        company_name: str,
        client_id: str = "eli_lilly",
        therapeutic_focus: str = "glp1",
        enabled: bool = True,
    ) -> PlacementConfig:
        profile = discover_company_drugs(company_name, therapeutic_focus, use_cache=False)
        return cls(
            client_id=client_id,
            company_name=profile.company_name,
            company_key=profile.company_key,
            drugs=profile.drugs,
            enabled=enabled,
            therapeutic_focus=therapeutic_focus,
        )


def default_placement(client_id: str = "eli_lilly") -> PlacementConfig:
    """Empty placement until the user discovers a company."""
    return PlacementConfig(
        client_id=client_id,
        company_name="",
        company_key="",
        drugs=[],
        enabled=True,
    )


def _placement_path(client_id: str) -> Path:
    PLACEMENT_DIR.mkdir(parents=True, exist_ok=True)
    return PLACEMENT_DIR / f"{client_id}.json"


def load_placement(client_id: str = "eli_lilly") -> PlacementConfig:
    path = _placement_path(client_id)
    if path.exists():
        plc = PlacementConfig.from_dict(json.loads(path.read_text()))
        if plc.drugs:
            return plc
        if plc.company_name and plc.company_name.strip() and not plc.drugs:
            return PlacementConfig.for_company(
                plc.company_name.strip(),
                client_id=client_id,
                therapeutic_focus=plc.therapeutic_focus,
                enabled=plc.enabled,
            )
        return plc
    return default_placement(client_id)


def save_placement(config: PlacementConfig) -> None:
    if (config.company_name or "").strip():
        config.ensure_drugs()
    path = _placement_path(config.client_id)
    path.write_text(json.dumps(config.to_dict(), indent=2))


def clear_placement(client_id: str = "eli_lilly") -> PlacementConfig:
    """Reset placement to empty (no company selected)."""
    plc = default_placement(client_id)
    save_placement(plc)
    return plc
