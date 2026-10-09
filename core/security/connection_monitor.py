"""Phase 1 ("Sichtbarkeit") aus KELVEX_ROADMAP.md: passives Erkennen, welche lokalen
Prozesse mit bekannten LLM-/Agenten-API-Endpunkten sprechen -- kein Eingriff, keine
Blockierung, reine Beobachtung für das Dashboard (siehe webui/app.py).

Endpoint-Agent-Ansatz (psutil, keine Root-Rechte nötig) statt netzwerkweitem SPAN/Proxy-
Mitlesen -- siehe core/security/llm_endpoints.py für die Begründung und die Grenzen des
DNS-Abgleichs."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import psutil

from core.security.llm_endpoints import OLLAMA_LOCAL_PORTS, resolve_endpoint_ips

logger = logging.getLogger(__name__)


@dataclass
class DetectedConnection:
    pid: Optional[int]
    process_name: str
    process_exe: str
    remote_ip: str
    remote_port: int
    service: str
    status: str
    detected_at: float


def sample_once() -> list[DetectedConnection]:
    """Ein einmaliger Scan aller aktiven Verbindungen dieses Rechners. Verbindungen ohne
    zugreifbare PID (z.B. Prozesse anderer Nutzer ohne Root) werden übersprungen statt
    einen Fehler auszulösen -- erwartbares, nicht außergewöhnliches psutil-Verhalten ohne
    erhöhte Rechte."""
    endpoint_ips = resolve_endpoint_ips()
    now = time.time()
    results: list[DetectedConnection] = []

    try:
        connections = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError):
        logger.warning("Kein Zugriff auf systemweite Verbindungsliste (psutil.AccessDenied).")
        return results

    for conn in connections:
        if conn.status != psutil.CONN_ESTABLISHED or conn.raddr is None:
            continue

        remote_ip, remote_port = conn.raddr.ip, conn.raddr.port

        service = endpoint_ips.get(remote_ip)
        if service is None:
            if remote_port in OLLAMA_LOCAL_PORTS and remote_ip in ("127.0.0.1", "::1"):
                service = "Ollama (lokal)"
            else:
                continue

        process_name = ""
        process_exe = ""
        if conn.pid is not None:
            try:
                proc = psutil.Process(conn.pid)
                process_name = proc.name()
                process_exe = proc.exe()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass  # Prozess zwischenzeitlich beendet oder nicht einsehbar -- Verbindung bleibt trotzdem sichtbar

        results.append(DetectedConnection(
            pid=conn.pid,
            process_name=process_name,
            process_exe=process_exe,
            remote_ip=remote_ip,
            remote_port=remote_port,
            service=service,
            status=conn.status,
            detected_at=now,
        ))

    return results


def run_sampler_loop(
    interval_seconds: float,
    stop_event: threading.Event,
    on_sample=None,
    pause_event: Optional[threading.Event] = None,
) -> None:
    """Läuft bis stop_event gesetzt wird. on_sample(conns) wird nach jedem Durchlauf
    aufgerufen (z.B. core.memory.database.Database.log_detected_connections) -- getrennt
    von sample_once(), damit Letzteres auch isoliert für den On-Demand-Chat-Tool-Aufruf
    (core/system/tool_registry.py) nutzbar bleibt, ohne eine DB-Verbindung zu brauchen.

    Ist pause_event gesetzt (siehe desktop_agent/tray.py: "Überwachung pausieren"), wird
    sample_once() für diesen Takt übersprungen, aber die Schleife bleibt am Leben -- beim
    Fortsetzen ist kein neuer Thread nötig."""
    while not stop_event.is_set():
        if pause_event is None or not pause_event.is_set():
            try:
                conns = sample_once()
                if on_sample is not None and conns:
                    on_sample(conns)
            except Exception:  # noqa: BLE001
                logger.exception("Fehler im Verbindungs-Sampler-Durchlauf -- Schleife läuft weiter.")
        stop_event.wait(interval_seconds)
