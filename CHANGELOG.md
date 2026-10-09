# Kelvex Security — Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/), Versionierung nach
[SemVer](https://semver.org/).

## [0.2.1-alpha] — 2026-10-09

### Hinzugefügt
- **Agent-seitiges OTP-Gate fertiggestellt**: `desktop_agent/setup_dialog.py::ask_otp()`
  + `tray.py::_verify_otp_threadsafe()` -- die lokalen Einstellungen verlangen jetzt
  tatsächlich den im Dashboard generierten Code, bevor sie sich öffnen (serverseitige
  Prüfung kam bereits mit 0.2.0-alpha).
- **Agent-Self-Update** (`desktop_agent/self_update.py`): erkennt über den
  Report-Poll-Zyklus, wenn Core eine neuere Agent-Version anbietet, lädt den
  bestehenden Installer herunter und übergibt ihm die Aktualisierung losgelöst, statt
  einen eigenen Update-Mechanismus zu bauen.
- **PID-Datei** (`desktop_agent/tray.py::PID_FILE`): beide Installer stoppen damit vor
  dem Entpacken eine noch laufende Instanz sauber -- ersetzt das ursprünglich für
  Windows vorgesehene, dort gar nicht vorhandene `pkill -f`-Substring-Matching.
- **Dashboard-Login** (`core/auth.py`): rudimentäres, aber sicheres Admin-Passwort
  (Werkzeug-Scrypt-Hash), bei der Ersteinrichtung erzwungen (`/setup`), danach
  ratenbegrenzter Login (`/login`) und Passwortänderung (`/account`, rotiert dabei den
  Session-Schlüssel -- meldet alle Sitzungen ab). Agenten-Endpunkte
  (register/report/verify-otp, Download-/Installer-Routen) bleiben bewusst ohne
  Session-Login erreichbar.
- Vier neue Navigations-Icons (Dashboard, Updates, Lizenzen, Konto) im bestehenden
  Marken-Icon-Stil.

### Geändert
- `deploy/config.py::RELEASE_EXCLUDES` um dieselbe Archon/Plesk-Abgrenzung wie im
  öffentlichen GitHub-Repo ergänzt -- das über die Webseite herunterladbare
  Release-Zip enthielt zuvor mehr als das öffentliche Repo.
- Verwaistes `.flatpak-builder/`-Cache-Verzeichnis (1,2 GB, von der bereits
  entfernten Flatpak-Paketierung) gelöscht -- enthielt Dateien mit Zeitstempel 0, die
  den Zip-Build zum Absturz brachten.

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
