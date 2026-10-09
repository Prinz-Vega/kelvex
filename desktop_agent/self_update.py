"""Agent-Self-Update: wird von tray.py::_agent_loop() ausgelöst, sobald eine
/api/agent/report-Antwort ein "update"-Feld enthält (siehe webui/app.py). Nutzt
bewusst den BESTEHENDEN Installer-Fluss (/install/linux bzw. /install/windows) statt
einen eigenen Update-Mechanismus zu erfinden -- der Installer handhabt bereits
venv/Abhängigkeiten, Config-Seeding und (seit dieser Version) das Stoppen einer noch
laufenden Instanz über deren PID-Datei (siehe tray.py::PID_FILE).

Importiert bewusst NICHTS aus tray.py (Gefahr eines Zirkelimports, da tray.py dieses
Modul importiert) -- icon/root werden als Parameter hereingereicht, das Beenden des
aktuellen Prozesses passiert direkt über icon.stop()/root.quit(), ohne tray.py's
internen _stop_event anzufassen (der Sampler-Thread ist ein Daemon-Thread und stirbt
ohnehin mit dem Hauptprozess)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import tkinter as tk
from pathlib import Path

import requests

from desktop_agent.agent_config import AgentConfig

_DOWNLOAD_TIMEOUT = 30


def trigger_self_update(config: AgentConfig, icon, root: tk.Tk) -> None:
    """Lädt das Installer-Skript, startet es LOSGELÖST (überlebt das Beenden dieses
    Prozesses) und beendet den aktuellen Agenten erst NACH bestätigtem Spawn-Erfolg --
    schlägt der Download/Spawn fehl, bleibt der alte Prozess am Leben und versucht es
    beim nächsten Poll-Zyklus erneut, statt sich in nichts zu beenden."""
    platform_path = "install/windows" if sys.platform == "win32" else "install/linux"
    suffix = ".bat" if sys.platform == "win32" else ".sh"

    try:
        resp = requests.get(f"{config.core_url}/{platform_path}", timeout=_DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        return  # Core gerade nicht erreichbar -- nächster Poll-Zyklus versucht es erneut

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
        fh.write(resp.content)
        script_path = Path(fh.name)

    try:
        if sys.platform == "win32":
            subprocess.Popen(
                [str(script_path)],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        else:
            script_path.chmod(0o755)
            subprocess.Popen(
                ["/bin/bash", str(script_path)],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except OSError:
        return  # Spawn fehlgeschlagen -- alter Prozess bleibt am Leben, nächster Versuch beim nächsten Poll

    icon.stop()
    root.after(0, root.quit)
