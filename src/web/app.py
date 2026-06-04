from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agents.orchestrator import SalesRepOrchestrator
from src.agents.research_agent import ResearchAgent
from src.audit.store import dashboard_series, init_db, list_runs, record_chat_exchange
from src.config import load_client
from src.ollama import OllamaClient
from src.platform.open_evidence_live import OpenEvidenceLive
from src.platform.placement import PlacementConfig, clear_placement, load_placement, save_placement
from src.platform.rag import load_chunks
from src.research.company_drugs import normalize_company_key

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
STATIC_DIR = WEB_DIR / "static"
DASHBOARD_JS_VERSION = "6"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Pharma Sales Rep Platform", version="0.4.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_visits: dict[str, list[dict[str, Any]]] = {}
_ollama_ready_cache: dict[str, tuple[float, OllamaClient]] = {}
_OLLAMA_CACHE_TTL_SEC = 30.0


class CompanyDiscoverBody(BaseModel):
    company_name: str
    client_id: str = "eli_lilly"
    therapeutic_focus: str = "glp1"
    enabled: bool = True


class PlacementBody(BaseModel):
    client_id: str = "eli_lilly"
    company_name: str = ""
    enabled: bool = True
    therapeutic_focus: str = "glp1"


class AskBody(BaseModel):
    question: str
    visit_id: Optional[str] = None
    client_id: str = "eli_lilly"
    use_placement: bool = True
    company_name: Optional[str] = None


class VisitCreate(BaseModel):
    title: Optional[str] = None


def _ollama_client(client_id: str) -> OllamaClient:
    client = load_client(client_id)
    audit = client["audit"]
    return OllamaClient(audit.get("ollama_base_url"), audit.get("model", "llama3.2"))


def _require_ollama(client_id: str) -> OllamaClient:
    now = time.monotonic()
    cached = _ollama_ready_cache.get(client_id)
    if cached and now - cached[0] < _OLLAMA_CACHE_TTL_SEC:
        return cached[1]

    ollama = _ollama_client(client_id)
    if not ollama.is_available():
        raise HTTPException(
            503,
            "Ollama is not running. Start the Ollama app and run: ollama pull llama3.2",
        )
    if not ollama.has_model():
        raise HTTPException(
            503,
            f"Model '{ollama.model}' not found. Run: ollama pull {ollama.model}",
        )
    _ollama_ready_cache[client_id] = (now, ollama)
    return ollama


def _placement_from_request(
    client_id: str,
    company_name: Optional[str],
    use_placement: bool,
) -> PlacementConfig:
    if not use_placement:
        return PlacementConfig(client_id=client_id, enabled=False, company_name="")
    plc = load_placement(client_id)
    if company_name and company_name.strip():
        requested_key = normalize_company_key(company_name.strip())
        if requested_key != normalize_company_key(plc.company_name):
            try:
                _, plc = ResearchAgent(client_id).discover_and_apply_placement(
                    company_name.strip(), enabled=True, refresh=False
                )
            except ValueError as e:
                raise HTTPException(404, str(e)) from e
    return plc


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "templates" / "index.html")


@app.get("/dashboard")
async def dashboard_page(client_id: str = "eli_lilly") -> HTMLResponse:
    """Serve dashboard with metrics embedded so KPIs render even if fetch fails."""
    init_db()
    template = (WEB_DIR / "templates" / "dashboard.html").read_text(encoding="utf-8")
    try:
        boot = dashboard_series(client_id)
    except Exception as e:
        logger.exception("dashboard_series failed")
        boot = {
            "company_name": "Company",
            "labels": [],
            "runs": [],
            "summary": {},
            "error": str(e),
        }
    payload = json.dumps(boot).replace("</", "<\\/")
    inject = (
        f'<script>window.__DASHBOARD_BOOT__={payload};'
        f'window.__DASHBOARD_CLIENT__="{client_id}";</script>\n'
        f'<script src="/static/js/dashboard.js?v={DASHBOARD_JS_VERSION}"></script>\n'
    )
    template = template.replace(
        '<script src="/static/js/dashboard.js"></script>', inject
    )
    if '<script src="/static/js/dashboard.js' not in template:
        template = template.replace("</body>", inject + "</body>")
    return HTMLResponse(template)


@app.get("/api/agents")
async def list_agents() -> list[dict[str, str]]:
    return SalesRepOrchestrator("eli_lilly").agent_roster()


@app.get("/api/health")
async def health(client_id: str = "eli_lilly") -> dict[str, Any]:
    ollama = _ollama_client(client_id)
    live = OpenEvidenceLive()
    plc = load_placement(client_id)
    plc.ensure_drugs()
    return {
        "status": "ok",
        "ollama": ollama.is_available(),
        "ollama_model_ready": ollama.has_model() if ollama.is_available() else False,
        "model": ollama.model,
        "live_openevidence": live.is_available,
        "corpus_chunks": len(load_chunks()),
        "placement_company": plc.company_name,
        "placement_drugs": len(plc.drugs or []),
    }


@app.post("/api/company/discover")
async def company_discover(body: CompanyDiscoverBody) -> dict[str, Any]:
    if not body.company_name.strip():
        raise HTTPException(400, "company_name is required")
    try:
        profile, plc = ResearchAgent(body.client_id).discover_and_apply_placement(
            body.company_name.strip(),
            enabled=body.enabled,
            refresh=True,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"Drug discovery failed: {e}") from e

    return {
        "placement": plc.to_dict(),
        "profile": profile.to_dict(),
        "message": f"Found {len(profile.drugs)} therapies for {profile.company_name}",
    }


@app.get("/api/placement")
async def get_placement(client_id: str = "eli_lilly") -> dict[str, Any]:
    plc = load_placement(client_id)
    plc.ensure_drugs()
    return plc.to_dict()


@app.post("/api/placement/clear")
async def reset_placement(client_id: str = "eli_lilly") -> dict[str, Any]:
    return clear_placement(client_id).to_dict()


@app.put("/api/placement")
async def put_placement(body: PlacementBody) -> dict[str, Any]:
    try:
        plc = ResearchAgent(body.client_id).discover_and_apply_placement(
            body.company_name, enabled=body.enabled, refresh=True
        )[1]
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return plc.to_dict()


@app.get("/api/sources")
async def sources() -> list[dict[str, Any]]:
    return [
        {
            "id": c.id,
            "title": c.title,
            "pmid": c.pmid,
            "journal": c.journal,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{c.pmid}/" if c.pmid else None,
        }
        for c in load_chunks()
    ]


@app.post("/api/visits")
async def create_visit(body: Optional[VisitCreate] = None) -> dict[str, str]:
    vid = str(uuid.uuid4())
    _visits[vid] = []
    return {"visit_id": vid, "title": (body.title if body else None) or "New Visit"}


@app.get("/api/visits/{visit_id}")
async def get_visit(visit_id: str) -> dict[str, Any]:
    if visit_id not in _visits:
        raise HTTPException(404, "Visit not found")
    return {"visit_id": visit_id, "messages": _visits[visit_id]}


def _track_chat_answer(client_id: str, question: str, answer: str) -> None:
    try:
        record_chat_exchange(client_id, question, answer)
    except Exception:
        logger.exception("Failed to record chat exchange for dashboard")


def _prepare_ask(body: AskBody) -> tuple[str, PlacementConfig, SalesRepOrchestrator]:
    _require_ollama(body.client_id)
    visit_id = body.visit_id or str(uuid.uuid4())
    if visit_id not in _visits:
        _visits[visit_id] = []
    _visits[visit_id].append({"role": "user", "content": body.question})
    plc = _placement_from_request(body.client_id, body.company_name, body.use_placement)
    return visit_id, plc, SalesRepOrchestrator(body.client_id)


@app.post("/api/ask")
async def ask(body: AskBody) -> dict[str, Any]:
    visit_id, plc, orch = _prepare_ask(body)
    try:
        result = orch.platform.ask(body.question, placement=plc)
    except Exception as e:
        raise HTTPException(503, f"LLM error: {e}") from e

    _visits[visit_id].append(
        {
            "role": "assistant",
            "content": result.answer,
            "sources": result.sources,
            "status": result.status,
            "placement": plc.to_dict(),
        }
    )
    _track_chat_answer(body.client_id, body.question, result.answer)
    return {
        "visit_id": visit_id,
        "answer": result.answer,
        "sources": result.sources,
        "status": result.status,
        "placement": plc.to_dict(),
    }


@app.post("/api/ask/stream")
async def ask_stream(body: AskBody) -> StreamingResponse:
    visit_id, plc, orch = _prepare_ask(body)

    def sse_events():
        answer_parts: list[str] = []
        try:
            stream, sources = orch.platform.ask_stream(body.question, placement=plc)
            for token in stream:
                answer_parts.append(token)
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            answer = "".join(answer_parts)
            _visits[visit_id].append(
                {
                    "role": "assistant",
                    "content": answer,
                    "sources": sources,
                    "status": "finished",
                    "placement": plc.to_dict(),
                }
            )
            _track_chat_answer(body.client_id, body.question, answer)
            yield f"data: {json.dumps({'type': 'done', 'visit_id': visit_id, 'sources': sources, 'placement': plc.to_dict()})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        sse_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/audit/run")
async def run_audit(client_id: str = "eli_lilly") -> dict[str, Any]:
    _require_ollama(client_id)
    try:
        scores, run_id = SalesRepOrchestrator(client_id).audit_and_save()
    except Exception as e:
        raise HTTPException(503, str(e)) from e
    plc = load_placement(client_id)
    return {
        "run_id": run_id,
        "prompts": len(scores),
        "company": plc.company_name,
        "drugs": [d.brand for d in (plc.drugs or [])],
        "summary": {
            "favorable": sum(1 for s in scores if s.favorability == "favorable"),
            "neutral": sum(1 for s in scores if s.favorability == "neutral"),
            "unfavorable": sum(1 for s in scores if s.favorability == "unfavorable"),
            "absent": sum(1 for s in scores if s.favorability == "absent"),
        },
    }


@app.get("/api/audit/history")
async def audit_history(client_id: str = "eli_lilly") -> dict[str, Any]:
    return dashboard_series(client_id)


@app.get("/api/audit/runs")
async def audit_runs(client_id: str = "eli_lilly") -> list[dict[str, Any]]:
    return list_runs(client_id)
