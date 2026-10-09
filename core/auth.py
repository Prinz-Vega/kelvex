"""Rudimentäre, aber sichere Dashboard-Authentifizierung für Kelvex Core: ein einzelnes
Admin-Passwort (kein Nutzerverwaltungssystem), gehasht mit Werkzeugs
generate_password_hash (scrypt, bereits Flask-Abhängigkeit, kein neues Paket nötig).

Bewusst getrennt vom Bearer-Token-Fluss der Agenten (/api/agent/*) -- das hier schützt
NUR die Dashboard-UI/Admin-API vor Netzwerkzugriff ohne Anmeldung, Agenten
authentifizieren sich weiterhin über ihr eigenes Token, nie über diese Session.

Persistenz wie config/settings.py/desktop_agent/agent_config.py: flache JSON-Datei
unter ~/.config/kelvex/, chmod 0600."""
from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

from config.settings import CONFIG_DIR

AUTH_FILE = CONFIG_DIR / "auth.json"
SECRET_KEY_FILE = CONFIG_DIR / "secret_key"

MIN_PASSWORD_LENGTH = 8


def _write_private(path: Path, data: bytes) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def has_password() -> bool:
    """False vor der Ersteinrichtung -- webui/app.py leitet in diesem Fall JEDE Route
    (außer /setup selbst) auf /setup um, statt mit einem leeren/Standard-Passwort
    nutzbar zu sein."""
    return AUTH_FILE.is_file()


def set_password(password: str) -> None:
    """Wird sowohl bei der Ersteinrichtung (/setup) als auch bei einer späteren
    Passwortänderung (/account) aufgerufen. Validierung der Mindestlänge ist Aufgabe
    des Aufrufers (siehe webui/app.py), diese Funktion schreibt bedingungslos."""
    data = {"password_hash": generate_password_hash(password)}
    _write_private(AUTH_FILE, json.dumps(data).encode("utf-8"))


def verify_password(password: str) -> bool:
    if not AUTH_FILE.is_file():
        return False
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    password_hash = data.get("password_hash")
    if not password_hash:
        return False
    return check_password_hash(password_hash, password)


def load_or_create_secret_key() -> bytes:
    """Flasks app.secret_key -- signiert die Session-Cookies. Einmal erzeugt, persistent
    über Neustarts hinweg (sonst würde jeder Core-Neustart alle Sessions invalidieren).
    Wird bewusst bei jeder Passwortänderung NEU erzeugt (siehe webui/app.py::account()),
    um alle bestehenden Sessions sofort ungültig zu machen -- ein einfacher, kostenloser
    "überall abmelden"-Effekt."""
    if SECRET_KEY_FILE.is_file():
        return SECRET_KEY_FILE.read_bytes()
    key = secrets.token_bytes(32)
    _write_private(SECRET_KEY_FILE, key)
    return key


def rotate_secret_key() -> bytes:
    key = secrets.token_bytes(32)
    _write_private(SECRET_KEY_FILE, key)
    return key
