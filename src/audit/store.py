from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.audit.scorer import MentionScore, score_answer
from src.config import load_client
from src.platform.placement import load_placement

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "audits.db"
LEGACY_CHAT_RUN_PREFIX = "chat-live-"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS audit_runs (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                platform TEXT NOT NULL,
                total_prompts INTEGER NOT NULL,
                favorable INTEGER NOT NULL,
                neutral INTEGER NOT NULL,
                unfavorable INTEGER NOT NULL,
                absent INTEGER NOT NULL,
                brand_mention_total INTEGER NOT NULL,
                competitor_mention_total INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_prompt_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                prompt_id TEXT NOT NULL,
                prompt_text TEXT NOT NULL,
                favorability TEXT NOT NULL,
                brand_mentions TEXT NOT NULL,
                competitor_mentions TEXT NOT NULL,
                answer_excerpt TEXT,
                FOREIGN KEY (run_id) REFERENCES audit_runs(id)
            );
            """
        )
        _migrate_legacy_chat_runs(conn)


def _run_metrics_from_counts(
    total: int,
    favorable: int,
    neutral: int,
    unfavorable: int,
    absent: int,
    brand_total: int,
    comp_total: int,
) -> dict[str, float]:
    """Derived metrics for one snapshot (single chat or multi-prompt audit)."""
    mention_total = brand_total + comp_total
    share_of_voice = round(100 * brand_total / mention_total, 1) if mention_total else 0.0
    visibility = round(100 * (total - absent) / total, 1) if total else 0.0
    favorable_rate = round(100 * favorable / total, 1) if total else 0.0
    # 0–100 index: favorable=100, neutral=55, unfavorable=15, absent=0
    fav_score = (
        favorable * 100 + neutral * 55 + unfavorable * 15
    ) / total if total else 0.0
    return {
        "share_of_voice_pct": share_of_voice,
        "visibility_pct": visibility,
        "favorable_rate_pct": favorable_rate,
        "favorability_index": round(fav_score, 1),
    }


def _metrics_for_run(run: dict[str, Any]) -> dict[str, float]:
    return _run_metrics_from_counts(
        run["total_prompts"],
        run["favorable"],
        run["neutral"],
        run["unfavorable"],
        run["absent"],
        run["brand_mention_total"],
        run["competitor_mention_total"],
    )


def _rolling_avg(values: list[float], window: int = 5) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
            continue
        chunk = values[i + 1 - window : i + 1]
        out.append(round(sum(chunk) / len(chunk), 1))
    return out


def _insert_run_with_score(
    conn: sqlite3.Connection,
    client_id: str,
    run_id: str,
    scored: MentionScore,
    platform: str,
    created_at: str,
) -> None:
    fav = scored.favorability
    fav_counts = {"favorable": 0, "neutral": 0, "unfavorable": 0, "absent": 0}
    fav_counts[fav] = 1
    conn.execute(
        """
        INSERT INTO audit_runs (
            id, client_id, created_at, platform,
            total_prompts, favorable, neutral, unfavorable, absent,
            brand_mention_total, competitor_mention_total
        ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            client_id,
            created_at,
            platform,
            fav_counts["favorable"],
            fav_counts["neutral"],
            fav_counts["unfavorable"],
            fav_counts["absent"],
            scored.company_mentions,
            scored.competitor_mentions_total,
        ),
    )
    conn.execute(
        """
        INSERT INTO audit_prompt_scores (
            run_id, prompt_id, prompt_text, favorability,
            brand_mentions, competitor_mentions, answer_excerpt
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            scored.prompt_id,
            scored.prompt_text,
            scored.favorability,
            json.dumps(scored.brand_mentions),
            json.dumps(scored.competitor_mentions),
            scored.answer[:2000] if scored.answer else None,
        ),
    )


def _migrate_legacy_chat_runs(conn: sqlite3.Connection) -> None:
    """Split old single rolling chat run into per-question snapshots."""
    rows = conn.execute(
        "SELECT id, client_id FROM audit_runs WHERE id LIKE ?",
        (f"{LEGACY_CHAT_RUN_PREFIX}%",),
    ).fetchall()
    for row in rows:
        legacy_id = row["id"]
        client_id = row["client_id"]
        prompts = conn.execute(
            """
            SELECT prompt_id, prompt_text, favorability,
                   brand_mentions, competitor_mentions, answer_excerpt
            FROM audit_prompt_scores WHERE run_id = ?
            ORDER BY id ASC
            """,
            (legacy_id,),
        ).fetchall()
        if not prompts:
            conn.execute("DELETE FROM audit_runs WHERE id = ?", (legacy_id,))
            continue
        client = load_client(client_id)
        placement_brands = load_placement(client_id).audit_brands()
        base_raw = conn.execute(
            "SELECT created_at FROM audit_runs WHERE id = ?", (legacy_id,)
        ).fetchone()["created_at"]
        base_dt = datetime.fromisoformat(base_raw.replace("Z", "+00:00"))
        conn.execute("DELETE FROM audit_prompt_scores WHERE run_id = ?", (legacy_id,))
        conn.execute("DELETE FROM audit_runs WHERE id = ?", (legacy_id,))
        for i, p in enumerate(prompts):
            answer = p["answer_excerpt"] or ""
            scored = score_answer(
                p["prompt_id"],
                p["prompt_text"],
                answer,
                client,
                extra_brands=placement_brands,
            )
            run_id = str(uuid.uuid4())
            ts = (base_dt + timedelta(seconds=i)).isoformat()
            _insert_run_with_score(conn, client_id, run_id, scored, "chat", ts)


def record_chat_exchange(client_id: str, question: str, answer: str) -> str:
    """Score one chat Q&A as its own time-series snapshot."""
    if not answer or not answer.strip():
        return ""
    init_db()
    client = load_client(client_id)
    placement_brands = load_placement(client_id).audit_brands()
    scored = score_answer(
        f"chat-{uuid.uuid4().hex[:12]}",
        question,
        answer,
        client,
        extra_brands=placement_brands,
    )
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        _insert_run_with_score(conn, client_id, run_id, scored, "chat", now)
    return run_id


def save_run(client_id: str, scores: list[MentionScore], platform: str = "open_evidence_clone") -> str:
    init_db()
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    fav_counts = {"favorable": 0, "neutral": 0, "unfavorable": 0, "absent": 0}
    brand_total = 0
    comp_total = 0
    for s in scores:
        fav_counts[s.favorability] = fav_counts.get(s.favorability, 0) + 1
        brand_total += s.company_mentions
        comp_total += s.competitor_mentions_total

    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO audit_runs (
                id, client_id, created_at, platform,
                total_prompts, favorable, neutral, unfavorable, absent,
                brand_mention_total, competitor_mention_total
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                client_id,
                now,
                platform,
                len(scores),
                fav_counts["favorable"],
                fav_counts["neutral"],
                fav_counts["unfavorable"],
                fav_counts["absent"],
                brand_total,
                comp_total,
            ),
        )
        for s in scores:
            conn.execute(
                """
                INSERT INTO audit_prompt_scores (
                    run_id, prompt_id, prompt_text, favorability,
                    brand_mentions, competitor_mentions, answer_excerpt
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    s.prompt_id,
                    s.prompt_text,
                    s.favorability,
                    json.dumps(s.brand_mentions),
                    json.dumps(s.competitor_mentions),
                    s.answer[:500] if s.answer else None,
                ),
            )
    return run_id


def list_runs(client_id: str, limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM audit_runs
            WHERE client_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (client_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _recompute_run_totals(conn: sqlite3.Connection, run_id: str, client_id: str) -> tuple[int, int]:
    client = load_client(client_id)
    placement_brands = load_placement(client_id).audit_brands()
    rows = conn.execute(
        """
        SELECT prompt_id, prompt_text, answer_excerpt
        FROM audit_prompt_scores WHERE run_id = ?
        """,
        (run_id,),
    ).fetchall()
    brand_total = 0
    comp_total = 0
    for row in rows:
        answer = row["answer_excerpt"] or ""
        if not answer:
            continue
        scored = score_answer(
            row["prompt_id"],
            row["prompt_text"],
            answer,
            client,
            extra_brands=placement_brands,
        )
        brand_total += scored.company_mentions
        comp_total += scored.competitor_mentions_total
    return brand_total, comp_total


def _runs_with_accurate_totals(client_id: str, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not runs:
        return runs
    with _conn() as conn:
        out: list[dict[str, Any]] = []
        for r in runs:
            row = dict(r)
            b, c = _recompute_run_totals(conn, row["id"], client_id)
            if b or c:
                row["brand_mention_total"] = b
                row["competitor_mention_total"] = c
            metrics = _metrics_for_run(row)
            row.update(metrics)
            out.append(row)
        return out


def _prompt_preview(conn: sqlite3.Connection, run_id: str) -> str:
    row = conn.execute(
        "SELECT prompt_text FROM audit_prompt_scores WHERE run_id = ? LIMIT 1",
        (run_id,),
    ).fetchone()
    if not row:
        return ""
    text = row["prompt_text"] or ""
    return text[:72] + ("…" if len(text) > 72 else "")


def dashboard_series(client_id: str) -> dict[str, Any]:
    """Time series — one point per chat question or audit battery run."""
    plc = load_placement(client_id)
    runs = _runs_with_accurate_totals(client_id, list_runs(client_id, limit=200))
    runs_chrono = list(reversed(runs))

    labels: list[str] = []
    for i, r in enumerate(runs_chrono, start=1):
        ts = r["created_at"][5:16].replace("T", " ")
        kind = "Chat" if r.get("platform") == "chat" else "Audit"
        labels.append(f"{ts} {kind} #{i}")

    sov = [r["share_of_voice_pct"] for r in runs_chrono]
    visibility = [r["visibility_pct"] for r in runs_chrono]
    favorable_rate = [r["favorable_rate_pct"] for r in runs_chrono]
    fav_index = [r["favorability_index"] for r in runs_chrono]

    with _conn() as conn:
        for r in runs:
            r["prompt_preview"] = _prompt_preview(conn, r["id"])

    chat_count = sum(1 for r in runs if r.get("platform") == "chat")
    audit_count = sum(1 for r in runs if r.get("platform") != "chat")

    def _avg_last(arr: list[float], n: int = 10) -> float | None:
        if not arr:
            return None
        chunk = arr[-n:]
        return round(sum(chunk) / len(chunk), 1)

    latest = runs[0] if runs else None
    trend_sov: float | None = None
    if len(sov) >= 2:
        trend_sov = round(sov[-1] - sov[-2], 1)

    def _latest_favorability(run: dict[str, Any] | None) -> str | None:
        if not run:
            return None
        if run.get("favorable"):
            return "favorable"
        if run.get("unfavorable"):
            return "unfavorable"
        if run.get("neutral"):
            return "neutral"
        if run.get("absent"):
            return "absent"
        return None

    return {
        "company_name": plc.company_name,
        "labels": labels,
        "share_of_voice_pct": sov,
        "visibility_pct": visibility,
        "favorable_rate_pct": favorable_rate,
        "favorability_index": fav_index,
        "rolling_sov_5": _rolling_avg(sov, 5),
        "rolling_visibility_5": _rolling_avg(visibility, 5),
        "rolling_favorable_5": _rolling_avg(favorable_rate, 5),
        "favorable": [r["favorable"] for r in runs_chrono],
        "neutral": [r["neutral"] for r in runs_chrono],
        "unfavorable": [r["unfavorable"] for r in runs_chrono],
        "absent": [r["absent"] for r in runs_chrono],
        "brand_mentions": [r["brand_mention_total"] for r in runs_chrono],
        "competitor_mentions": [r["competitor_mention_total"] for r in runs_chrono],
        "runs": runs,
        "chat_questions": chat_count,
        "audit_runs": audit_count,
        "summary": {
            "latest_sov": sov[-1] if sov else None,
            "avg_sov_10": _avg_last(sov, 10),
            "latest_visibility": visibility[-1] if visibility else None,
            "avg_visibility_10": _avg_last(visibility, 10),
            "latest_favorable_rate": favorable_rate[-1] if favorable_rate else None,
            "avg_favorable_10": _avg_last(favorable_rate, 10),
            "latest_favorability_index": fav_index[-1] if fav_index else None,
            "total_snapshots": len(runs),
            "trend_sov": trend_sov,
            "latest_favorability": _latest_favorability(latest),
        },
    }
