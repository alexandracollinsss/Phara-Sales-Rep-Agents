from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from src.config import ROOT

CACHE_DIR = ROOT / "data" / "companies"

# Curated GLP-1 portfolios when FDA search is noisy or incomplete
KNOWN_GLP1_PORTFOLIO: dict[str, list[dict[str, str]]] = {
    "eli lilly": [
        {"brand": "Mounjaro", "generic": "tirzepatide"},
        {"brand": "Zepbound", "generic": "tirzepatide"},
        {"brand": "Trulicity", "generic": "dulaglutide"},
    ],
    "novo nordisk": [
        {"brand": "Ozempic", "generic": "semaglutide"},
        {"brand": "Wegovy", "generic": "semaglutide"},
        {"brand": "Rybelsus", "generic": "semaglutide"},
    ],
    "astrazeneca": [
        {"brand": "Farxiga", "generic": "dapagliflozin"},
    ],
    "sanofi": [
        {"brand": "Soliqua", "generic": "insulin glargine and lixisenatide"},
    ],
}

GLP1_KEYWORDS = (
    "glp-1",
    "glp1",
    "glucagon-like",
    "semaglutide",
    "tirzepatide",
    "liraglutide",
    "dulaglutide",
    "exenatide",
    "lixisenatide",
    "surpass",
    "surmount",
    "sustain",
    "step trial",
    "incretin",
    "mounjaro",
    "zepbound",
    "ozempic",
    "wegovy",
    "trulicity",
    "rybelsus",
)

COMPANY_SEARCH_ALIASES: dict[str, list[str]] = {
    "eli lilly": ["lilly", "eli lilly"],
    "lilly": ["lilly", "eli lilly"],
    "novo nordisk": ["novo nordisk", "novo"],
    "astrazeneca": ["astrazeneca", "astra zeneca"],
    "sanofi": ["sanofi"],
    "pfizer": ["pfizer"],
    "merck": ["merck"],
}


@dataclass
class DiscoveredDrug:
    id: str
    brand: str
    generic: str
    source: str  # openfda | curated

    def brand_terms(self) -> list[str]:
        terms = [self.brand.lower(), self.id]
        for part in re.split(r"[^a-z0-9]+", self.generic.lower()):
            if len(part) > 4:
                terms.append(part)
        return list(dict.fromkeys(terms))


@dataclass
class CompanyProfile:
    company_name: str
    company_key: str
    drugs: list[DiscoveredDrug]
    discovered_at: str
    sources: list[str]
    therapeutic_focus: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "company_name": self.company_name,
            "company_key": self.company_key,
            "drugs": [asdict(d) for d in self.drugs],
            "discovered_at": self.discovered_at,
            "sources": self.sources,
            "therapeutic_focus": self.therapeutic_focus,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompanyProfile:
        drugs = [DiscoveredDrug(**d) for d in data.get("drugs", [])]
        return cls(
            company_name=data["company_name"],
            company_key=data["company_key"],
            drugs=drugs,
            discovered_at=data.get("discovered_at", ""),
            sources=data.get("sources", []),
            therapeutic_focus=data.get("therapeutic_focus", "glp1"),
        )


def normalize_company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _slug_brand(brand: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", brand.lower()).strip("_")


def _is_glp1_relevant(brand: str, generic: str) -> bool:
    hay = f"{brand} {generic}".lower()
    return any(k in hay for k in GLP1_KEYWORDS)


def _search_aliases(company_name: str) -> list[str]:
    key = normalize_company_key(company_name)
    if key in COMPANY_SEARCH_ALIASES:
        return COMPANY_SEARCH_ALIASES[key]
    # Also try partial keys
    for k, aliases in COMPANY_SEARCH_ALIASES.items():
        if k in key or key in k:
            return aliases
    return [company_name, key]


def _fetch_openfda_labels(manufacturer_term: str, limit: int = 100) -> list[dict[str, Any]]:
    """Query openFDA drug labels by manufacturer name."""
    q = f'openfda.manufacturer_name:"{manufacturer_term}"'
    url = "https://api.fda.gov/drug/label.json"
    with httpx.Client(timeout=30.0) as client:
        r = client.get(url, params={"search": q, "limit": limit})
        if r.status_code == 404:
            return []
        r.raise_for_status()
        return r.json().get("results", [])


def _parse_openfda_results(results: list[dict[str, Any]]) -> list[DiscoveredDrug]:
    seen: set[str] = set()
    drugs: list[DiscoveredDrug] = []
    for row in results:
        openfda = row.get("openfda") or {}
        brands = openfda.get("brand_name") or []
        generics = openfda.get("generic_name") or []
        if not brands:
            continue
        brand = brands[0].strip()
        generic = ", ".join(g[:80] for g in generics[:2]) if generics else ""
        key = brand.lower()
        if key in seen or len(brand) < 3:
            continue
        seen.add(key)
        drugs.append(
            DiscoveredDrug(
                id=_slug_brand(brand),
                brand=brand,
                generic=generic,
                source="openfda",
            )
        )
    return drugs


def _merge_curated(company_key: str, drugs: list[DiscoveredDrug]) -> list[DiscoveredDrug]:
    curated = KNOWN_GLP1_PORTFOLIO.get(company_key, [])
    by_brand = {d.brand.lower(): d for d in drugs}
    for c in curated:
        b = c["brand"]
        if b.lower() not in by_brand:
            by_brand[b.lower()] = DiscoveredDrug(
                id=_slug_brand(b),
                brand=b,
                generic=c.get("generic", ""),
                source="curated",
            )
    return list(by_brand.values())


def discover_company_drugs(
    company_name: str,
    therapeutic_focus: str = "glp1",
    use_cache: bool = True,
) -> CompanyProfile:
    """
    Discover marketed drugs for a pharma company via openFDA (+ curated GLP-1 fallbacks).
    """
    company_key = normalize_company_key(company_name)
    cache_path = CACHE_DIR / f"{company_key.replace(' ', '_')}.json"

    if use_cache and cache_path.exists():
        cached = CompanyProfile.from_dict(json.loads(cache_path.read_text()))
        if cached.drugs and cached.therapeutic_focus == therapeutic_focus:
            return cached

    sources: list[str] = []
    all_drugs: list[DiscoveredDrug] = []

    for term in _search_aliases(company_name):
        try:
            results = _fetch_openfda_labels(term)
            if results:
                sources.append(f"openfda:manufacturer_name:{term}")
                all_drugs.extend(_parse_openfda_results(results))
        except httpx.HTTPError:
            continue

    # Deduplicate
    by_id: dict[str, DiscoveredDrug] = {}
    for d in all_drugs:
        by_id[d.id] = d
    merged = list(by_id.values())

    if therapeutic_focus == "glp1":
        merged = _merge_curated(company_key, merged)
        merged = [d for d in merged if _is_glp1_relevant(d.brand, d.generic)]
        # Sort: curated/openfda GLP-1 first by known portfolio order
        portfolio = KNOWN_GLP1_PORTFOLIO.get(company_key, [])
        order = {_slug_brand(p["brand"]): i for i, p in enumerate(portfolio)}

        def sort_key(d: DiscoveredDrug) -> tuple[int, str]:
            return (order.get(d.id, 99), d.brand)

        merged.sort(key=sort_key)

    if not merged and company_key in KNOWN_GLP1_PORTFOLIO:
        sources.append("curated:fallback")
        merged = [
            DiscoveredDrug(
                id=_slug_brand(p["brand"]),
                brand=p["brand"],
                generic=p.get("generic", ""),
                source="curated",
            )
            for p in KNOWN_GLP1_PORTFOLIO[company_key]
        ]

    profile = CompanyProfile(
        company_name=company_name.strip(),
        company_key=company_key,
        drugs=merged[:12],
        discovered_at=datetime.now(timezone.utc).isoformat(),
        sources=sources or ["curated:fallback"],
        therapeutic_focus=therapeutic_focus,
    )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(profile.to_dict(), indent=2))
    return profile
