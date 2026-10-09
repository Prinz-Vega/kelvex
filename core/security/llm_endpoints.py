"""Registry bekannter LLM-/Agenten-API-Endpunkte für Phase 1 ("Sichtbarkeit") aus
KELVEX_ROADMAP.md. psutil liefert nur rohe Remote-IP:Port, keine Hostnamen -- Cloud-APIs
laufen oft hinter CDN-/Load-Balancer-IPs, die sich ändern und mit anderen Diensten geteilt
sein können. Statt eine feste IP-Liste zu pflegen, werden die bekannten Domains periodisch
per DNS aufgelöst (TTL-gecacht) und aktive Verbindungen gegen die so gewonnene IP-Menge
abgeglichen. Das ist ein Best-Effort-Ansatz -- mögliche False Positives/Negatives bei
geteilter CDN-Infrastruktur sind bewusst in Kauf genommen, angemessen für den in der
Roadmap selbst beschriebenen Phase-1-Anspruch ("erstmals einen Überblick, ohne dass etwas
blockiert wird"), kein vollständiger/beweissicherer Nachweis.

Lokales Ollama ist zuverlässiger erkennbar: einfacher Loopback-Verbindungscheck auf einen
bekannten Port, kein DNS nötig (siehe core/security/connection_monitor.py)."""
from __future__ import annotations

import socket
import time

# Domain -> Dienstname. Liste bewusst auf die in der Roadmap genannten Anbieter
# beschränkt ("OpenAI, Anthropic, Google, lokale Ollama-Instanzen etc.") -- einfach um
# weitere Einträge erweiterbar, sobald Phase 1 produktiv genutzt wird.
KNOWN_ENDPOINTS: dict[str, str] = {
    "api.openai.com": "OpenAI",
    "api.anthropic.com": "Anthropic",
    "generativelanguage.googleapis.com": "Google Gemini",
    "aiplatform.googleapis.com": "Google Vertex AI",
}

# Lokales Ollama lauscht standardmäßig auf diesem Port -- Verbindungen dorthin sind
# eindeutig lokal und brauchen keine DNS-Auflösung.
OLLAMA_LOCAL_PORTS = {11434}

_cache: dict[str, str] = {}
_cache_built_at: float = 0.0


def resolve_endpoint_ips(ttl_seconds: int = 300) -> dict[str, str]:
    """IP -> Dienstname, aus KNOWN_ENDPOINTS per DNS aufgelöst und für ttl_seconds
    gecacht. Einzelne nicht auflösbare Domains (z.B. kein Netz) werden übersprungen,
    nicht der ganze Aufruf abgebrochen -- ein Ausfall einer Domain soll die Erkennung
    der übrigen nicht verhindern."""
    global _cache, _cache_built_at
    now = time.time()
    if _cache and (now - _cache_built_at) < ttl_seconds:
        return _cache

    fresh: dict[str, str] = {}
    for domain, service in KNOWN_ENDPOINTS.items():
        try:
            infos = socket.getaddrinfo(domain, None)
        except (socket.gaierror, socket.timeout):
            continue
        for info in infos:
            ip = info[4][0]
            fresh[ip] = service

    if fresh:
        _cache = fresh
        _cache_built_at = now
        return _cache
    # DNS-Auflösung ist komplett fehlgeschlagen (z.B. kein Netz) -- lieber den alten,
    # abgelaufenen Cache weiterverwenden als jede Verbindung als unbekannt zu behandeln.
    return _cache
