"""Lizenzformat: sieben Felder, die gemeinsam signiert werden (siehe canonical_json()),
plus eine separat angehängte Signatur. Von deploy/license_tool.py (signiert) UND
verifier.py (prüft) importiert -- beide nutzen DIESELBE canonical_json()-Implementierung,
damit die signierten Bytes niemals zwischen Aussteller und Prüfer auseinanderdriften
können."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

CANONICAL_FIELDS = (
    "license_id", "license_type", "hardware_id", "seats", "modules", "issued_at", "expires_at",
)


class LicenseFormatError(ValueError):
    """Eingehendes Lizenz-JSON hat fehlende oder falsch typisierte Felder -- reines
    Parsing-Problem, sagt nichts über die Signatur aus (siehe verifier.py)."""


@dataclass
class License:
    license_id: str
    license_type: str
    hardware_id: str
    seats: int
    modules: list[str]
    issued_at: float
    expires_at: float  # Lizenzen sind IMMER zeitlich begrenzt -- kein "läuft nie ab"-Wert

    def canonical_json(self) -> bytes:
        """Deterministische Byte-Folge für Signieren/Prüfen: sortierte Keys, keine
        Leerzeichen -- unabhängig von Dict-Einfügereihenfolge oder Formatierung immer
        identisch für dieselben Werte."""
        payload = {field: getattr(self, field) for field in CANONICAL_FIELDS}
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def to_signed_dict(self, signature_b64: str) -> dict:
        data = asdict(self)
        data["signature"] = signature_b64
        return data

    @classmethod
    def from_signed_dict(cls, data: dict) -> tuple["License", str]:
        """Reines Parsen -- prüft NICHT die Signatur selbst (siehe verifier.py::verify_license()).
        Wirft LicenseFormatError bei fehlenden/falsch typisierten Feldern."""
        if not isinstance(data, dict):
            raise LicenseFormatError("Lizenz muss ein JSON-Objekt sein")
        signature = data.get("signature")
        if not isinstance(signature, str) or not signature:
            raise LicenseFormatError("Feld 'signature' fehlt oder ist leer")
        try:
            license_obj = cls(
                license_id=str(data["license_id"]),
                license_type=str(data["license_type"]),
                hardware_id=str(data["hardware_id"]),
                seats=int(data["seats"]),
                modules=[str(m) for m in data["modules"]],
                issued_at=float(data["issued_at"]),
                expires_at=float(data["expires_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LicenseFormatError(f"Lizenzfeld fehlt oder hat falschen Typ: {exc}") from exc
        return license_obj, signature


UNBAN_CANONICAL_FIELDS = ("unban_id", "hardware_id", "issued_at")


@dataclass
class UnbanCertificate:
    """Hebt die lokale Manipulationssperre (siehe storage.py::ban_hardware()) für eine
    bestimmte hardware_id auf -- signiert mit demselben privaten Schlüssel wie eine
    Lizenz, aber strukturell unterscheidbar (kein "seats"-Feld), damit
    api_license_activate() ohne Mehrdeutigkeit erkennen kann, welche der beiden Arten
    von signiertem JSON gerade eingefügt wurde. Bewusst ohne Ablauf -- eine
    Entsperrung ist eine einmalige, harmlose Aktion, kein Dauerzustand wie eine Lizenz."""

    unban_id: str
    hardware_id: str
    issued_at: float

    def canonical_json(self) -> bytes:
        payload = {field: getattr(self, field) for field in UNBAN_CANONICAL_FIELDS}
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def to_signed_dict(self, signature_b64: str) -> dict:
        data = asdict(self)
        data["signature"] = signature_b64
        return data

    @classmethod
    def from_signed_dict(cls, data: dict) -> tuple["UnbanCertificate", str]:
        if not isinstance(data, dict):
            raise LicenseFormatError("Entsperr-Zertifikat muss ein JSON-Objekt sein")
        signature = data.get("signature")
        if not isinstance(signature, str) or not signature:
            raise LicenseFormatError("Feld 'signature' fehlt oder ist leer")
        try:
            cert = cls(
                unban_id=str(data["unban_id"]),
                hardware_id=str(data["hardware_id"]),
                issued_at=float(data["issued_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LicenseFormatError(f"Entsperr-Feld fehlt oder hat falschen Typ: {exc}") from exc
        return cert, signature


def looks_like_unban_certificate(data: dict) -> bool:
    """Strukturelle Unterscheidung, BEVOR geparst wird: ein Lizenz-JSON hat immer
    "seats"/"modules"/"license_type", ein Entsperr-Zertifikat nie. Reine Heuristik auf
    Feldnamen, keine Sicherheitsprüfung (die passiert erst bei der Signaturprüfung) --
    entscheidet nur, welcher der beiden from_signed_dict()-Pfade versucht wird."""
    return isinstance(data, dict) and "unban_id" in data and "seats" not in data
