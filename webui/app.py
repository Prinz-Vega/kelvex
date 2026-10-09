"""Dashboard für Phase 1 ("Sichtbarkeit") aus KELVEX_ROADMAP.md: zeigt, welche lokalen
Prozesse mit bekannten KI-/LLM-API-Diensten sprechen. Erster echter Baustein der später
geplanten "Web-GUI (Verwaltung)".

Rudimentäre, aber sichere Admin-Authentifizierung (siehe core/auth.py): ein einzelnes
Passwort, bei der Ersteinrichtung erzwungen (/setup), danach Session-Cookie-Login
(/login). Betrifft NUR die Dashboard-UI/Admin-API -- die Agenten-Endpunkte
(/api/agent/register, /api/agent/report, /api/agent/verify-otp) und die
Download-/Installer-Routen bleiben absichtlich ohne Session-Login erreichbar, da
Agenten sich über ihr eigenes Bearer-Token authentifizieren, nicht über eine
Browser-Session (siehe OPEN_ENDPOINTS unten).

Reiner Lesezugriff auf die Detections-Tabelle -- der Sampler läuft im lokalen Agenten
(desktop_agent/tray.py, der "Desktop-GUI (Endpoint-Agent)" aus der Roadmap), der sich
über den Registrierungsfluss unten (/api/agent/register, /api/agent/report) authentifiziert
meldet, nicht mehr direkt in eine gemeinsame Datei schreibt -- echte Client-Server-Trennung,
kein gemeinsamer Rechner mehr vorausgesetzt.

Getrennt von deploy/site/ (die öffentliche, rein statische Projektseite) -- dieses hier
ist die tatsächliche Kelvex-Anwendung, nicht die Marketing-Seite."""
from __future__ import annotations

import io
import secrets
import sys
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402
from flask import (  # noqa: E402
    Flask, Response, jsonify, make_response, redirect, render_template, request, send_file, session, url_for,
)

import core.auth as auth  # noqa: E402
import core.version  # noqa: E402
from config.settings import DB_FILE  # noqa: E402
from core.licensing.fingerprint import HardwareIdUnavailableError, compute_hardware_id  # noqa: E402
from core.licensing.license_data import looks_like_unban_certificate  # noqa: E402
from core.licensing.storage import (  # noqa: E402
    ban_hardware, clear_hardware_ban, delete_installed_license, is_hardware_banned,
    load_installed_license, save_installed_license,
)
from core.licensing.verifier import (  # noqa: E402
    LicenseStatus, effective_seat_limit, verify_license, verify_unban_certificate,
)
from core.memory.database import Database  # noqa: E402
from core.update_apply import UpdateApplyError, apply_update_zip  # noqa: E402
from core.updater import check_for_update, is_newer  # noqa: E402
from dataclasses import asdict  # noqa: E402
from desktop_agent._version import __version__ as CURRENT_AGENT_VERSION  # noqa: E402
from webui.i18n import SUPPORTED_LANGUAGES, t  # noqa: E402

# UI-Polling-Intervall -- zeigt neue, vom Agenten erkannte Treffer zügig an.
DASHBOARD_REFRESH_SECONDS = 10

LANG_COOKIE = "lang"
LANG_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

# Admin-OTP für lokale Agent-Einstellungen (siehe desktop_agent/setup_dialog.py::ask_otp()).
OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 10
OTP_ATTEMPT_WINDOW_SECONDS = 300
# In-Memory, bei Core-Neustart zurückgesetzt -- reicht für dieses Bedrohungsmodell (schützt
# vor Erraten durch jemanden mit nur lokalem Zugriff auf den Agent-Rechner, nicht vor einem
# Netzwerk-Angreifer, der das -- ebenfalls auth-lose -- Dashboard selbst erreichen kann und
# sich dort einfach einen frischen Code generieren könnte; das ist kein neues Leck dieser
# Funktion, sondern dieselbe bestehende Vertrauensgrenze wie bei approve/revoke oben).
_otp_attempts: dict[int, list[float]] = {}

# Login-Rate-Limiting (siehe login()) -- analog zum OTP-Versuchszähler oben, nach
# Quell-IP statt Agent-ID, da es hier kein Pendant zu einer Agent-ID gibt (nur EIN
# geteiltes Admin-Passwort, keine Nutzerverwaltung).
LOGIN_MAX_ATTEMPTS = 10
LOGIN_ATTEMPT_WINDOW_SECONDS = 300
_login_attempts: dict[str, list[float]] = {}

# Endpunkte, die OHNE Dashboard-Login erreichbar bleiben müssen: Agenten authentifizieren
# sich über ihr eigenes Bearer-Token (nie über die Browser-Session), die Download-/
# Installer-Routen werden direkt von install.sh/.bat bzw. curl aufgerufen (kein Browser,
# keine Session-Cookies) -- siehe auch Moduldokstring oben.
OPEN_ENDPOINTS = {
    "login", "setup", "logout", "static", "set_lang",
    "api_agent_register", "api_agent_report", "api_agent_verify_otp",
    "download_agent", "install_linux", "install_windows",
}

app = Flask(__name__)
app.secret_key = auth.load_or_create_secret_key()
db = Database(DB_FILE)


@app.before_request
def _require_auth():
    if request.endpoint in OPEN_ENDPOINTS or request.endpoint is None:
        return
    if not auth.has_password():
        return redirect(url_for("setup"))
    if not session.get("authenticated"):
        return redirect(url_for("login", next=request.path))


@app.route("/setup", methods=["GET", "POST"])
def setup():
    """Nur erreichbar, solange noch KEIN Passwort existiert (siehe _require_auth()) --
    danach leitet dieselbe Route auf /login weiter, damit ein direkt aufgerufenes
    /setup nach der Ersteinrichtung nicht versehentlich ein zweites Mal ein Passwort
    setzen lässt."""
    if auth.has_password():
        return redirect(url_for("login"))

    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if len(password) < auth.MIN_PASSWORD_LENGTH:
            error = "password_too_short"
        elif password != confirm:
            error = "password_mismatch"
        else:
            auth.set_password(password)
            session["authenticated"] = True
            return redirect(url_for("dashboard"))

    return render_template("setup.html", error=error, min_length=auth.MIN_PASSWORD_LENGTH)


@app.route("/login", methods=["GET", "POST"])
def login():
    if not auth.has_password():
        return redirect(url_for("setup"))

    error = None
    if request.method == "POST":
        now = time.time()
        ip = request.remote_addr or "unknown"
        attempts = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_ATTEMPT_WINDOW_SECONDS]
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            error = "too_many_attempts"
        else:
            attempts.append(now)
            _login_attempts[ip] = attempts
            if auth.verify_password(request.form.get("password", "")):
                session["authenticated"] = True
                next_path = request.args.get("next")
                return redirect(next_path if next_path else url_for("dashboard"))
            error = "invalid_password"

    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/account", methods=["GET", "POST"])
def account():
    error = None
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm", "")
        if not auth.verify_password(current):
            error = "current_password_wrong"
        elif len(new) < auth.MIN_PASSWORD_LENGTH:
            error = "password_too_short"
        elif new != confirm:
            error = "password_mismatch"
        else:
            auth.set_password(new)
            # Neuer Secret Key -- invalidiert sofort ALLE bestehenden Sessions (auch
            # diese hier), ein kostenloser "überall abmelden"-Effekt bei Passwortwechsel.
            app.secret_key = auth.rotate_secret_key()
            session.clear()
            return redirect(url_for("login"))
    return render_template("account.html", error=error, min_length=auth.MIN_PASSWORD_LENGTH)


def current_lang() -> str:
    """Englisch ist die primäre/Standardsprache (siehe webui/i18n.py) -- nur ein
    gültiges "lang"-Cookie (gesetzt über /lang/<code> unten) schaltet auf Deutsch um."""
    lang = request.cookies.get(LANG_COOKIE, "")
    return lang if lang in SUPPORTED_LANGUAGES else "en"


# Im Template als {{ t('key') }} nutzbar, ohne lang in jedem render_template()-Aufruf
# mitschleppen zu müssen -- current_lang() liest ohnehin nur das Request-Cookie.
app.jinja_env.globals["t"] = lambda key: t(key, current_lang())
app.jinja_env.globals["current_lang"] = current_lang


@app.route("/lang/<code>")
def set_lang(code: str):
    """Setzt das Sprach-Cookie und leitet zur aufrufenden Seite zurück (Fallback: "/"),
    kein Formular-POST nötig -- der Umschalter im Header ist ein einfacher Link."""
    resp = make_response(redirect(request.referrer or "/"))
    if code in SUPPORTED_LANGUAGES:
        resp.set_cookie(LANG_COOKIE, code, max_age=LANG_COOKIE_MAX_AGE, samesite="Lax")
    return resp


@app.route("/")
def dashboard():
    return render_template("dashboard.html", refresh_seconds=DASHBOARD_REFRESH_SECONDS)


@app.route("/api/detections")
def api_detections():
    return jsonify({"detections": db.recent_detected_connections(limit=100)})


# --- Agent-Registrierungsfluss (siehe desktop_agent/tray.py) ------------------

@app.route("/api/agent/register", methods=["POST"])
def api_agent_register():
    """Kein Auth -- das IST der Bootstrap-Schritt. Idempotent: ein bereits bekannter
    client_id-Wert erzeugt keinen neuen Eintrag, liefert nur den aktuellen Status."""
    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id")
    hostname = data.get("hostname", "unbekannt")
    if not client_id:
        return jsonify({"error": "client_id fehlt"}), 400
    result = db.register_agent_request(client_id, hostname)
    return jsonify(result)


@app.route("/api/agent/report", methods=["POST"])
def api_agent_report():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Kein Bearer-Token übermittelt"}), 401
    token = auth[len("Bearer "):]
    agent = db.agent_by_token(token)
    if agent is None:
        return jsonify({"error": "Ungültiges oder widerrufenes Token"}), 403

    data = request.get_json(silent=True) or {}
    detections = data.get("detections", [])
    # Vom Agenten über HTTP gesendete Dicts in dasselbe Format bringen, das
    # log_detected_connections() von core.security.connection_monitor.DetectedConnection
    # erwartet (Attributzugriff per .pid/.process_name/...) -- ein einfaches Namedtuple-
    # ähnliches Objekt reicht, keine echte Dataclass-Instanz nötig.
    conns = [SimpleNamespace(**d) for d in detections]
    db.log_detected_connections(conns, agent_id=agent["id"])
    db.touch_agent_last_seen(agent["id"])

    # Core-gepushte Konfiguration: bewusst bei JEDEM Report-Zyklus erneut ausgeliefert
    # (kein Ack/Pop) -- bleibt bestehen, bis ein Operator sie im Dashboard löscht. Generisch
    # gehalten: der Agent interpretiert nur Schlüssel, die er kennt (aktuell nur "language").
    pending_config = db.get_agent_pending_config(agent["id"]) or {}

    # Agent-Update-Hinweis: der Agent meldet seit dieser Version seine eigene Version mit
    # ("agent_version") -- ältere Agenten, die das Feld noch nicht senden, bekommen nie ein
    # Update signalisiert (harmlos, sie hatten ohnehin noch keine Self-Update-Logik).
    reported_version = data.get("agent_version", "0.0.0")
    update_info = None
    if is_newer(CURRENT_AGENT_VERSION, reported_version):
        update_info = {"version": CURRENT_AGENT_VERSION}

    return jsonify({
        "ok": True,
        "received": len(conns),
        "config": pending_config,
        "update": update_info,
    })


# --- Agentenverwaltung (Dashboard-Seite) ---------------------------------------

@app.route("/agents")
def agents_page():
    return render_template("agents.html")


@app.route("/api/agents")
def api_agents():
    return jsonify({"agents": db.list_agents()})


@app.route("/api/agents/<int:agent_id>/approve", methods=["POST"])
def api_agents_approve(agent_id: int):
    # Freemium-Gate: 1 genehmigter Agent ist immer kostenlos, ab dem 2. braucht es eine
    # gültige Lizenz. Bei JEDEM Genehmigen neu geprüft (kein Hintergrund-Job, kein
    # gecachtes Flag) -- eine abgelaufene/entfernte Lizenz blockiert ab sofort nur NEUE
    # Genehmigungen, bereits genehmigte Agenten werden NICHT automatisch widerrufen.
    seat_limit = effective_seat_limit(verify_license(load_installed_license()))
    approved_count = sum(1 for a in db.list_agents() if a["status"] == "approved")
    if approved_count >= seat_limit:
        return jsonify({
            "error": "license_seat_limit_reached",
            "seat_limit": seat_limit,
            "agents_used": approved_count,
        }), 402

    token = db.approve_agent(agent_id)
    if token is None:
        return jsonify({"error": "Agent nicht gefunden"}), 404
    return jsonify({"ok": True})


@app.route("/api/agents/<int:agent_id>/revoke", methods=["POST"])
def api_agents_revoke(agent_id: int):
    ok = db.revoke_agent(agent_id)
    if not ok:
        return jsonify({"error": "Agent nicht gefunden"}), 404
    return jsonify({"ok": True})


# --- Admin-OTP für lokale Agent-Einstellungen -----------------------------------

@app.route("/api/agents/<int:agent_id>/otp", methods=["POST"])
def api_agents_generate_otp(agent_id: int):
    """Dashboard-seitig, kein Auth (konsistent mit approve/revoke oben). Der Code wird
    dem Operator angezeigt, der ihn außerhalb dieses Systems (mündlich, Chat, o.ä.) an die
    Person am Agent-Rechner weitergibt."""
    if db.agent_by_id(agent_id) is None:
        return jsonify({"error": "Agent nicht gefunden"}), 404
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.generate_agent_otp(agent_id, code, OTP_TTL_SECONDS)
    return jsonify({"code": code, "expires_at": time.time() + OTP_TTL_SECONDS})


@app.route("/api/agent/verify-otp", methods=["POST"])
def api_agent_verify_otp():
    """Agent-seitig, Bearer-Auth wie /api/agent/report -- der Online-Check, den
    desktop_agent/tray.py::_verify_otp_threadsafe() vor dem Öffnen der lokalen
    Einstellungen durchführt."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Kein Bearer-Token übermittelt"}), 401
    token = auth[len("Bearer "):]
    agent = db.agent_by_token(token)
    if agent is None:
        return jsonify({"error": "Ungültiges oder widerrufenes Token"}), 403

    now = time.time()
    attempts = [t for t in _otp_attempts.get(agent["id"], []) if now - t < OTP_ATTEMPT_WINDOW_SECONDS]
    if len(attempts) >= OTP_MAX_ATTEMPTS:
        return jsonify({"ok": False, "error": "Zu viele Versuche, bitte später erneut versuchen"}), 429
    attempts.append(now)
    _otp_attempts[agent["id"]] = attempts

    data = request.get_json(silent=True) or {}
    code = str(data.get("code", ""))
    ok = db.verify_and_consume_agent_otp(agent["id"], code)
    return jsonify({"ok": ok})


# --- Core-gepushte Agent-Konfiguration -------------------------------------------

@app.route("/api/agents/<int:agent_id>/push-config", methods=["POST"])
def api_agents_push_config(agent_id: int):
    if db.agent_by_id(agent_id) is None:
        return jsonify({"error": "Agent nicht gefunden"}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Body muss ein JSON-Objekt sein"}), 400
    db.set_agent_pending_config(agent_id, data)
    return jsonify({"ok": True})


@app.route("/api/agents/<int:agent_id>/push-config/clear", methods=["POST"])
def api_agents_push_config_clear(agent_id: int):
    if db.agent_by_id(agent_id) is None:
        return jsonify({"error": "Agent nicht gefunden"}), 404
    db.clear_agent_pending_config(agent_id)
    return jsonify({"ok": True})


# --- Agent-Download -------------------------------------------------------------

_AGENT_REQUIREMENTS = "psutil>=5.9.0\npystray>=0.19.5\nrequests>=2.31.0\nPillow>=10.0.0\n"

_AGENT_README = """Kelvex Agent -- Installation

1. Python 3.10 oder neuer voraussetzen.
2. In diesem Ordner: pip install -r requirements.txt
3. Starten: python3 desktop_agent/tray.py
4. Beim ersten Start nach der Kelvex-Core-Adresse gefragt (z.B. http://<core-host>:8822).
5. Der Agent erscheint danach im Dashboard unter "Agenten" als "pending" -- dort
   genehmigen, bevor er Daten melden kann.
"""


@app.route("/download/agent")
def download_agent():
    """Baut ein Quellcode-Zip im Speicher -- kein gepacktes Standalone-Executable (siehe
    Plan: bewusst außerhalb des Umfangs dieser Runde). desktop_agent/ + die beiden
    core/security/-Module, die es tatsächlich importiert, plus __init__.py-Stubs, damit
    die relativen Importe nach dem Entpacken funktionieren."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        agent_dir = PROJECT_ROOT / "desktop_agent"
        for py_file in agent_dir.glob("*.py"):
            zf.write(py_file, f"desktop_agent/{py_file.name}")
        # Tray-Icon -- tray.py lädt es zur Laufzeit (ICON_PATH), muss also mit ins Zip.
        zf.write(agent_dir / "agent_icon.png", "desktop_agent/agent_icon.png")
        # i18n-Locale-Dateien -- i18n.py::t() lädt sie zur Laufzeit, ohne sie bricht der
        # heruntergeladene Agent beim ersten t()-Aufruf.
        for locale_file in (agent_dir / "locales").glob("*.json"):
            zf.write(locale_file, f"desktop_agent/locales/{locale_file.name}")

        zf.write(PROJECT_ROOT / "core" / "__init__.py", "core/__init__.py")
        zf.write(PROJECT_ROOT / "core" / "security" / "__init__.py", "core/security/__init__.py")
        zf.write(
            PROJECT_ROOT / "core" / "security" / "connection_monitor.py",
            "core/security/connection_monitor.py",
        )
        zf.write(
            PROJECT_ROOT / "core" / "security" / "llm_endpoints.py",
            "core/security/llm_endpoints.py",
        )

        zf.writestr("requirements.txt", _AGENT_REQUIREMENTS)
        zf.writestr("README.txt", _AGENT_README)

    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="kelvex-agent.zip",
    )


# --- One-Click-Installer ---------------------------------------------------------
#
# Statt des rohen Quellcode-Zips (download_agent() oben, bleibt als manuelle/
# Fallback-Option erreichbar) bekommt der Nutzer hier je ein einzelnes, selbstständiges
# Skript pro Plattform: lädt den Agenten von GENAU DIESEM Core-Server (request.host_url
# -- derselbe Host, über den das Skript gerade heruntergeladen wurde) herunter,
# installiert Abhängigkeiten, trägt die Core-Adresse vorab in agent_config.json ein
# (via desktop_agent/_seed_config.py -- macht den Erststart-Einrichtungsdialog
# überflüssig) und startet den Agenten sofort, inkl. Autostart-Eintrag.

_LINUX_INSTALL_SH = """#!/usr/bin/env bash
set -euo pipefail
CORE_URL="__CORE_URL__"
INSTALL_DIR="$HOME/.local/share/kelvex-agent"

echo "=== Kelvex Agent Installer ==="

command -v python3 >/dev/null 2>&1 || {
    echo "python3 wurde nicht gefunden. Bitte Python 3.10+ installieren und erneut starten." >&2
    exit 1
}

mkdir -p "$INSTALL_DIR"
TMP_ZIP="$(mktemp /tmp/kelvex-agent.XXXXXX.zip)"
trap 'rm -f "$TMP_ZIP"' EXIT

echo "Lade Agent von $CORE_URL ..."
if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$CORE_URL/download/agent" -o "$TMP_ZIP"
elif command -v wget >/dev/null 2>&1; then
    wget -qO "$TMP_ZIP" "$CORE_URL/download/agent"
else
    echo "Weder curl noch wget gefunden." >&2
    exit 1
fi

python3 -c "import zipfile, sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$TMP_ZIP" "$INSTALL_DIR"

# Laufende Instanz stoppen (PID-Datei statt pkill -f-Substring-Match -- robuster,
# plattformübergreifend einheitlich, siehe desktop_agent/tray.py::PID_FILE). Nötig,
# wenn ein Admin dieses Skript manuell gegen einen noch laufenden Agenten erneut
# ausführt -- beim automatischen Self-Update (desktop_agent/self_update.py) hat sich
# der alte Prozess bereits selbst beendet, bevor dieses Skript hier läuft, daher meist
# ein No-Op, aber als Absicherung immer ausgeführt.
PID_FILE="$HOME/.config/kelvex/agent.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Beende laufende Agent-Instanz (PID $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

echo "Richte virtuelle Umgebung ein..."
# Eigenes venv statt "pip install --user" -- auf Debian/Ubuntu 12+ ("externally-managed-
# environment", PEP 668) schlägt --user sonst fehl, ohne venv müsste der Nutzer sich
# selbst um die passende --break-system-packages-Umgehung kümmern.
python3 -m venv "$INSTALL_DIR/.venv"
VENV_PY="$INSTALL_DIR/.venv/bin/python3"

echo "Installiere Abhängigkeiten..."
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r "$INSTALL_DIR/requirements.txt"

echo "Trage Kelvex-Core-Adresse ein..."
"$VENV_PY" "$INSTALL_DIR/desktop_agent/_seed_config.py" "$CORE_URL"

mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/kelvex-agent.desktop" <<AUTOSTART
[Desktop Entry]
Type=Application
Name=Kelvex Agent
Exec=$VENV_PY "$INSTALL_DIR/desktop_agent/tray.py"
X-GNOME-Autostart-enabled=true
AUTOSTART

echo "Starte Kelvex Agent..."
nohup "$VENV_PY" "$INSTALL_DIR/desktop_agent/tray.py" >/dev/null 2>&1 &
disown || true

echo ""
echo "Fertig. Freigabe erteilen unter: $CORE_URL/agents"
"""

_WINDOWS_INSTALL_BAT = """@echo off
setlocal
set "CORE_URL=__CORE_URL__"
set "INSTALL_DIR=%LOCALAPPDATA%\\KelvexAgent"

echo === Kelvex Agent Installer ===

where python >nul 2>nul
if errorlevel 1 (
    echo Python wurde nicht gefunden. Bitte Python 3.10+ von https://python.org installieren und erneut starten.
    pause
    exit /b 1
)

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

echo Lade Agent von %CORE_URL% ...
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%CORE_URL%/download/agent' -OutFile '%TEMP%\\kelvex-agent.zip'"
if errorlevel 1 (
    echo Download fehlgeschlagen.
    pause
    exit /b 1
)

powershell -NoProfile -Command "Expand-Archive -Path '%TEMP%\\kelvex-agent.zip' -DestinationPath '%INSTALL_DIR%' -Force"
del "%TEMP%\\kelvex-agent.zip"

REM Laufende Instanz stoppen (PID-Datei statt Prozessname -- robuster, siehe
REM desktop_agent/tray.py::PID_FILE). Nutzt die bereits im System vorhandene
REM Python-Installation (gerade erst oben geprueft), kein neues Werkzeug noetig.
set "PID_FILE=%USERPROFILE%\\.config\\kelvex\\agent.pid"
if exist "%PID_FILE%" (
    for /f %%P in ('type "%PID_FILE%"') do taskkill /F /PID %%P >nul 2>&1
    del "%PID_FILE%" >nul 2>&1
)

echo Installiere Abhaengigkeiten...
python -m pip install --quiet --user -r "%INSTALL_DIR%\\requirements.txt"

echo Trage Kelvex-Core-Adresse ein...
python "%INSTALL_DIR%\\desktop_agent\\_seed_config.py" "%CORE_URL%"

echo Richte Autostart ein...
set "STARTUP=%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup"
> "%STARTUP%\\Kelvex Agent.bat" echo @echo off
>> "%STARTUP%\\Kelvex Agent.bat" echo start "" /b pythonw "%INSTALL_DIR%\\desktop_agent\\tray.py"

echo Starte Kelvex Agent...
start "" /b pythonw "%INSTALL_DIR%\\desktop_agent\\tray.py"

echo.
echo Fertig. Freigabe erteilen unter: %CORE_URL%/agents
pause
"""


@app.route("/install/linux")
def install_linux():
    core_url = request.host_url.rstrip("/")
    script = _LINUX_INSTALL_SH.replace("__CORE_URL__", core_url)
    return Response(
        script,
        mimetype="text/x-sh",
        headers={"Content-Disposition": "attachment; filename=kelvex-agent-install.sh"},
    )


@app.route("/install/windows")
def install_windows():
    core_url = request.host_url.rstrip("/")
    script = _WINDOWS_INSTALL_BAT.replace("__CORE_URL__", core_url)
    return Response(
        script,
        mimetype="application/bat",
        headers={"Content-Disposition": "attachment; filename=kelvex-agent-install.bat"},
    )


# --- Core-Selbst-Update (online + offline) ---------------------------------------
#
# Prüfung bleibt core/updater.py (unverändert) -- hier kommt nur das tatsächliche
# ANWENDEN eines Updates dazu, siehe core/update_apply.py für die Begründung, warum das
# ein separater Mechanismus vom Agent-Self-Update ist. Startet NIE automatisch neu
# (bestätigte Nutzerentscheidung) -- die Dashboard-Seite zeigt danach ein "Neustart
# erforderlich"-Banner mit dem zur laufenden Plattform passenden Befehl.

@app.route("/updates")
def updates_page():
    return render_template(
        "updates.html",
        current_version=core.version.__version__,
        is_windows=(sys.platform == "win32"),
    )


@app.route("/api/core/update/check")
def api_core_update_check():
    info = check_for_update(core.version.__version__)
    if info is None:
        return jsonify({"available": False})
    return jsonify({
        "available": True,
        "version": info.version,
        "page_url": info.page_url,
        "zip_url": info.zip_url,
        "zip_size_mb": info.zip_size_mb,
    })


@app.route("/api/core/update/apply-online", methods=["POST"])
def api_core_update_apply_online():
    # Die Zip-URL wird NICHT aus dem Request übernommen, sondern hier serverseitig neu
    # ermittelt -- das Dashboard hat kein Auth, ein beliebiger Netzwerk-Client dürfte sonst
    # eine beliebige URL zum Herunterladen+Entpacken unterschieben.
    info = check_for_update(core.version.__version__)
    if info is None or not info.zip_url:
        return jsonify({"ok": False, "error": "Kein Update verfügbar"}), 400
    try:
        resp = requests.get(info.zip_url, timeout=60)
        resp.raise_for_status()
        new_version = apply_update_zip(io.BytesIO(resp.content))
    except (requests.RequestException, UpdateApplyError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True, "applied_version": new_version})


@app.route("/api/core/update/apply-upload", methods=["POST"])
def api_core_update_apply_upload():
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"ok": False, "error": "Keine Datei übermittelt"}), 400
    try:
        new_version = apply_update_zip(uploaded.stream)
    except UpdateApplyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "applied_version": new_version})


# --- Lizenzierung -----------------------------------------------------------------
#
# Vollständig offline geprüft (Ed25519-Signatur gegen core/licensing/public_key.py,
# siehe dort für die Begründung) -- kein Lizenzserver, kein Netzwerkaufruf. 1 genehmigter
# Agent ist immer kostenlos (siehe api_agents_approve() oben), ab dem 2. braucht es eine
# gültige, hier aktivierte Lizenz.

@app.route("/licenses")
def licenses_page():
    return render_template("licenses.html")


@app.route("/api/license/status")
def api_license_status():
    try:
        hw_id = compute_hardware_id()
    except HardwareIdUnavailableError:
        hw_id = None
    banned = is_hardware_banned()
    result = verify_license(load_installed_license())
    approved_count = sum(1 for a in db.list_agents() if a["status"] == "approved")
    return jsonify({
        "hardware_id": hw_id,
        "banned": banned,
        "status": result.status.value,
        "license": asdict(result.license) if result.license else None,
        "days_remaining": result.days_remaining,
        "seat_limit": effective_seat_limit(result),
        "agents_used": approved_count,
    })


@app.route("/api/license/activate", methods=["POST"])
def api_license_activate():
    """Body = das eingefügte/hochgeladene signierte JSON -- entweder eine Lizenz oder ein
    Entsperr-Zertifikat (siehe license_data.py::looks_like_unban_certificate()), beide
    teilen denselben Einfüge-Kasten im Dashboard, da beide klein genug für eine
    Textarea sind und strukturell eindeutig unterscheidbar bleiben.

    Validiert VOLLSTÄNDIG lokal (Signatur, Hardware, Ablauf) VOR dem Speichern -- eine
    ungültige Lizenz wird nie auf Platte geschrieben.

    Manipulationssperre: eine erkannte Signatur-Manipulation bei einer LIZENZ (ein JSON,
    dessen Inhalt nicht zu seiner Signatur passt -- kann nur durch absichtliches
    Verändern entstehen, niemals durch Zufall) sperrt diese Installation PERMANENT für
    jede künftige Aktivierung, auch eine später korrekt ausgestellte, gültige Lizenz.
    Eine abgelaufene oder auf eine andere Maschine ausgestellte Lizenz löst KEINE Sperre
    aus -- das ist kein Beweis für Manipulation (siehe storage.py::ban_hardware()). Ein
    gültiges Entsperr-Zertifikat hebt die Sperre wieder auf -- es gibt dafür absichtlich
    KEINEN Dashboard-Button, nur dieser signierte Weg (siehe clear_hardware_ban())."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "malformed"}), 400

    if looks_like_unban_certificate(data):
        if verify_unban_certificate(data):
            clear_hardware_ban()
            return jsonify({"ok": True, "unbanned": True})
        return jsonify({"ok": False, "error": "invalid_unban_certificate"}), 400

    if is_hardware_banned():
        return jsonify({"ok": False, "error": "hardware_banned"}), 403

    result = verify_license(data)
    if result.status == LicenseStatus.INVALID_SIGNATURE:
        ban_hardware("Manipulierte Lizenz bei Aktivierung erkannt (Signatur ungültig).")
        return jsonify({"ok": False, "error": "hardware_banned"}), 403
    if result.status != LicenseStatus.VALID:
        return jsonify({"ok": False, "error": result.status.value}), 400
    save_installed_license(data)
    return jsonify({"ok": True})


@app.route("/api/license/deactivate", methods=["POST"])
def api_license_deactivate():
    delete_installed_license()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8822, debug=False)
