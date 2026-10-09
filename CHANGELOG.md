# Kelvex Security — Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/), Versionierung nach
[SemVer](https://semver.org/).

## [0.2.0-alpha] — 2026-10-09

### Hinzugefügt
- **Lizenzsystem** (`core/licensing/`): Ed25519-signierte, hardware-gebundene,
  zeitlich begrenzte Lizenzen, vollständig offline geprüft. 1 Endpoint ist immer
  kostenlos; ab dem 2. Endpoint ohne gültige Lizenz schlägt die Genehmigung fehl
  (`402`). Erkannte Signatur-Manipulation sperrt die Installation permanent, bis ein
  separat signiertes Entsperr-Zertifikat angewendet wird. Neue `/licenses`-Seite im
  Dashboard, `deploy/license_tool.py` als Ausstellungs-CLI.
- **Admin-OTP für lokale Agent-Einstellungen**: im Dashboard generierter Einmalcode,
  online gegen Core geprüft, bevor der Agent seine lokalen Einstellungen öffnet.
- **Core-gepushte Agent-Konfiguration**: Dashboard kann Einstellungen (aktuell:
  Sprache) an Agenten pushen, ausgeliefert über den bestehenden Report-Poll-Zyklus.
- **Core-Selbst-Update**: Prüfen + Anwenden eines neuen Core-Releases, online oder per
  hochgeladener Datei (Air-Gapped-geeignet), kein automatischer Dienst-Neustart.
- **One-Click-Installer** für den Kelvex Agent (Linux `install.sh`, Windows
  `install.bat`), von Core selbst ausgeliefert, inkl. automatischer Ersteinrichtung.
- **Vollständige Mehrsprachigkeit** (Englisch primär, Deutsch sekundär) über
  Dashboard und Agent.

### Geändert
- `core/memory/database.py` und `config/settings.py` auf den tatsächlichen Umfang von
  Kelvex Core/Agent reduziert.
