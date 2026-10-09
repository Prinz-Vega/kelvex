# Kelvex Security

Kelvex Security detects and classifies Shadow-AI / Agentic-AI activity on endpoints in
your own network — on-premise, no data leaves your infrastructure. This repository
contains **Kelvex Core** (the central dashboard/backend) and the **Kelvex Agent** (the
lightweight endpoint client).

1 endpoint is always free. Beyond that, a hardware-bound, time-limited license is
required — see [`core/licensing/`](core/licensing/) and the in-app "Licenses" page.
See [`LICENSE`](LICENSE) for terms.

## Components

- **`webui/`** — Kelvex Core: a Flask dashboard (port 8822) that approves/revokes
  agents, shows detected connections, pushes configuration to agents, checks for and
  applies Core updates (online or via an uploaded file), and manages licenses.
- **`desktop_agent/`** — Kelvex Agent: a system-tray client (Windows/Linux) that
  detects local processes talking to known LLM/agent API endpoints
  (`core/security/connection_monitor.py` + `llm_endpoints.py`, psutil-based, no root
  needed) and reports them to Core over a per-agent approval + Bearer-token flow.
- **`core/licensing/`** — Ed25519-signed, hardware-bound, time-limited license
  verification, fully offline (no license server, no network call).
- **`core/memory/database.py`** — SQLite storage for detected connections, agent
  registration/approval, admin-OTP codes, and Core-pushed agent configuration.
- **`deploy/license_tool.py`** — CLI for issuing licenses (requires a private signing
  key that is never part of this repository).

## Running Kelvex Core

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python webui/app.py
```

Dashboard at `http://localhost:8822`. From there, download/install the Kelvex Agent
for Linux or Windows (one-click install scripts served by Core itself) and approve it
under "Agents".

## Running the Agent manually (development)

```bash
.venv/bin/python desktop_agent/tray.py
```

On first run it asks for the Kelvex Core address. After that, local settings are
protected by an admin-generated one-time code (see Core's dashboard).

## Licensing

Licenses are Ed25519-signed and hardware-bound — the private signing key never ships
in this repository, only the public key used for offline verification
(`core/licensing/public_key.py`). Tampering with a license file (editing any field by
hand) invalidates its signature and permanently locks that installation from further
activation attempts until a separately issued, signed unban certificate is applied.

For a commercial license beyond the free tier, see [`LICENSE`](LICENSE) for contact
details.
