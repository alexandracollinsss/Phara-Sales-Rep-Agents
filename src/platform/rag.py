from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.config import CORPUS_DIR


@dataclass
class CorpusChunk:
    id: str
    title: str
    body: str
    source: str
    pmid: str | None
    journal: str | None


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "section"


def _parse_pmid(body: str) -> str | None:
    m = re.search(r"\*\*PMID:\*\*\s*\[?(\d+)\]?", body)
    return m.group(1) if m else None


def _parse_journal(body: str) -> str | None:
    m = re.search(r"\*\*Citation:\*\*.*?\*([^*]+)\*", body)
    return m.group(1).strip() if m else None


_CHUNKS_CACHE: list[CorpusChunk] | None = None


def load_chunks() -> list[CorpusChunk]:
    global _CHUNKS_CACHE
    if _CHUNKS_CACHE is not None:
        return _CHUNKS_CACHE
    chunks: list[CorpusChunk] = []
    for path in sorted(CORPUS_DIR.glob("*.md")):
        text = path.read_text()
        file_stem = path.stem
        sections = re.split(r"\n## ", text)
        for i, section in enumerate(sections):
            if i == 0 and not section.strip().startswith("#"):
                continue
            section = section.strip()
            if not section:
                continue
            lines = section.splitlines()
            title_line = lines[0].lstrip("# ").strip()
            body = "\n".join(lines[1:]).strip()
            if not body:
                continue
            chunk_id = f"{file_stem}:{_slug(title_line)}"
            chunks.append(
                CorpusChunk(
                    id=chunk_id,
                    title=title_line,
                    body=body,
                    source=title_line,
                    pmid=_parse_pmid(body),
                    journal=_parse_journal(body),
                )
            )
    _CHUNKS_CACHE = chunks
    return chunks


def retrieve(
    query: str,
    top_k: int = 6,
    boost_terms: list[tuple[str, float]] | None = None,
    force_corpus_stems: list[str] | None = None,
) -> list[CorpusChunk]:
    """Lightweight lexical retrieval with optional placement boosts."""
    chunks = load_chunks()
    terms = [t for t in re.findall(r"[a-z0-9]{3,}", query.lower()) if len(t) > 2]

    scored_map: dict[str, float] = {}
    for c in chunks:
        hay = f"{c.title} {c.body}".lower()
        score = sum(hay.count(t) * (2 if t in c.title.lower() else 1) for t in terms) if terms else 0.1
        if boost_terms:
            for term, weight in boost_terms:
                if term in hay:
                    score += weight * (3 if term in c.title.lower() else 1)
        scored_map[c.id] = score

    # Force-include placement corpus (Lilly SURPASS/SURMOUNT, etc.)
    if force_corpus_stems:
        for c in chunks:
            stem = c.id.split(":")[0]
            if stem in force_corpus_stems:
                scored_map[c.id] = scored_map.get(c.id, 0) + 10.0

    if not scored_map:
        return chunks[:top_k]

    ranked = sorted(chunks, key=lambda c: scored_map.get(c.id, 0), reverse=True)
    seen: set[str] = set()
    out: list[CorpusChunk] = []
    for c in ranked:
        if c.id in seen:
            continue
        seen.add(c.id)
        out.append(c)
        if len(out) >= top_k:
            break
    return out


def format_context(chunks: list[CorpusChunk]) -> tuple[str, list[dict]]:
    """Numbered context for LLM + source list for UI citations."""
    parts: list[str] = []
    sources: list[dict] = []
    for i, c in enumerate(chunks, start=1):
        parts.append(f"[{i}] {c.title}\n{c.body}")
        sources.append(
            {
                "index": i,
                "id": c.id,
                "title": c.title,
                "pmid": c.pmid,
                "journal": c.journal,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{c.pmid}/" if c.pmid else None,
            }
        )
    return "\n\n".join(parts), sources
