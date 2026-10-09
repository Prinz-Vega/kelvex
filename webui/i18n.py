"""Leichtgewichtiges i18n für das Dashboard (webui/): lädt locales/<sprache>.json,
Punkt-Pfad-Lookup (z.B. "nav.dashboard"). Englisch ist die primäre/Standardsprache,
Deutsch sekundär -- Sprache lebt im Cookie "lang" (siehe app.py), nicht in einer
Nutzerdatenbank (kein Auth auf dem Dashboard, siehe app.py-Docstring).

Kein Flask-Babel, kein Build-Schritt -- dasselbe Muster wie desktop_agent/i18n.py und
deploy/site/assets/i18n.js (drei getrennte, bewusst unabhängige Implementierungen
derselben einfachen Idee, je Rendering-Technologie)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
REFERENCE_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "de")

_cache: dict[str, dict[str, Any]] = {}


def _load(lang: str) -> dict[str, Any]:
    if lang not in _cache:
        path = LOCALES_DIR / f"{lang}.json"
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _cache[lang] = json.load(fh)
        except (OSError, json.JSONDecodeError):
            _cache[lang] = {}
    return _cache[lang]


def t(key: str, lang: str = REFERENCE_LANGUAGE) -> str:
    """Punkt-Pfad-Lookup. Fällt auf REFERENCE_LANGUAGE zurück, wenn der Key in `lang`
    fehlt; liefert "⟨key⟩" als sichtbaren Platzhalter, wenn der Key in GAR keiner
    Sprache existiert -- macht fehlende Übersetzungen sofort sichtbar statt sie
    stillschweigend leer zu lassen."""
    for candidate in (lang, REFERENCE_LANGUAGE):
        node: Any = _load(candidate)
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if isinstance(node, str):
            return node
    return f"⟨{key}⟩"
