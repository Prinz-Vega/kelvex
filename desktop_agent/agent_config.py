"""Persistente Konfiguration des Kelvex Agent (Core-Adresse, Client-ID, Token) --
eigenständig von config/settings.py (dem Kelvex-Core-Backend), da der Agent als
separates, herunterladbares Paket läuft (siehe webui/app.py::download_agent()) und
nicht von der vollen Core-Konfiguration abhängen soll."""
from __future__ import annotations

import json
import os
import stat
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".config" / "kelvex"
CONFIG_FILE = CONFIG_DIR / "agent.json"


@dataclass
class AgentConfig:
    core_url: str = ""
    # Einmal per uuid4() erzeugt, überlebt Neustarts -- identifiziert diesen Agenten
    # gegenüber Kelvex Core beim Registrieren (core_url + client_id + hostname),
    # unabhängig vom Token (das erst nach Freigabe existiert).
    client_id: str = ""
    # None bis ein Operator den Agenten im Dashboard genehmigt hat (siehe
    # webui/app.py::api_agents_approve()).
    token: Optional[str] = None
    # "en" (primäre Sprache) oder "de" (sekundär) -- siehe i18n.py. Englisch als
    # Standard, nicht Deutsch, obwohl der Code-Kommentar-Stil im Projekt Deutsch ist --
    # bewusste Nutzer/Entwickler-Trennung, siehe core/i18n.py::REFERENCE_LANGUAGE für
    # dieselbe Begründung an anderer Stelle im Projekt.
    language: str = "en"

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2, ensure_ascii=False)
        try:
            os.chmod(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    @classmethod
    def load(cls) -> "AgentConfig":
        if not CONFIG_FILE.exists():
            cfg = cls(client_id=str(uuid.uuid4()))
            cfg.save()
            return cfg
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            data = {}
        known_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        cfg = cls(**filtered)
        if not cfg.client_id:
            cfg.client_id = str(uuid.uuid4())
            cfg.save()
        return cfg
