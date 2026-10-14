# ZEM: Zero-Trust Enforcement for Model Context Protocol (MCP)

> **Zero-trust gateway, deterministic guardrails, and real-time telemetry for AI agents and MCP tools.**  
> *Built for the NVIDIA-Nebius AI Hackathon.*

---

## 🛡️ Overview

**ZEM** acts as an inline, zero-trust security gateway between autonomous AI agents and Model Context Protocol (MCP) tool servers. It intercepts tool call invocations at the boundary, applying fail-closed guardrails, structured AI reasoning, real-time threat intelligence, and immutable audit logging.

### Architecture Overview

```mermaid
flowchart TD
    A["AI Agent (e.g. Claude / Cursor / Claude Code)"] -->|MCP Tool Calls (stdio)| B["ZEM Security Gateway"]
    
    subgraph Gateway ["ZEM Pipeline Engine"]
        B --> C{"Deterministic Guards"}
        C -->|Shell / Path / Secret Check| D["Signal Aggregator"]
        D -->|Hard Deny Triggered| E["Block Decision"]
        D -->|Gray Zone| F["Nebius Nemotron Reasoner"]
        F --> G["Final Decision (Allow / Deny / Redact)"]
    end
    
    G --> H[("SqliteAudit Store (~/.zem/zem.db)")]
    
    subgraph Telemetry ["Live SOC Telemetry (R1)"]
        H --> I["FastAPI Gateway API (zem.api)"]
        I -->|Server-Sent Events: /api/stream| J["React 3D SOC Dashboard (web/)"]
        I -->|REST: /api/decisions| J
    end
```

---

## ⚡ API Endpoints (R1)

The ZEM API layer provides read-only telemetry and live streaming access to the gateway audit log:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/healthz` | Health check endpoint returning `{"status": "ok"}`. |
| `GET` | `/api/decisions` | Returns recent audit decisions (newest first). Supports `?limit=50` (max 200). |
| `GET` | `/api/decisions/{call_id}` | Retrieves full audit event record for a specific `call_id` (returns 404 if not found). |
| `GET` | `/api/stream` | Server-Sent Events (SSE) live stream. Pushes new tool call intercepts in real-time as they are recorded. |

---

## 🚀 Quickstart

### Prerequisites
- Python 3.12+ with [`uv`](https://github.com/astral-sh/uv)
- Node.js 18+ and `npm`

### 1. Start the ZEM Telemetry API
```bash
# Launch FastAPI server on port 8000
uv run uvicorn zem.api.app:app --host 127.0.0.1 --port 8000 --reload
```

### 2. Launch the SOC Web Dashboard
```bash
# Navigate to web dashboard
cd web

# Install dependencies (first time only)
npm install

# Start Vite dev server on port 3000
npm run dev
```
Open **`http://localhost:3000`** in your browser. The dashboard automatically detects the running backend and displays:
- **`🟢 LIVE GATEWAY (SSE)`**: Real-time event streaming active.
- **`🟡 DEMO MODE (OFFLINE)`**: Standalone mode using built-in mock telemetry dataset if the backend is not running.

---

## 🧪 Testing & Verification

Run the full verification suite:

```bash
# Run API & unit test suite
uv run python -m pytest tests/unit/test_api_basic.py

# Lint and format check
uv run ruff check src tests

# Static type checking on contract models
uv run mypy --strict src/zem/contracts

# Build frontend production bundle
cd web && npm run build
```

---

## 📁 Repository Structure

```
ZEM/
├── src/zem/
│   ├── api/             # FastAPI backend (app.py, data_source.py)
│   ├── audit/           # SQLite audit logger (store.py)
│   ├── contracts/       # Core Pydantic schemas (models.py - strict read-only)
│   ├── detectors/       # Deterministic guards (shell, path, secrets)
│   ├── pipeline/        # Evaluation orchestrator
│   └── policy/          # YAML policy engine
├── tests/
│   ├── unit/            # Unit tests (test_api_basic.py, etc.)
│   └── contract/        # Contract compliance tests
├── web/                 # React 3D SOC Dashboard (Vite, Tailwind, Three.js)
│   ├── src/             # App.tsx, SocAnalytics.tsx, TiltCard.tsx
│   └── public/          # 3D canvas sequence frames
├── AGENTS.md            # Zero-trust development rules and workspace boundaries
└── pyproject.toml       # Project dependencies & tooling config
```
