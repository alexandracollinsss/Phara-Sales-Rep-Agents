from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class MentionScore:
    prompt_id: str
    prompt_text: str
    answer: str
    brand_mentions: dict[str, int]
    competitor_mentions: dict[str, int]
    favorability: str  # favorable | neutral | unfavorable | absent
    company_mentions: int = 0
    competitor_mentions_total: int = 0


def audit_tracking_context(
    client: dict[str, Any], placement_drugs: list[dict[str, Any]] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Company brands come from placement (discovered drugs).
    Competitors are other products in the client profile not on the placement list.
    """
    if placement_drugs:
        company = list(placement_drugs)
        company_ids = {b["id"] for b in company}
    else:
        company = list(client.get("brands") or [])
        company_ids = {b["id"] for b in company}

    competitors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in list(client.get("brands") or []) + list(client.get("competitors") or []):
        eid = entry["id"]
        if eid in company_ids or eid in seen:
            continue
        seen.add(eid)
        competitors.append(entry)
    return company, competitors


def _normalize_brand_def(entry: dict[str, Any]) -> dict[str, Any]:
    generic = entry.get("generic") or ""
    if isinstance(generic, str):
        generic = generic.split(",")[0].strip()
    return {
        "id": entry["id"],
        "brand": entry.get("brand") or entry["id"],
        "generic": generic,
        "differentiators": entry.get("differentiators") or [],
    }


def _hits_for_brand(lower: str, brand: dict[str, Any], shared_generics: set[str]) -> int:
    """Count mentions for one product without double-counting id vs brand name."""
    hits = 0
    for term in (brand.get("brand"), brand["id"]):
        if term and isinstance(term, str) and len(term) >= 3:
            hits = max(hits, len(re.findall(re.escape(term.lower()), lower)))
    generic = (brand.get("generic") or "").lower()
    if generic and len(generic) >= 4:
        if generic not in shared_generics:
            gen_hits = len(re.findall(re.escape(generic), lower))
            if gen_hits:
                shared_generics.add(generic)
                hits += gen_hits
    return hits


def _side_mentions(
    answer: str, defs: list[dict[str, Any]]
) -> tuple[dict[str, int], int]:
    lower = answer.lower()
    shared_generics: set[str] = set()
    by_id: dict[str, int] = {}
    for raw in defs:
        brand = _normalize_brand_def(raw)
        by_id[brand["id"]] = _hits_for_brand(lower, brand, shared_generics)
    return by_id, sum(by_id.values())


def _all_match_terms(defs: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    seen_generics: set[str] = set()
    for raw in defs:
        brand = _normalize_brand_def(raw)
        for term in (brand.get("brand"), brand["id"]):
            if term and isinstance(term, str) and len(term) >= 3:
                terms.append(term)
        generic = (brand.get("generic") or "").lower()
        if generic and len(generic) >= 4 and generic not in seen_generics:
            seen_generics.add(generic)
            terms.append(brand.get("generic") or generic)
    return terms


def _favorability(
    answer: str,
    company_defs: list[dict[str, Any]],
    competitor_defs: list[dict[str, Any]],
) -> str:
    lower = answer.lower()
    company_terms = _all_match_terms(company_defs)
    competitor_terms = _all_match_terms(competitor_defs)
    brand_hit = any(t.lower() in lower for t in company_terms)
    if not brand_hit:
        return "absent"

    positive = (
        "recommend",
        "preferred",
        "first-line",
        "first line",
        "superior",
        "greater reduction",
        "advantage",
    )
    negative = ("avoid", "not recommend", "inferior", "less effective", "contraindicated")

    b_pos = sum(1 for p in positive if p in lower)
    b_neg = sum(1 for n in negative if n in lower)
    comp_pos = 0
    for c in competitor_terms:
        if c.lower() in lower:
            for p in positive:
                if p in lower and c.lower() in lower:
                    comp_pos += 1

    if b_neg > b_pos:
        return "unfavorable"
    if b_pos > 0 and comp_pos == 0:
        return "favorable"
    return "neutral"


def score_answer(
    prompt_id: str,
    prompt_text: str,
    answer: str,
    client: dict[str, Any],
    extra_brands: list[dict[str, Any]] | None = None,
) -> MentionScore:
    placement_defs = extra_brands or []
    company_defs, competitor_defs = audit_tracking_context(client, placement_defs or None)

    brand_mentions, company_total = _side_mentions(answer, company_defs)
    competitor_mentions, competitor_total = _side_mentions(answer, competitor_defs)

    fav = _favorability(answer, company_defs, competitor_defs)
    return MentionScore(
        prompt_id=prompt_id,
        prompt_text=prompt_text,
        answer=answer,
        brand_mentions=brand_mentions,
        competitor_mentions=competitor_mentions,
        favorability=fav,
        company_mentions=company_total,
        competitor_mentions_total=competitor_total,
    )
