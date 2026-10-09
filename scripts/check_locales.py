#!/usr/bin/env python3
"""Prüft die Locale-Verzeichnisse von Kelvex Core und dem Kelvex Agent gegen ihre
jeweilige Referenzsprache: meldet fehlende/überzählige Schlüssel pro Sprache sowie
{platzhalter}-Namen, die zwischen Referenz- und Zielsprache für denselben Schlüssel
nicht übereinstimmen (z.B. Übersetzer benennt {model} versehentlich in {modell} um --
das würde sonst erst zur Laufzeit als KeyError/sichtbarer "⟨key⟩"-Platzhalter auffallen).

Layout: locales/<sprache>.json, genau eine Datei pro Sprache und Verzeichnis.

Aufruf:
    python3 scripts/check_locales.py
Exit-Code 0 = alles sauber, 1 = mindestens eine Abweichung gefunden.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
REFERENCE_LANGUAGE = "en"

# (Anzeigename, Locale-Verzeichnis, Layout, Referenzsprache)
LOCALE_SETS = [
    ("desktop_agent/locales/", PROJECT_ROOT / "desktop_agent" / "locales", "flat", REFERENCE_LANGUAGE),
    ("webui/locales/", PROJECT_ROOT / "webui" / "locales", "flat", REFERENCE_LANGUAGE),
]

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def flatten(namespace: dict, prefix: str = "") -> dict[str, str]:
    """Reduziert ein verschachteltes JSON-Objekt auf {"a.b.c": wert, ...}, nur für Strings."""
    flat: dict[str, str] = {}
    for key, value in namespace.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten(value, full_key))
        elif isinstance(value, str):
            flat[full_key] = value
    return flat


def load_language_dir(lang_dir: Path) -> dict[str, str]:
    """Layout "dir": locales/<sprache>/*.json, Dateiname als Schlüssel-Präfix."""
    flat: dict[str, str] = {}
    for json_file in sorted(lang_dir.glob("*.json")):
        if json_file.stem == "_meta":
            continue
        with open(json_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        flat.update(flatten(data, json_file.stem))
    return flat


def load_language_flat(json_file: Path) -> dict[str, str]:
    """Layout "flat": locales/<sprache>.json, eine Datei pro Sprache."""
    if not json_file.exists():
        return {}
    with open(json_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return flatten(data)


def languages_for(locales_dir: Path, layout: str) -> list[str]:
    if layout == "dir":
        return sorted(p.name for p in locales_dir.iterdir() if p.is_dir())
    return sorted(p.stem for p in locales_dir.glob("*.json"))


def load_language(locales_dir: Path, layout: str, lang: str) -> dict[str, str]:
    if layout == "dir":
        return load_language_dir(locales_dir / lang)
    return load_language_flat(locales_dir / f"{lang}.json")


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(text))


def check_locale_set(label: str, locales_dir: Path, layout: str, reference_lang: str) -> bool:
    """True, wenn keine Probleme gefunden wurden."""
    if not locales_dir.is_dir():
        print(f"[{label}] Kein Verzeichnis gefunden unter {locales_dir}", file=sys.stderr)
        return False

    reference = load_language(locales_dir, layout, reference_lang)
    if not reference:
        print(f"[{label}] Referenzsprache '{reference_lang}' ist leer oder fehlt.", file=sys.stderr)
        return False

    problems_found = False

    for lang in languages_for(locales_dir, layout):
        if lang == reference_lang:
            continue
        translated = load_language(locales_dir, layout, lang)

        missing = sorted(set(reference) - set(translated))
        extra = sorted(set(translated) - set(reference))

        if missing:
            problems_found = True
            print(f"[{label}] [{lang}] Fehlende Schlüssel ({len(missing)}):")
            for key in missing:
                print(f"  - {key}")

        if extra:
            problems_found = True
            print(f"[{label}] [{lang}] Überzählige Schlüssel ({len(extra)}):")
            for key in extra:
                print(f"  - {key}")

        for key in sorted(set(reference) & set(translated)):
            ref_placeholders = placeholders(reference[key])
            trans_placeholders = placeholders(translated[key])
            if ref_placeholders != trans_placeholders:
                problems_found = True
                print(
                    f"[{label}] [{lang}] Platzhalter-Mismatch bei '{key}': "
                    f"{reference_lang}={sorted(ref_placeholders)} {lang}={sorted(trans_placeholders)}"
                )

    return not problems_found


def main() -> int:
    any_problems = False
    for label, locales_dir, layout, reference_lang in LOCALE_SETS:
        ok = check_locale_set(label, locales_dir, layout, reference_lang)
        if not ok:
            any_problems = True

    if not any_problems:
        print("Alle Locales sind vollständig und konsistent.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
