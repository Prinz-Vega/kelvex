"""SQLite-Datenschicht für Kelvex Core: erkannte KI-Verbindungen (Phase 1 "Sichtbarkeit"),
die Agenten-Registrierung/-Freigabe, Admin-OTP für lokale Agent-Einstellungen und
Core-gepushte Agent-Konfiguration."""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS detected_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pid INTEGER,
    process_name TEXT NOT NULL DEFAULT '',
    process_exe TEXT NOT NULL DEFAULT '',
    remote_ip TEXT NOT NULL,
    remote_port INTEGER NOT NULL,
    service TEXT NOT NULL,
    status TEXT NOT NULL,
    detected_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL UNIQUE,
    hostname TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    token TEXT,
    requested_at REAL NOT NULL,
    approved_at REAL,
    last_seen REAL
);

-- Eine Zeile pro Agent, PK=agent_id statt AUTOINCREMENT: ein neuer Code ersetzt (INSERT
-- OR REPLACE) einen noch nicht verbrauchten alten, keine Historie nötig (siehe
-- Database.generate_agent_otp()).
CREATE TABLE IF NOT EXISTS agent_otp (
    agent_id INTEGER PRIMARY KEY REFERENCES agents(id),
    code TEXT NOT NULL,
    expires_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_detected_connections_detected_at ON detected_connections(detected_at);
CREATE INDEX IF NOT EXISTS idx_detected_connections_service ON detected_connections(service);
CREATE INDEX IF NOT EXISTS idx_agents_token ON agents(token);
"""


class Database:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """CREATE TABLE IF NOT EXISTS erweitert nur fehlende Tabellen, keine fehlenden
        Spalten in bereits existierenden Tabellen -- daher hier per ALTER TABLE
        nachgezogen, jede Spalte einzeln und tolerant gegenüber bereits vorhandenen
        Spalten."""
        for ddl in (
            # NULL = Erkennung ohne meldenden Agenten (z.B. älterer Datenbestand vor
            # Einführung des Registrierungsflusses) -- wird beim Anzeigen als "dieser
            # Rechner" dargestellt, siehe recent_detected_connections().
            "ALTER TABLE detected_connections ADD COLUMN agent_id INTEGER REFERENCES agents(id)",
            # NULL = nichts von Core an diesen Agenten zu pushen. Wird NICHT automatisch
            # beim Ausliefern über /api/agent/report gelöscht, sondern erst, wenn ein
            # Operator es im Dashboard explizit löscht -- siehe clear_agent_pending_config().
            "ALTER TABLE agents ADD COLUMN pending_config_json TEXT",
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # Spalte existiert bereits

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- Erkannte KI-Verbindungen (Phase 1 "Sichtbarkeit", siehe KELVEX_ROADMAP.md) ---

    def log_detected_connections(self, connections: list, agent_id: Optional[int] = None) -> None:
        """Fügt pro Sample-Tick, der eine Verbindung sieht, eine Zeile ein -- bewusst
        kein Upsert. recent_detected_connections() gruppiert beim Lesen und liefert damit
        'wie oft' (COUNT) direkt aus der Gruppierung, ohne eigene Update-Logik hier.
        agent_id=None bedeutet "dieser Rechner" (kein meldender Agent, z.B. älterer
        Datenbestand vor dem Registrierungsfluss)."""
        if not connections:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO detected_connections "
                "(pid, process_name, process_exe, remote_ip, remote_port, service, status, detected_at, agent_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (c.pid, c.process_name, c.process_exe, c.remote_ip, c.remote_port,
                     c.service, c.status, c.detected_at, agent_id)
                    for c in connections
                ],
            )

    def recent_detected_connections(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT dc.process_name, dc.process_exe, dc.remote_ip, dc.remote_port, dc.service,
                       MAX(dc.detected_at) AS last_seen,
                       MIN(dc.detected_at) AS first_seen,
                       COUNT(*) AS hits,
                       a.hostname AS source_hostname
                FROM detected_connections dc
                LEFT JOIN agents a ON a.id = dc.agent_id
                GROUP BY dc.process_name, dc.remote_ip, dc.remote_port, dc.service, dc.agent_id
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Agenten (Registrierungsfluss, siehe desktop_agent/) ---------------

    def register_agent_request(self, client_id: str, hostname: str) -> dict:
        """Idempotent: eine bereits bekannte client_id erzeugt KEINEN neuen Eintrag,
        sondern liefert den bestehenden Status zurück (z.B. nach einem Core-Neustart
        oder während der Agent auf Freigabe pollt)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, status, token FROM agents WHERE client_id = ?", (client_id,)
            ).fetchone()
            if row is not None:
                return dict(row)
            cur = conn.execute(
                "INSERT INTO agents (client_id, hostname, status, requested_at) VALUES (?, ?, 'pending', ?)",
                (client_id, hostname, time.time()),
            )
            return {"id": cur.lastrowid, "status": "pending", "token": None}

    def agent_by_token(self, token: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, client_id, hostname, status FROM agents WHERE token = ? AND status = 'approved'",
                (token,),
            ).fetchone()
        return dict(row) if row else None

    def list_agents(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, client_id, hostname, status, requested_at, approved_at, last_seen, "
                "pending_config_json "
                "FROM agents ORDER BY requested_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def agent_by_id(self, agent_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, client_id, hostname, status, token FROM agents WHERE id = ?",
                (agent_id,),
            ).fetchone()
        return dict(row) if row else None

    def approve_agent(self, agent_id: int) -> Optional[str]:
        token = secrets.token_urlsafe(32)
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE agents SET status = 'approved', token = ?, approved_at = ? WHERE id = ?",
                (token, time.time(), agent_id),
            )
            if cur.rowcount == 0:
                return None
        return token

    def revoke_agent(self, agent_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE agents SET status = 'revoked', token = NULL WHERE id = ?", (agent_id,)
            )
            return cur.rowcount > 0

    def touch_agent_last_seen(self, agent_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE agents SET last_seen = ? WHERE id = ?", (time.time(), agent_id))

    # --- Admin-OTP für Agent-Einstellungen (siehe desktop_agent/setup_dialog.py::ask_otp()) ---

    def generate_agent_otp(self, agent_id: int, code: str, ttl_seconds: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO agent_otp (agent_id, code, expires_at) VALUES (?, ?, ?)",
                (agent_id, code, time.time() + ttl_seconds),
            )

    def verify_and_consume_agent_otp(self, agent_id: int, code: str) -> bool:
        """Einmalverwendung: ein korrekter, nicht abgelaufener Code wird sofort gelöscht.
        Ein FALSCHER Code löscht die Zeile NICHT -- ein Vertipper darf einen noch
        gültigen Code nicht vorzeitig verfallen lassen (Rate-Limiting gegen Erraten
        passiert auf Route-Ebene, siehe webui/app.py)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT code, expires_at FROM agent_otp WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            if row is None or row["code"] != code or row["expires_at"] < time.time():
                return False
            conn.execute("DELETE FROM agent_otp WHERE agent_id = ?", (agent_id,))
        return True

    # --- Core-gepushte Agent-Konfiguration (siehe webui/app.py::api_agent_report()) ---

    def set_agent_pending_config(self, agent_id: int, config: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE agents SET pending_config_json = ? WHERE id = ?",
                (json.dumps(config), agent_id),
            )

    def get_agent_pending_config(self, agent_id: int) -> Optional[dict]:
        """Liest nur -- löscht NICHT (kein Ack-Protokoll, siehe clear_agent_pending_config()).
        Wird daher bei jedem /api/agent/report-Zyklus erneut ausgeliefert, bis ein
        Operator die Einstellung im Dashboard explizit löscht."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT pending_config_json FROM agents WHERE id = ?", (agent_id,)
            ).fetchone()
        if row is None or not row["pending_config_json"]:
            return None
        return json.loads(row["pending_config_json"])

    def clear_agent_pending_config(self, agent_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE agents SET pending_config_json = NULL WHERE id = ?", (agent_id,)
            )
