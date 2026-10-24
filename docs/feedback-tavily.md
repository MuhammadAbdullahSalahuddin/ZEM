# Sponsor Technical Feedback: Tavily Search API in ZEM (Round 3)

**Project**: ZEM — Zero-Trust Enforcement Gateway for Model Context Protocol (MCP)  
**Integration Module**: [`src/zem/intel/tavily_enricher.py`](../src/zem/intel/tavily_enricher.py), [`src/zem/intel/cache.py`](../src/zem/intel/cache.py)  
**Use Case**: Real-time threat intelligence enrichment (CVE advisories, PyPI/npm typosquatting detection, and malicious domain verification) for gray-zone AI agent tool calls.

---

## 1. Architecture & Integration Pattern

In ZEM's defense-in-depth pipeline, ~75–85% of MCP tool calls are settled in `<4ms` by deterministic static guards (`PathGuard`, `ShellGuard`, `SecretGuard`, `InstallGuard`). However, when an AI coding agent invokes a gray-zone operation—such as `pip install requests-security-patch` or posting a summary to an unpinned external domain—static AST rules cannot know whether that package was published yesterday as a typosquatted malware payload.

ZEM integrates **Tavily Search API** (`POST https://api.tavily.com/search`) as an on-demand **Live Web Radar (`Enricher`)**:
1. **Trigger**: When the fast NVIDIA Nemotron reasoner flags `needs_intel: true` with an `intel_query` (or when a package/domain detector requests enrichment), `TavilyEnricher.lookup(query)` executes.
2. **Outbound Query Sanitizer (`sanitize_query`)**: Before any network request is made, ZEM scrubs secrets (`AWS`, `GitHub`, `JWT`, high-entropy tokens), email addresses, URL query strings, and local filesystem paths (`/Users/...`, `C:\...`, `../`) so an attacker can never use search queries as an exfiltration side-channel.
3. **SQLite TTL Cache (`IntelCache`)**: Lookups are cached by normalized SHA-256 hash in `~/.zem/intel_cache.db` (default 24h TTL). Repeated checks for the same package or domain resolve in `<1ms` with zero API credit consumption.
4. **Prompt Sandboxing**: Returned `IntelItem` snippets (`title`, `url`, `snippet`, `score`) are angle-bracket neutralized (`<` → `‹`, `>` → `›`), truncated to 300 chars, and sealed inside `<intel><untrusted>...</untrusted></intel>` blocks before being handed to the deep Nemotron reasoner.

---

## 2. What Worked Exceptionally Well

1. **Clean, Zero-Bloat JSON Schema (`search_depth: "basic"`)**:
   - Setting `search_depth="basic"`, `include_answer=False`, and `include_raw_content=False` returns concise, pre-chunked `content` snippets and a calibrated relevance `score` (`0.0–1.0`) in a single HTTP POST call (~300–450ms).
   - Unlike raw SERP scrapers that return HTML boilerplate, Tavily's `content` field is immediately usable inside an LLM security prompt without secondary HTML stripping.
2. **High Signal on Security & Package Registries**:
   - Queries targeting `osv.dev`, `security.snyk.io`, `pypi.org`, `nvd.nist.gov`, and `attack.mitre.org` consistently rank in the top 3 results with relevance scores `>0.90`.
3. **Predictable Latency for Inline Gateways**:
   - With `max_results=5` and `search_depth="basic"`, p50 latency stayed well within our 4.0-second fail-safe timeout budget, and combined with our SQLite TTL cache, amortized latency across an agent coding session drops below `5ms`.

---

## 3. Friction Points & Feature Suggestions for the Tavily Team

1. **Dedicated `"security"` / `"advisory"` Topic Filter**:
   - Currently, Tavily supports `topic="general"` and `topic="news"`. Adding a `topic="security"` preset (prioritizing OSV, NVD, GitHub Security Advisories, Snyk, URLhaus, and MITRE ATT&CK) would make Tavily a drop-in threat-intelligence feed for security gateways without requiring manual `include_domains` lists.
2. **Server-Side PII/Secret Scrubbing Option**:
   - In zero-trust agent gateways, developers worry that an LLM might accidentally include a sensitive token or internal hostname in a generated search query. We built `sanitize_query()` client-side in `src/zem/intel/tavily_enricher.py`, but an optional `"redact_secrets": true` flag on the Tavily API endpoint would be a major enterprise selling point.
3. **Lightweight Head/Batch Lookup for Package Names**:
   - When an AI agent runs `pip install a b c`, being able to pass a batch of 3 short queries in one HTTP round-trip would reduce connection overhead for inline proxy workloads.

