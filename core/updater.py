"""Auto-Update-Prüfung gegen kelvex.arrakiz.net (deploy/site/api/latest.php).

Bewusst NUR Prüfen + Melden -- kein automatisches Herunterladen oder Ersetzen
laufender Programmdateien. Ein Selbst-Updater, der die eigenen, gerade
ausgeführten Dateien überschreibt, ist deutlich riskanter (venv/Abhängigkeiten
könnten sich geändert haben, Neustart-Logik nötig) und passt nicht zum
"nichts ohne Bestätigung"-Sicherheitsprinzip des Projekts (siehe
core/security/warden.py, disclaimer.php) -- der Nutzer entscheidet selbst,
wann und wie eine neue Version installiert wird.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import requests

UPDATE_CHECK_URL = "https://kelvex.arrakiz.net/api/latest.php"
TIMEOUT = 6


@dataclass
class UpdateInfo:
    version: str
    page_url: str
    zip_url: Optional[str] = None
    zip_size_mb: Optional[float] = None
    flatpak_url: Optional[str] = None
    flatpak_size_mb: Optional[float] = None


def _version_tuple(v: str) -> tuple[int, ...]:
    """Extrahiert die numerischen X.Y.Z-Teile einer Versionsangabe wie
    '0.11.0-beta' -- Pre-Release-Tags (-alpha/-beta) werden für den Vergleich
    ignoriert, da die numerische Version zwischen Releases ohnehin durchgängig
    steigt (siehe CHANGELOG.md), auch über Alpha/Beta-Übergänge hinweg."""
    m = re.match(r"\d+(?:\.\d+)*", v.strip())
    if not m:
        return (0,)
    return tuple(int(p) for p in m.group(0).split("."))


def is_newer(remote_version: str, current_version: str) -> bool:
    return _version_tuple(remote_version) > _version_tuple(current_version)


def check_for_update(current_version: str) -> Optional[UpdateInfo]:
    """Gibt UpdateInfo zurück, wenn auf der Webseite eine neuere Version als
    current_version verfügbar ist, sonst None. Wirft nie -- ein Update-Check
    ist ein Nice-to-have und darf App-Start/-Betrieb nie stören (Netzwerk-
    fehler, Timeout, kaputtes JSON etc. werden alle als 'kein Update' behandelt)."""
    try:
        resp = requests.get(UPDATE_CHECK_URL, timeout=TIMEOUT)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    remote_version = data.get("version")
    if not remote_version or not is_newer(remote_version, current_version):
        return None

    zip_info = data.get("zip") or {}
    flatpak_info = data.get("flatpak") or {}
    return UpdateInfo(
        version=remote_version,
        page_url=data.get("page_url") or "https://kelvex.arrakiz.net/index.php#download",
        zip_url=zip_info.get("url"),
        zip_size_mb=zip_info.get("size_mb"),
        flatpak_url=flatpak_info.get("url"),
        flatpak_size_mb=flatpak_info.get("size_mb"),
    )
