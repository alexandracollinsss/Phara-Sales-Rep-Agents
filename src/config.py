from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config" / "clients"
PROMPTS_DIR = ROOT / "prompts"
CORPUS_DIR = ROOT / "data" / "corpus"


def load_client(client_id: str) -> dict[str, Any]:
    path = CONFIG_DIR / f"{client_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Unknown client: {client_id} ({path})")
    with path.open() as f:
        return yaml.safe_load(f)


def load_audit_battery() -> list[dict[str, str]]:
    path = PROMPTS_DIR / "audit_battery.yaml"
    with path.open() as f:
        data = yaml.safe_load(f)
    return data["prompts"]


def load_corpus() -> str:
    parts: list[str] = []
    for p in sorted(CORPUS_DIR.glob("*.md")):
        parts.append(p.read_text())
    return "\n\n".join(parts)
