"""One-Click-Installer-Helfer (siehe webui/app.py::install_linux()/install_windows()):
schreibt core_url in agent_config.json, BEVOR tray.py das erste Mal startet -- macht den
Erststart-Einrichtungsdialog (setup_dialog.py::ask_core_url) überflüssig, wenn der Nutzer
über einen der install.sh/install.bat-Skripte gekommen ist, die die Core-Adresse ohnehin
schon kennen (sie laden den Agenten ja von genau dort herunter)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from desktop_agent.agent_config import AgentConfig  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: _seed_config.py <core_url>", file=sys.stderr)
        return 1
    config = AgentConfig.load()
    config.core_url = sys.argv[1].rstrip("/")
    config.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
