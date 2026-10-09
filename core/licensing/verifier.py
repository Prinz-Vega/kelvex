"""Vollständig lokale Lizenzprüfung -- kein Lizenzserver, kein Netzwerkaufruf. Prüft in
fester Reihenfolge Signatur vor Hardware vor Ablauf: ein manipuliertes Feld (z.B. per
Hand geändertes "seats") soll als Signaturfehler auffallen, nicht fälschlich als falsche
Hardware oder abgelaufene Lizenz missverstanden werden."""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.licensing.fingerprint import compute_hardware_id
from core.licensing.license_data import License, LicenseFormatError, UnbanCertificate
from core.licensing.public_key import LICENSE_PUBLIC_KEY_HEX

_PUBLIC_KEY = Ed25519PublicKey.from_public_bytes(bytes.fromhex(LICENSE_PUBLIC_KEY_HEX))


class LicenseStatus(Enum):
    VALID = "valid"
    NO_LICENSE = "no_license"
    INVALID_SIGNATURE = "invalid_signature"
    HARDWARE_MISMATCH = "hardware_mismatch"
    EXPIRED = "expired"
    MALFORMED = "malformed"


@dataclass
class LicenseCheckResult:
    status: LicenseStatus
    # Bei INVALID_SIGNATURE/MALFORMED NIE gefüllt -- der Inhalt ist dann nicht
    # vertrauenswürdig. Bei HARDWARE_MISMATCH/EXPIRED weiterhin gefüllt (für die
    # Anzeige, z.B. "diese Lizenz war für Maschine X / bis Datum Y gültig").
    license: Optional[License]
    days_remaining: Optional[int]


def effective_seat_limit(result: LicenseCheckResult) -> int:
    """1 (Gratis-Tier) wenn keine gültige Lizenz vorliegt, sonst das Sitzplatzlimit der
    Lizenz."""
    if result.status != LicenseStatus.VALID or result.license is None:
        return 1
    return result.license.seats


def verify_license(license_json: Optional[dict], *, hardware_id: Optional[str] = None) -> LicenseCheckResult:
    """license_json=None -> sofort NO_LICENSE, damit jeder Aufrufer denselben Pfad nutzen
    kann (verify_license(load_installed_license())) statt selbst auf None zu prüfen.
    hardware_id-Parameter ist NUR für Tests gedacht -- Produktionscode lässt ihn weg und
    prüft damit automatisch gegen die echte lokale Maschine."""
    if license_json is None:
        return LicenseCheckResult(LicenseStatus.NO_LICENSE, None, None)

    try:
        license_obj, signature_b64 = License.from_signed_dict(license_json)
    except LicenseFormatError:
        return LicenseCheckResult(LicenseStatus.MALFORMED, None, None)

    try:
        signature = base64.b64decode(signature_b64)
    except (ValueError, TypeError):
        return LicenseCheckResult(LicenseStatus.MALFORMED, None, None)

    try:
        _PUBLIC_KEY.verify(signature, license_obj.canonical_json())
    except InvalidSignature:
        return LicenseCheckResult(LicenseStatus.INVALID_SIGNATURE, None, None)

    current_hardware_id = hardware_id if hardware_id is not None else compute_hardware_id()
    if license_obj.hardware_id != current_hardware_id:
        return LicenseCheckResult(LicenseStatus.HARDWARE_MISMATCH, license_obj, None)

    now = time.time()
    if license_obj.expires_at < now:
        return LicenseCheckResult(LicenseStatus.EXPIRED, license_obj, 0)

    days_remaining = int((license_obj.expires_at - now) // 86400)
    return LicenseCheckResult(LicenseStatus.VALID, license_obj, days_remaining)


def verify_unban_certificate(cert_json: dict, *, hardware_id: Optional[str] = None) -> bool:
    """Prüft ein Entsperr-Zertifikat (siehe license_data.py::UnbanCertificate) gegen
    denselben öffentlichen Schlüssel wie eine Lizenz. True nur, wenn Signatur gültig UND
    die zertifizierte hardware_id zur aktuellen (oder im Test übergebenen) Maschine
    passt -- ein für eine ANDERE Maschine ausgestelltes Zertifikat darf diese hier nicht
    entsperren."""
    try:
        cert, signature_b64 = UnbanCertificate.from_signed_dict(cert_json)
        signature = base64.b64decode(signature_b64)
    except (LicenseFormatError, ValueError, TypeError):
        return False

    try:
        _PUBLIC_KEY.verify(signature, cert.canonical_json())
    except InvalidSignature:
        return False

    current_hardware_id = hardware_id if hardware_id is not None else compute_hardware_id()
    return cert.hardware_id == current_hardware_id
