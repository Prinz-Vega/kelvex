#!/usr/bin/env python3
"""Entwickler-Tool zum Erzeugen des Lizenz-Signierschlüssels und zum Ausstellen von
Lizenzen -- NICHT Teil der laufenden App, wird nie importiert, nicht an Kunden
ausgeliefert (liegt unter deploy/, von RELEASE_EXCLUDES bereits ausgeschlossen).

Der private Schlüssel (deploy/keys/license_signing_key) verlässt diesen Rechner nie.
Nur der dazugehörige öffentliche Schlüssel wandert von Hand in
core/licensing/public_key.py -- siehe dort für die Begründung, warum das sicher ist.

Aufruf:
    .venv/bin/python deploy/license_tool.py generate-keypair [--force]
    .venv/bin/python deploy/license_tool.py issue --hardware-id <sha256-hex> \\
        --license-type dev|trial|starter|pro|enterprise --seats <int> \\
        (--expires-days <int> | --expires-date YYYY-MM-DD) \\
        [--modules "modul_a,modul_b"] [--output pfad.json]
    .venv/bin/python deploy/license_tool.py issue-unban --hardware-id <sha256-hex> \\
        [--output pfad.json]

Für ein grafisches Tool statt dieser CLI siehe deploy/license_gui.py (gitignored,
nicht auf GitHub -- importiert dieselben Funktionen aus diesem Modul)."""
from __future__ import annotations

import argparse
import base64
import json
import os
import stat
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from core.licensing.license_data import License, UnbanCertificate  # noqa: E402

PRIVATE_KEY_PATH = Path(__file__).parent / "keys" / "license_signing_key"


def _load_or_fail_private_key() -> Ed25519PrivateKey:
    if not PRIVATE_KEY_PATH.is_file():
        raise SystemExit(
            f"Kein Signierschlüssel unter {PRIVATE_KEY_PATH} gefunden -- "
            "zuerst 'deploy/license_tool.py generate-keypair' ausführen."
        )
    raw = PRIVATE_KEY_PATH.read_bytes()
    return Ed25519PrivateKey.from_private_bytes(raw)


def generate_keypair(force: bool = False) -> None:
    if PRIVATE_KEY_PATH.exists() and not force:
        raise SystemExit(
            f"{PRIVATE_KEY_PATH} existiert bereits -- ein neuer Schlüssel würde alle "
            "bereits ausgegebenen Lizenzen entwerten. --force zum Überschreiben."
        )
    PRIVATE_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    raw_private = private_key.private_bytes_raw()
    PRIVATE_KEY_PATH.write_bytes(raw_private)
    os.chmod(PRIVATE_KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)

    raw_public = private_key.public_key().public_bytes_raw()
    public_hex = raw_public.hex()
    print(f"Privater Schlüssel geschrieben nach: {PRIVATE_KEY_PATH}")
    print()
    print("Füge diesen Wert in core/licensing/public_key.py ein (LICENSE_PUBLIC_KEY_HEX):")
    print(public_hex)


def issue_license(
    hardware_id: str, license_type: str, seats: int, expires_at: float, modules: list[str],
) -> dict:
    license_obj = License(
        license_id=str(uuid.uuid4()),
        license_type=license_type,
        hardware_id=hardware_id,
        seats=seats,
        modules=modules,
        issued_at=time.time(),
        expires_at=expires_at,
    )
    private_key = _load_or_fail_private_key()
    signature = private_key.sign(license_obj.canonical_json())
    signature_b64 = base64.b64encode(signature).decode("ascii")
    return license_obj.to_signed_dict(signature_b64)


def issue_unban_certificate(hardware_id: str) -> dict:
    """Hebt die lokale Manipulationssperre (core/licensing/storage.py::ban_hardware())
    für genau diese hardware_id auf -- siehe license_data.py::UnbanCertificate für das
    Format. Kein Ablauf, da eine Entsperrung eine einmalige Aktion ist."""
    cert = UnbanCertificate(unban_id=str(uuid.uuid4()), hardware_id=hardware_id, issued_at=time.time())
    private_key = _load_or_fail_private_key()
    signature = private_key.sign(cert.canonical_json())
    signature_b64 = base64.b64encode(signature).decode("ascii")
    return cert.to_signed_dict(signature_b64)


def _parse_expiry(args: argparse.Namespace) -> float:
    if args.expires_date is not None:
        dt = datetime.strptime(args.expires_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    # Bewusst auch negative Werte erlaubt -- erzeugt eine bereits abgelaufene Lizenz,
    # nützlich zum Testen der Ablauf-Ablehnung ohne echtes Warten.
    return time.time() + args.expires_days * 86400


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    gen_parser = subparsers.add_parser("generate-keypair", help="Neues Signierschlüsselpaar erzeugen")
    gen_parser.add_argument("--force", action="store_true", help="Bestehenden Schlüssel überschreiben")

    issue_parser = subparsers.add_parser("issue", help="Eine Lizenz ausstellen")
    issue_parser.add_argument("--hardware-id", required=True)
    issue_parser.add_argument("--license-type", required=True, choices=["dev", "trial", "starter", "pro", "enterprise"])
    issue_parser.add_argument("--seats", required=True, type=int)
    expiry_group = issue_parser.add_mutually_exclusive_group(required=True)
    expiry_group.add_argument("--expires-days", type=int)
    expiry_group.add_argument("--expires-date", type=str, help="YYYY-MM-DD")
    issue_parser.add_argument("--modules", default="", help="Kommagetrennte Modul-Slugs, leer = keine")
    issue_parser.add_argument("--output", type=str, help="Zieldatei (Default: stdout)")

    unban_parser = subparsers.add_parser("issue-unban", help="Manipulationssperre einer Maschine aufheben")
    unban_parser.add_argument("--hardware-id", required=True)
    unban_parser.add_argument("--output", type=str, help="Zieldatei (Default: stdout)")

    args = parser.parse_args()

    if args.command == "generate-keypair":
        generate_keypair(force=args.force)
        return 0

    if args.command == "issue-unban":
        signed = issue_unban_certificate(args.hardware_id)
    else:
        modules = [m.strip() for m in args.modules.split(",") if m.strip()]
        expires_at = _parse_expiry(args)
        signed = issue_license(args.hardware_id, args.license_type, args.seats, expires_at, modules)

    output_text = json.dumps(signed, indent=2)
    if args.output:
        Path(args.output).write_text(output_text + "\n", encoding="utf-8")
        print(f"Geschrieben nach: {args.output}")
    else:
        print(output_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
