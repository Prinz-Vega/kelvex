"""Stabiler Hardware-Fingerabdruck für die Lizenzbindung. Nutzt bewusst den OS-eigenen,
für genau diesen Zweck gedachten Maschinen-Identifier statt eines selbstgebastelten
Verbunds aus MAC-Adresse/Boot-Zeit o.ä. -- beides ändert sich bei NIC-Wechsel bzw. jedem
Neustart und wäre als Lizenz-Bindung untauglich (eine Lizenz dürfte nicht bei jedem Reboot
ungültig werden)."""
from __future__ import annotations

import hashlib
import os
import sys

# Nur für Tests/CI -- die App selbst liest diese Variable nie aktiv, sie existiert nur,
# damit Tests einen Fingerabdruck simulieren können, ohne Root-/Registry-Zugriff zu
# brauchen oder von der realen Maschine abhängig zu sein.
_OVERRIDE_ENV_VAR = "KELVEX_LICENSE_HARDWARE_ID_OVERRIDE"


class HardwareIdUnavailableError(RuntimeError):
    """Weder /etc/machine-id (Linux) noch MachineGuid (Windows) waren lesbar -- z.B. in
    einem Container ohne systemd. Bewusst kein stiller Rückfall auf einen schwächeren
    Fingerabdruck, das würde die Hardware-Bindung aufweichen."""


def _raw_machine_id() -> str:
    if sys.platform == "win32":
        import winreg  # nur unter Windows verfügbar

        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
        try:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
        finally:
            winreg.CloseKey(key)
        return value.strip()

    machine_id_path = "/etc/machine-id"
    try:
        with open(machine_id_path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError as exc:
        raise HardwareIdUnavailableError(
            f"{machine_id_path} nicht lesbar -- Lizenzbindung auf dieser Maschine nicht möglich."
        ) from exc


def compute_hardware_id() -> str:
    """SHA-256-Hash des rohen OS-Maschinen-Identifiers -- der rohe Wert selbst wird
    nirgends gespeichert/übertragen, nur sein Hash (64-stelliger Hex-String)."""
    override = os.environ.get(_OVERRIDE_ENV_VAR)
    if override:
        return override
    raw = _raw_machine_id()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
