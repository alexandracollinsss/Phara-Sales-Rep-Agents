from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.config import load_client
from src.ollama import OllamaClient


class BaseAgent(ABC):
    """Shared Ollama + client config for all agents."""

    name: str = "base"

    def __init__(self, client_id: str = "eli_lilly"):
        self.client_id = client_id
        self.client = load_client(client_id)
        audit = self.client["audit"]
        self.ollama = OllamaClient(
            base_url=audit.get("ollama_base_url", "http://127.0.0.1:11434"),
            model=audit.get("model", "llama3.2"),
        )

    def company_name(self) -> str:
        return self.client["company"]["name"]

    @abstractmethod
    def describe(self) -> str:
        ...
