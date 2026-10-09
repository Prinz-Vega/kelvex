"""Persistenz der installierten Lizenz -- selbe Konvention wie config/settings.py und
desktop_agent/agent_config.py: flache JSON-Datei unter ~/.config/kelvex/, chmod 0600,
fehlende/korrupte Datei wird als "nichts installiert" behandelt, nicht als Fehler.

Reines I/O -- liefert/speichert das ROHE dict inklusive "signature". Prüfen ist Aufgabe
von verifier.py::verify_license(), nicht dieses Moduls.

Enthält außerdem die lokale Manipulationssperre (siehe ban_hardware()): bewusst NUR
lokal, kein serverseitiger Permaban (das würde einen Netzwerkaufruf bei jeder
Aktivierung erfordern, der Lizenzprüfung soll aber vollständig offline bleiben, siehe
verifier.py-Docstring). Eine lokale Sperre übersteht keinen manuellen Reset von
~/.config/kelvex/ durch einen hinreichend entschlossenen Angreifer mit Dateisystem-
Zugriff -- das ist eine bekannte, akzeptierte Grenze rein lokaler Anti-Tamper-
Maßnahmen, kein Implementierungsfehler."""
from __future__ import annotations

import json
import os
import stat
import time
from typing import Optional

from config.settings import CONFIG_DIR

LICENSE_FILE = CONFIG_DIR / "license.json"
BAN_FILE = CONFIG_DIR / "license_banned.json"


def load_installed_license() -> Optional[dict]:
    try:
        with open(LICENSE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def save_installed_license(signed_license_dict: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LICENSE_FILE, "w", encoding="utf-8") as fh:
        json.dump(signed_license_dict, fh, indent=2)
    try:
        os.chmod(LICENSE_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def delete_installed_license() -> None:
    try:
        LICENSE_FILE.unlink()
    except OSError:
        pass  # bereits entfernt oder nie installiert -- idempotent


def is_hardware_banned() -> bool:
    return BAN_FILE.exists()


def clear_hardware_ban() -> None:
    """Nur über ein gültiges, auf diese Maschine ausgestelltes UnbanCertificate erreichbar
    (siehe webui/app.py::api_license_activate(), verifier.py::verify_unban_certificate())
    -- es gibt bewusst keinen Dashboard-Button dafür, das würde die Sperre entwerten."""
    try:
        BAN_FILE.unlink()
    except OSError:
        pass


def ban_hardware(reason: str) -> None:
    """Permanent (bis zum manuellen Löschen der Datei durch jemanden mit
    Dateisystem-Zugriff, siehe Modul-Docstring) -- einmal gesetzt, lehnt
    api_license_activate() JEDE künftige Aktivierung ab, auch eine später korrekt
    ausgestellte, gültige Lizenz. Wird NUR bei erkannter Signatur-Manipulation
    aufgerufen (siehe webui/app.py::api_license_activate()), nicht bei abgelaufener
    oder auf eine andere Maschine ausgestellter Lizenz -- beides ist kein Beweis für
    Manipulation, nur für Ablauf bzw. falsche Zielmaschine."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(BAN_FILE, "w", encoding="utf-8") as fh:
        json.dump({"banned_at": time.time(), "reason": reason}, fh, indent=2)
    try:
        os.chmod(BAN_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
