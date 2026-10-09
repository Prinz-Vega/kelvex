"""Kelvex Agent (Systemtray) -- der "Desktop-GUI (Endpoint-Agent)" aus
KELVEX_ROADMAP.md: "Lokaler Client auf überwachten Geräten (Windows/Linux) — zeigt
Agent-Status, lokale Meldungen, einfache Kontrollen", bewusst "reduziert, unaufdringlich"
im Hintergrund laufend -- kein Fenster, kein Chat, nur Tray-Icon + Menü + Benachrichtigungen.

Meldet Erkennungen per HTTP an Kelvex Core (core_url aus agent_config.py), nicht mehr in
eine gemeinsame lokale Datei -- echte Client-Server-Trennung, kein gemeinsamer Rechner mit
dem Dashboard mehr vorausgesetzt. Muss von einem Operator im Dashboard unter /agents erst
freigegeben werden, bevor Meldungen angenommen werden (siehe Registrierungsfluss unten).

Bekannte Einschränkung: GNOME Shell zeigt AppIndicator-/StatusNotifierItem-Tray-Icons
(die pystray auf Linux nutzt) nur mit einer zusätzlichen Shell-Extension an -- Sampler,
Registrierung, Benachrichtigungen und Menü-Aktionen funktionieren unabhängig davon, nur
das Icon selbst ist auf manchen Linux-Desktops ggf. nicht sichtbar.

Benachrichtigungen sind ein eigenes, im Kelvex-Design gehaltenes Toast-Fenster (tkinter),
keine generische OS-Benachrichtigung -- plyer/native Toasts übernehmen weder die
Markenfarben noch das Logo. Das erzwingt eine Besonderheit im Threading-Modell: pystray
und tkinter wollen beide die Haupt-Event-Schleife des Prozesses besitzen. Lösung:
pystray läuft über icon.run_detached() in einem eigenen Hintergrund-Thread, tkinter
bekommt die Hauptschleife (root.mainloop()) -- JEDE tkinter-Interaktion, die aus einem
pystray-Menü-Callback oder dem Sampler-Thread heraus ausgelöst wird (Popup, Einstellungen-
Dialog), muss über root.after(0, ...) auf den Haupt-Thread umgeleitet werden. Direktes
Erzeugen/Anfassen von tkinter-Widgets aus einem anderen Thread erzeugt keinen Fehler,
sondern ein Fenster, das zwar erscheint, aber dessen Klicks nie verarbeitet werden (zwei
nebenläufige Tcl-Event-Schleifen statt einer) -- genau dieser Bug trat zuerst beim
"Einstellungen…"-Menüpunkt auf, siehe _ask_core_url_threadsafe().

Sprache: Englisch primär, Deutsch sekundär (siehe i18n.py). Die aktuell gewählte Sprache
lebt im Modul-Global _current_lang statt bei jedem Menü-Rendern agent_config.json neu zu
lesen -- wird beim Start aus der Config übernommen und bei einem Sprachwechsel im
Einstellungen-Dialog sofort aktualisiert (siehe _open_settings())."""
from __future__ import annotations

import os
import socket
import sys
import threading
import tkinter as tk
import webbrowser
from dataclasses import asdict
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pystray  # noqa: E402
import requests  # noqa: E402
from PIL import Image, ImageTk  # noqa: E402

from core.security.connection_monitor import sample_once  # noqa: E402
from desktop_agent import self_update  # noqa: E402
from desktop_agent.agent_config import AgentConfig  # noqa: E402
from desktop_agent._version import __version__ as AGENT_VERSION  # noqa: E402
from desktop_agent.i18n import t  # noqa: E402
from desktop_agent.setup_dialog import ask_core_url, ask_otp, show_about  # noqa: E402

SAMPLE_INTERVAL_SECONDS = 30
REGISTER_RETRY_SECONDS = 30
OTP_MAX_ATTEMPTS = 3
ICON_PATH = Path(__file__).resolve().parent / "agent_icon.png"
PID_FILE = Path.home() / ".config" / "kelvex" / "agent.pid"

# Markenfarben (siehe deploy/site/assets/tailwind-config.js -- dieselben Tokens, hier als
# feste Hex-Werte, da tkinter kein CSS/Tailwind kennt).
K_BG = "#121417"
K_SURFACE = "#1E2226"
K_BORDER = "#2A2F35"
K_TEXT = "#F5F5F5"
K_TEXT_MUT = "#8A94A0"
K_NORMAL = "#DFFF00"

POPUP_DURATION_MS = 6000

_stop_event = threading.Event()
_pause_event = threading.Event()
_current_lang = "en"
_status_text = ""  # per _set_status() im Startpfad von main() korrekt initialisiert
# Bereits gemeldete (process_name, remote_ip, remote_port, service)-Kombinationen --
# verhindert, dass bei jedem Sample-Tick erneut benachrichtigt wird.
_notified: set[tuple] = set()
# Für den Popup: hält die Toplevel-Referenz, damit ein neues Popup ein noch offenes
# ersetzt statt sich zu überlagern (bei mehreren neuen Erkennungen im selben Takt).
_active_popup: tk.Toplevel | None = None
_popup_icon_image = None  # Referenz halten -- sonst sammelt Tkinter das PhotoImage vorzeitig ein
# Verhindert, dass ein Self-Update mehrfach angestoßen wird, falls der Spawn selbst
# fehlschlägt und der Agent weiterläuft (siehe _agent_loop()).
_update_in_progress = threading.Event()


def _set_status(icon, key: str) -> None:
    global _status_text
    _status_text = t(key, _current_lang)
    icon.update_menu()


def _register(config: AgentConfig) -> dict:
    """Ein einzelner Registrierungsversuch -- idempotent auf Core-Seite, sicher
    wiederholbar. Netzwerkfehler (Core nicht erreichbar) werden wie ein 'pending'-Status
    behandelt, damit die Aufrufschleife nicht abbricht."""
    try:
        resp = requests.post(
            f"{config.core_url}/api/agent/register",
            json={"client_id": config.client_id, "hostname": socket.gethostname()},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return {"status": "unreachable"}


def _report(config: AgentConfig, connections: list) -> tuple[bool, Optional[dict]]:
    """(ok, response_json). ok=False bei 401/403 (Token ungültig/widerrufen) -- Aufrufer
    muss dann neu registrieren. Andere Fehler (Netzwerk) gelten als vorübergehend, nicht
    als Widerruf, und werden beim nächsten Takt erneut versucht -- response_json ist
    dann None, der Aufrufer wertet in dem Fall kein config/update-Feld aus."""
    try:
        resp = requests.post(
            f"{config.core_url}/api/agent/report",
            json={
                "detections": [asdict(c) for c in connections],
                "agent_version": AGENT_VERSION,
            },
            headers={"Authorization": f"Bearer {config.token}"},
            timeout=10,
        )
        if resp.status_code in (401, 403):
            return False, None
        resp.raise_for_status()
        return True, resp.json()
    except requests.RequestException:
        return True, None  # vorübergehender Netzwerkfehler -- nächster Takt versucht es erneut


def _show_popup(root: tk.Tk, config: AgentConfig, lines: list[tuple[str, str]]) -> None:
    """Läuft NUR auf dem Haupt-Thread (über root.after() eingeplant). lines: Liste aus
    (Prozessname, Dienst) -- bei mehreren gleichzeitigen neuen Erkennungen werden alle in
    einem Popup zusammengefasst statt mehrere Fenster übereinanderzulegen."""
    global _active_popup
    if _active_popup is not None:
        _active_popup.destroy()

    popup = tk.Toplevel(root)
    _active_popup = popup
    popup.overrideredirect(True)
    popup.attributes("-topmost", True)
    popup.configure(bg=K_SURFACE, highlightthickness=1, highlightbackground=K_BORDER)

    width = 340
    screen_w = popup.winfo_screenwidth()
    screen_h = popup.winfo_screenheight()
    x = screen_w - width - 20
    y = screen_h - 140

    accent = tk.Frame(popup, bg=K_NORMAL, width=3)
    accent.pack(side="left", fill="y")

    body = tk.Frame(popup, bg=K_SURFACE, padx=12, pady=10)
    body.pack(side="left", fill="both", expand=True)

    header = tk.Frame(body, bg=K_SURFACE)
    header.pack(fill="x", anchor="w")
    if _popup_icon_image is not None:
        tk.Label(header, image=_popup_icon_image, bg=K_SURFACE).pack(side="left", padx=(0, 8))
    tk.Label(
        header, text="KELVEX AGENT", bg=K_SURFACE, fg=K_TEXT,
        font=("Consolas", 10, "bold"),
    ).pack(side="left")

    unknown = t("popup.unknown_process", _current_lang)
    for process_name, service in lines[:3]:
        tk.Label(
            body,
            text=f"{process_name or unknown} → {service}",
            bg=K_SURFACE, fg=K_TEXT_MUT, font=("Consolas", 9),
            anchor="w", justify="left", wraplength=width - 60,
        ).pack(fill="x", anchor="w", pady=(6, 0))
    if len(lines) > 3:
        tk.Label(
            body, text=t("popup.more", _current_lang).format(n=len(lines) - 3),
            bg=K_SURFACE, fg=K_NORMAL, font=("Consolas", 9), anchor="w",
        ).pack(fill="x", anchor="w", pady=(4, 0))

    popup.geometry(f"{width}x120+{x}+{y}")

    def _open_and_close(_event=None) -> None:
        if config.core_url:
            webbrowser.open(config.core_url)
        popup.destroy()

    for widget in (popup, accent, body, header):
        widget.bind("<Button-1>", _open_and_close)

    def _close() -> None:
        global _active_popup
        if _active_popup is popup:
            _active_popup = None
        try:
            popup.destroy()
        except tk.TclError:
            pass  # bereits geschlossen (z.B. durch Klick)

    popup.after(POPUP_DURATION_MS, _close)


def _notify_new(root: tk.Tk, config: AgentConfig, connections: list) -> None:
    new_lines = []
    for conn in connections:
        key = (conn.process_name, conn.remote_ip, conn.remote_port, conn.service)
        if key in _notified:
            continue
        _notified.add(key)
        new_lines.append((conn.process_name, conn.service))
    if new_lines:
        root.after(0, lambda: _show_popup(root, config, new_lines))


def _apply_pushed_config(icon, config: AgentConfig, response: dict) -> None:
    """Generisch gehalten -- nur bekannte Schlüssel werden interpretiert, alles andere
    wird ignoriert, damit künftige Core-seitige Einstellungen ohne Protokolländerung
    dazukommen können (siehe webui/app.py::api_agent_report())."""
    global _current_lang
    config_patch = response.get("config") or {}
    new_lang = config_patch.get("language")
    if new_lang and new_lang != config.language:
        config.language = new_lang
        config.save()
        _current_lang = new_lang
        icon.update_menu()  # Menü-Beschriftungen sofort auf die neue Sprache umstellen


def _agent_loop(icon, root: tk.Tk, config: AgentConfig) -> None:
    while not _stop_event.is_set():
        if config.token is None:
            result = _register(config)
            status = result.get("status")
            if status == "approved":
                config.token = result["token"]
                config.save()
                _set_status(icon, "status.active")
            elif status == "unreachable":
                _set_status(icon, "status.unreachable")
            else:
                _set_status(icon, "status.pending")
            _stop_event.wait(REGISTER_RETRY_SECONDS)
            continue

        if not _pause_event.is_set():
            try:
                conns = sample_once()
            except Exception:  # noqa: BLE001
                conns = []
            if conns:
                ok, response = _report(config, conns)
                if not ok:
                    # Token widerrufen -- zurück auf Anfang, erneut registrieren
                    config.token = None
                    config.save()
                    _set_status(icon, "status.reregistering")
                    _stop_event.wait(REGISTER_RETRY_SECONDS)
                    continue
                if response is not None:
                    _apply_pushed_config(icon, config, response)
                    update_info = response.get("update")
                    if update_info and not _update_in_progress.is_set():
                        _update_in_progress.set()
                        self_update.trigger_self_update(config, icon, root)
                        _update_in_progress.clear()  # nur erreicht, wenn der Spawn selbst fehlschlug
                _notify_new(root, config, conns)
        _stop_event.wait(SAMPLE_INTERVAL_SECONDS)


def _open_dashboard(icon, item) -> None:
    config = AgentConfig.load()
    if config.core_url:
        webbrowser.open(config.core_url)


def _dashboard_label(item) -> str:
    return t("menu.dashboard", _current_lang)


def _toggle_pause(icon, item) -> None:
    if _pause_event.is_set():
        _pause_event.clear()
    else:
        _pause_event.set()


def _pause_label(item) -> str:
    key = "menu.resume" if _pause_event.is_set() else "menu.pause"
    return t(key, _current_lang)


def _ask_core_url_threadsafe(root: tk.Tk, initial: str, lang: str, timeout: float = 300) -> tuple[Optional[str], str]:
    """pystray ruft Menü-Callbacks in seinem EIGENEN Thread auf (icon.run_detached()),
    nicht im Haupt-Thread, auf dem root.mainloop() läuft -- der Dialog selbst darf aber
    nur vom Haupt-Thread aus erzeugt werden (siehe setup_dialog.py-Docstring). Daher hier
    über root.after() auf den Haupt-Thread umgeleitet und per Event synchron auf das
    Ergebnis gewartet, damit der aufrufende Menü-Callback wie gewohnt einen Rückgabewert
    bekommt."""
    result_holder: dict = {}
    done = threading.Event()

    def _show() -> None:
        result_holder["result"] = ask_core_url(root, initial=initial, lang=lang)
        done.set()

    root.after(0, _show)
    done.wait(timeout=timeout)
    return result_holder.get("result", (None, lang))


def _verify_otp_threadsafe(root: tk.Tk, config: AgentConfig, timeout: float = 300) -> bool:
    """Gleiches root.after()+threading.Event-Brückenmuster wie
    _ask_core_url_threadsafe() -- aus dem pystray-Menü-Thread aufgerufen, der Dialog
    selbst darf aber nur auf dem Haupt-Thread entstehen. Online-Check gegen Core: bei
    Nichterreichbarkeit KEIN Offline-Rückfall, der Dialog bleibt dann einfach gesperrt."""
    error_key: Optional[str] = None
    for _attempt in range(OTP_MAX_ATTEMPTS):
        result_holder: dict = {}
        done = threading.Event()

        def _show() -> None:
            result_holder["code"] = ask_otp(root, config.language, error_key)
            done.set()

        root.after(0, _show)
        done.wait(timeout=timeout)
        code = result_holder.get("code")
        if not code:
            return False  # abgebrochen

        try:
            resp = requests.post(
                f"{config.core_url}/api/agent/verify-otp",
                json={"code": code},
                headers={"Authorization": f"Bearer {config.token}"},
                timeout=10,
            )
            resp.raise_for_status()
            if resp.json().get("ok"):
                return True
            error_key = "otp.invalid_code"
        except requests.RequestException:
            # Zeigt die Fehlermeldung einmalig per root.after() an (kein weiterer
            # Versuch bei Netzwerkfehler -- "nicht erreichbar" ist kein "falscher Code").
            done2 = threading.Event()
            root.after(0, lambda: (ask_otp(root, config.language, "otp.core_unreachable"), done2.set()))
            done2.wait(timeout=timeout)
            return False
    return False


def _open_settings(icon, root: tk.Tk, item) -> None:
    global _current_lang
    config = AgentConfig.load()
    if config.core_url:  # Ersteinrichtung schon erfolgt -- Sperre greift
        if not _verify_otp_threadsafe(root, config):
            return
    new_url, new_lang = _ask_core_url_threadsafe(root, config.core_url, config.language)

    changed = False
    if new_lang != config.language:
        config.language = new_lang
        _current_lang = new_lang
        changed = True
    if new_url and new_url != config.core_url:
        config.core_url = new_url
        config.token = None  # neue Core-Adresse -- alte Freigabe gilt dort nicht
        changed = True
    if changed:
        config.save()
        _set_status(icon, "status.pending" if config.token is None else "status.active")
    else:
        icon.update_menu()  # Menü-Beschriftungen ggf. nach Sprachwechsel aktualisieren


def _open_about(icon, root: tk.Tk, item) -> None:
    config = AgentConfig.load()
    # Fire-and-forget: show_about() liefert keinen Rückgabewert, der aufrufende
    # Menü-Callback muss also nicht wie bei _ask_core_url_threadsafe() auf ein Event warten.
    root.after(0, lambda: show_about(
        root, AGENT_VERSION, config.client_id, config.core_url, _status_text, _current_lang,
    ))


def _about_label(item) -> str:
    return t("menu.about", _current_lang)


def _status_label(item) -> str:
    return _status_text


def _settings_label(item) -> str:
    return t("menu.settings", _current_lang)


def _quit_label(item) -> str:
    return t("menu.quit", _current_lang)


def _quit(icon, root: tk.Tk, item) -> None:
    _stop_event.set()
    icon.stop()
    try:
        PID_FILE.unlink()
    except OSError:
        pass  # bereits entfernt oder nie geschrieben -- idempotent
    root.after(0, root.quit)


def main() -> None:
    global _popup_icon_image, _current_lang
    config = AgentConfig.load()
    _current_lang = config.language

    # Versteckter Haupt-Thread-Root -- muss VOR dem Erststart-Dialog existieren (der
    # Dialog braucht ein Eltern-Tk zum Andocken), hält danach die tkinter-Event-Schleife
    # für Popups/Einstellungen am Leben, zeigt selbst kein Fenster (siehe Modul-Docstring
    # für die Thread-Aufteilung zwischen pystray und tkinter).
    root = tk.Tk()
    root.withdraw()

    if not config.core_url:
        # Läuft hier noch auf dem Haupt-Thread, bevor root.mainloop() startet -- kein
        # root.after()-Umweg nötig, anders als bei _open_settings() später.
        url, lang = ask_core_url(root, initial="", lang=_current_lang)
        config.language = lang
        _current_lang = lang
        if not url:
            print(t("cli.no_core_url", _current_lang))
            config.save()
            return
        config.core_url = url
        config.save()

    _status_text_init = t("status.starting", _current_lang)
    globals()["_status_text"] = _status_text_init

    image = Image.open(ICON_PATH)
    _popup_icon_image = ImageTk.PhotoImage(image.resize((28, 28)))

    menu = pystray.Menu(
        pystray.MenuItem(_status_label, lambda: None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(_dashboard_label, _open_dashboard),
        pystray.MenuItem(_pause_label, _toggle_pause),
        pystray.MenuItem(_settings_label, lambda icon, item: _open_settings(icon, root, item)),
        pystray.MenuItem(_about_label, lambda icon, item: _open_about(icon, root, item)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(_quit_label, lambda icon, item: _quit(icon, root, item)),
    )
    icon = pystray.Icon("kelvex-agent", image, "Kelvex Agent", menu)

    # Für die Installer (siehe webui/app.py's _LINUX_INSTALL_SH/_WINDOWS_INSTALL_BAT):
    # lesen diese Datei vor dem Entpacken, um eine noch laufende Instanz sauber zu
    # beenden -- robuster und plattformübergreifend einheitlicher als ein pkill -f-
    # Substring-Match (das es unter Windows ohnehin nicht gibt).
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))
    except OSError:
        pass

    agent_thread = threading.Thread(target=_agent_loop, args=(icon, root, config), daemon=True)
    agent_thread.start()

    icon.run_detached()
    root.mainloop()  # blockiert bis _quit() -> root.quit()


if __name__ == "__main__":
    main()
