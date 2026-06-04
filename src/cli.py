from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.agents.orchestrator import SalesRepOrchestrator
from src.agents.research_agent import ResearchAgent
from src.config import load_client
from src.ollama import OllamaClient

console = Console()
ROOT = Path(__file__).resolve().parents[1]


def _check_ollama(client_id: str) -> OllamaClient:
    client = load_client(client_id)
    audit = client["audit"]
    ollama = OllamaClient(audit.get("ollama_base_url"), audit.get("model", "llama3.2"))
    if not ollama.is_available():
        console.print("[red]Ollama is not running.[/red] Start the Ollama app first.")
        sys.exit(1)
    if not ollama.has_model():
        console.print(f"[red]Model {ollama.model} not found.[/red] Run: ollama pull {ollama.model}")
        sys.exit(1)
    return ollama


def cmd_ask(question: str, client_id: str, company: str | None) -> None:
    _check_ollama(client_id)
    orch = SalesRepOrchestrator(client_id)
    if company:
        orch.setup_company(company)
    result = orch.ask(question)
    console.print(Panel(result.answer, title="Clinical Q&A", border_style="cyan"))


def cmd_discover(company: str, client_id: str) -> None:
    profile, plc = ResearchAgent(client_id).discover_and_apply_placement(company)
    console.print(f"[green]Found {len(profile.drugs)} drugs for {profile.company_name}[/green]")
    for i, d in enumerate(profile.drugs, 1):
        console.print(f"  {i}. {d.brand} ({d.generic}) [{d.source}]")


def cmd_audit(client_id: str, save: bool) -> None:
    _check_ollama(client_id)
    orch = SalesRepOrchestrator(client_id)
    plc = orch.placement.get()
    console.print(f"[bold]Auditing as {plc.company_name}…[/bold]")
    if save:
        scores, run_id = orch.audit_and_save()
        console.print(f"[dim]Saved run {run_id}[/dim]")
    else:
        scores, _ = orch.audit.run(save=False)
    table = Table("Prompt", "Favorability", "Brands", "Competitors")
    for s in scores:
        table.add_row(
            s.prompt_id,
            s.favorability,
            str(s.company_mentions),
            str(s.competitor_mentions_total),
        )
    console.print(table)


def cmd_run(client_id: str) -> None:
    _check_ollama(client_id)
    orch = SalesRepOrchestrator(client_id)
    plc = orch.placement.get()
    console.print(
        Panel(
            f"Full rep cycle for [bold]{plc.company_name}[/bold]",
            title="Sales Rep Orchestrator",
            border_style="green",
        )
    )
    briefing = orch.run_full_cycle(save_audit=True)
    console.print(Panel(briefing.summary, title="Executive summary"))
    if briefing.run_id:
        console.print(f"[dim]Audit saved: {briefing.run_id}[/dim]")
    for section, items in [
        ("Audit highlights", briefing.audit_highlights),
        ("Content optimization", briefing.optimization_actions),
        ("Placement targets", briefing.placement_actions),
        ("Risks", briefing.risks),
    ]:
        console.print(f"[bold]{section}[/bold]")
        for item in items:
            console.print(f"  • {item}")


def cmd_agents() -> None:
    table = Table("Agent", "Role")
    for a in SalesRepOrchestrator("eli_lilly").agent_roster():
        table.add_row(a["id"], a["description"])
    console.print(table)


def cmd_test(full: bool) -> None:
    args = [sys.executable, str(ROOT / "scripts" / "test_all.py")]
    if full:
        args.append("--full")
    raise SystemExit(subprocess.call(args))


def cmd_serve(no_reload: bool = False, port: int = 8080) -> None:
    import uvicorn

    web = ROOT / "web"
    kwargs: dict = {
        "app": "src.web.app:app",
        "host": "127.0.0.1",
        "port": port,
    }
    if not no_reload:
        kwargs["reload"] = True
        kwargs["reload_dirs"] = [str(ROOT / "src"), str(web)]
    uvicorn.run(**kwargs)


def cmd_share() -> None:
    import subprocess

    script = ROOT / "scripts" / "share.sh"
    raise SystemExit(subprocess.call(["bash", str(script)]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Pharma digital sales rep platform")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_client(p: argparse.ArgumentParser) -> None:
        p.add_argument("--client", default="eli_lilly", help="Client config id")

    ask_p = sub.add_parser("ask", help="Ask the clinical Q&A platform")
    add_client(ask_p)
    ask_p.add_argument("question", help="Physician-style question")
    ask_p.add_argument("--company", help="Refresh placement for this company")

    disc_p = sub.add_parser("discover", help="Discover company drugs and apply placement")
    add_client(disc_p)
    disc_p.add_argument("company", help="e.g. Eli Lilly")

    audit_p = sub.add_parser("audit", help="Run prompt battery audit")
    add_client(audit_p)
    audit_p.add_argument("--save", action="store_true", help="Persist to dashboard DB")

    run_p = sub.add_parser("run", help="Full audit + optimize + briefing (saves audit)")
    add_client(run_p)

    sub.add_parser("agents", help="List specialized agents")
    test_p = sub.add_parser("test", help="Run smoke tests")
    test_p.add_argument("--full", action="store_true", help="Include full 8-prompt audit")
    serve_p = sub.add_parser("serve", help="Start web UI")
    serve_p.add_argument("--no-reload", action="store_true", help="Disable auto-reload")
    serve_p.add_argument("--port", type=int, default=8080)
    sub.add_parser("share", help="Start web UI + Cloudflare public URL")

    args = parser.parse_args()
    if args.command == "ask":
        cmd_ask(args.question, args.client, getattr(args, "company", None))
    elif args.command == "discover":
        cmd_discover(args.company, args.client)
    elif args.command == "audit":
        cmd_audit(args.client, args.save)
    elif args.command == "run":
        cmd_run(args.client)
    elif args.command == "agents":
        cmd_agents()
    elif args.command == "test":
        cmd_test(args.full)
    elif args.command == "serve":
        cmd_serve(no_reload=args.no_reload, port=args.port)
    elif args.command == "share":
        cmd_share()


if __name__ == "__main__":
    main()
