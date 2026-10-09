"""Wendet ein Kelvex-Core-Release-Zip auf die laufende Installation an -- Gegenstück zu
core/updater.py (das nur PRÜFT, ob eine neuere Version existiert). Getrennt vom
Agenten-Self-Update (desktop_agent/self_update.py): der Agent aktualisiert sich über die
bestehenden install.sh/install.bat-Skripte (die bereits venv/Abhängigkeiten handhaben),
Core aktualisiert sich hier per direktem Datei-Kopieren über die eigene Installation,
da ein Admin ohnehin auf demselben Dateisystem sitzt.

Startet NIE automatisch neu -- bewusste Nutzerentscheidung (siehe KELVEX_ROADMAP.md:
"Updates als manuell einspielbare Pakete statt Auto-Update"). webui/app.py zeigt nach
einem erfolgreichen apply_update_zip()-Aufruf ein "Neustart erforderlich"-Banner."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


class UpdateApplyError(Exception):
    pass


def _read_version(version_file: Path) -> str:
    if not version_file.is_file():
        raise UpdateApplyError("Zip enthält keine core/version.py -- kein gültiges Kelvex-Release.")
    # Regex statt exec() -- das ist admin-hochgeladener Inhalt, kein vertrauenswürdiger Code.
    match = _VERSION_RE.search(version_file.read_text(encoding="utf-8"))
    if not match:
        raise UpdateApplyError("core/version.py im Zip enthält keine __version__-Zuweisung.")
    return match.group(1)


def _copy_tree_over(src: Path, dest: Path) -> None:
    """Kopiert jede Datei aus src nach dest, überschreibt vorhandene Dateien, LÖSCHT aber
    nichts, das in dest existiert und in src fehlt -- sicherer Standard, falls das Zip aus
    irgendeinem Grund unvollständig ist. Die Live-DB liegt ohnehin außerhalb von
    PROJECT_ROOT (~/.config/kelvex/), ist von diesem Kopiervorgang also nie betroffen."""
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dest / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def apply_update_zip(zip_path_or_fileobj) -> str:
    """Entpackt, validiert, kopiert über PROJECT_ROOT, installiert Abhängigkeiten nach.
    Gibt die neue Versionsnummer zurück. Wirft UpdateApplyError bei ungültigem Zip."""
    staging_dir = Path(tempfile.mkdtemp(prefix="kelvex-update-"))
    try:
        try:
            with zipfile.ZipFile(zip_path_or_fileobj) as zf:
                zf.extractall(staging_dir)
        except zipfile.BadZipFile as exc:
            raise UpdateApplyError(f"Keine gültige Zip-Datei: {exc}") from exc

        # deploy/release.py baut das Zip mit dem Projekt-Root als Wurzel (core/, webui/,
        # desktop_agent/, ... liegen direkt im Zip, kein zusätzlicher Wrapper-Ordner).
        new_version = _read_version(staging_dir / "core" / "version.py")

        _copy_tree_over(staging_dir, PROJECT_ROOT)

        requirements_file = PROJECT_ROOT / "requirements.txt"
        if requirements_file.is_file():
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(requirements_file)],
                check=True,
            )

        return new_version
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
