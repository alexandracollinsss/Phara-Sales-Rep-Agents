#!/usr/bin/env python3
"""Smoke tests for all major product functions. Run: python scripts/test_all.py [--full]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def ok(name: str) -> None:
    print(f"  PASS  {name}")


def fail(name: str, err: str) -> None:
    print(f"  FAIL  {name}: {err}")
    FAILURES.append(f"{name}: {err}")


def test_imports() -> None:
    mods = [
        "src.agents.orchestrator",
        "src.agents.research_agent",
        "src.agents.platform_agent",
        "src.agents.audit_agent",
        "src.agents.placement_agent",
        "src.agents.optimizer_agent",
        "src.web.app",
        "src.research.company_drugs",
        "src.platform.placement",
        "src.platform.rag",
    ]
    for m in mods:
        try:
            __import__(m)
            ok(f"import {m}")
        except Exception as e:
            fail(f"import {m}", str(e))


def test_research() -> None:
    from src.research.company_drugs import discover_company_drugs

    try:
        p = discover_company_drugs("Eli Lilly", use_cache=True)
        if len(p.drugs) < 2:
            fail("discover Eli Lilly", f"expected >=2 drugs, got {len(p.drugs)}")
        else:
            ok(f"discover Eli Lilly ({len(p.drugs)} drugs)")
    except Exception as e:
        fail("discover Eli Lilly", str(e))

    try:
        p2 = discover_company_drugs("NotARealCorp999", use_cache=True)
        ok(f"discover invalid company ({len(p2.drugs)} drugs)")
    except Exception as e:
        fail("discover invalid", str(e))


def test_placement() -> None:
    from src.platform.placement import PlacementConfig, clear_placement, load_placement, save_placement

    try:
        plc = PlacementConfig.for_company("Eli Lilly", client_id="eli_lilly")
        save_placement(plc)
        loaded = load_placement("eli_lilly")
        if not loaded.drugs:
            fail("placement round-trip", "no drugs after save")
        else:
            ok(f"placement save/load ({len(loaded.drugs)} drugs)")
        clear_placement("eli_lilly")
    except Exception as e:
        fail("placement", str(e))


def test_rag() -> None:
    from src.platform.rag import load_chunks, retrieve

    try:
        n = len(load_chunks())
        r = retrieve("tirzepatide semaglutide weight", top_k=3)
        if n < 5 or len(r) < 1:
            fail("rag", f"chunks={n} retrieved={len(r)}")
        else:
            ok(f"rag ({n} chunks, {len(r)} retrieved)")
    except Exception as e:
        fail("rag", str(e))


def test_agents_roster() -> None:
    from src.agents.orchestrator import SalesRepOrchestrator

    try:
        o = SalesRepOrchestrator("eli_lilly")
        roster = o.agent_roster()
        if len(roster) < 5:
            fail("agent roster", str(roster))
        else:
            ok(f"agent roster ({len(roster)} agents)")
    except Exception as e:
        fail("agent roster", str(e))


def test_ollama() -> None:
    from src.config import load_client
    from src.ollama import OllamaClient

    client = load_client("eli_lilly")
    audit = client["audit"]
    ollama = OllamaClient(audit.get("ollama_base_url"), audit.get("model", "llama3.2"))
    if ollama.is_available():
        ok("ollama reachable")
        if ollama.has_model():
            ok(f"ollama model {ollama.model}")
        else:
            fail("ollama model", f"pull with: ollama pull {ollama.model}")
    else:
        fail("ollama", "not running — start Ollama app")


def test_platform_ask() -> None:
    from src.agents.platform_agent import PlatformAgent
    from src.ollama import OllamaClient
    from src.config import load_client

    client = load_client("eli_lilly")
    audit = client["audit"]
    if not OllamaClient(audit["ollama_base_url"], audit["model"]).is_available():
        print("  SKIP  platform ask (ollama down)")
        return
    try:
        r = PlatformAgent("eli_lilly").ask("What is tirzepatide used for?")
        if len(r.answer) < 50:
            fail("platform ask", "answer too short")
        else:
            ok("platform ask")
    except Exception as e:
        fail("platform ask", str(e))


def test_audit_full() -> None:
    from src.agents.audit_agent import AuditAgent
    from src.ollama import OllamaClient
    from src.config import load_client

    client = load_client("eli_lilly")
    audit_cfg = client["audit"]
    if not OllamaClient(audit_cfg["ollama_base_url"], audit_cfg["model"]).is_available():
        print("  SKIP  full audit (ollama down)")
        return
    try:
        scores, run_id = AuditAgent("eli_lilly").run(save=True)
        if len(scores) != 8 or not run_id:
            fail("audit run", f"scores={len(scores)} run_id={run_id}")
        else:
            ok(f"audit run (8 prompts, run_id={run_id[:8]}…)")
    except Exception as e:
        fail("audit run", str(e))


def test_api_routes() -> None:
    try:
        import httpx

        base = "http://127.0.0.1:8080"
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{base}/api/health")
            if r.status_code != 200:
                fail("GET /api/health", str(r.status_code))
                return
            ok("GET /api/health")

            r = c.get(f"{base}/api/agents")
            if r.status_code != 200:
                fail("GET /api/agents", str(r.status_code))
            else:
                ok("GET /api/agents")

            r = c.post(
                f"{base}/api/company/discover",
                json={"company_name": "Eli Lilly", "client_id": "eli_lilly"},
            )
            if r.status_code != 200:
                fail("POST /api/company/discover", r.text[:200])
            else:
                ok("POST /api/company/discover")

            r = c.post(f"{base}/api/visits", json={})
            if r.status_code != 200:
                fail("POST /api/visits", str(r.status_code))
            else:
                ok("POST /api/visits")
    except httpx.ConnectError:
        print("  SKIP  API routes (server not on :8080 — run: python -m src.cli serve)")
    except Exception as e:
        fail("API routes", str(e))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Include slow audit (8 LLM calls)")
    args = parser.parse_args()

    print("Pharma agent — smoke tests\n")
    test_imports()
    test_research()
    test_placement()
    test_rag()
    test_agents_roster()
    test_ollama()
    test_platform_ask()
    if args.full:
        test_audit_full()
    test_api_routes()

    print()
    if FAILURES:
        print(f"FAILED {len(FAILURES)}:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
