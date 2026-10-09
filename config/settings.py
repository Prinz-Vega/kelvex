"""Gemeinsame Konfigurationspfade für Kelvex Core und den Kelvex Agent -- beide legen
ihre jeweiligen Dateien (memory.db, license.json, agent.json, ...) unter demselben
~/.config/kelvex/-Verzeichnis ab."""
from __future__ import annotations

from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "kelvex"
DB_FILE = CONFIG_DIR / "memory.db"
