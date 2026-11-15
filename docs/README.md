# TokenSlim Documentation Index

Welcome to the comprehensive technical documentation for **TokenSlim**, an autonomous, token-efficient software engineering agent with selective AST context extraction, stale-answer detection, and granular Bifrost gateway telemetry.

This repository was developed for the **Geek Room × HackCulture Global AI Hackathon 2026** under:
- **Track 1:** Bifrost Gateway #01 (Model Routing, Telemetry, Reference Pricing & Token Accounting)
- **Track 2:** Tavily Stale-Answer Detection (API Deprecation Screening & Migration Guidance)

---

## Documentation Structure

```text
docs/
├── README.md                          # Central documentation portal (this file)
├── architecture/
│   └── ARCHITECTURE.md                # System architecture, data flow & component design
├── benchmarks/
│   └── BENCHMARK_METHODOLOGY.md       # 12-task benchmark design & token accounting formulas
├── security/
│   └── SECURITY.md                    # Sandboxing model, allowlists & defense mechanisms
├── guides/
│   └── DEMO_GUIDE.md                  # Evaluator walkthrough for Replay vs Live modes
└── development/
    └── CHECKPOINT_REPORTS/            # Historical development & audit reports (CP 0–8)
```

---

## 1. Core Technical Specifications

### [Architecture Specification](architecture/ARCHITECTURE.md)
Detailed architectural blueprint of TokenSlim:
- **Presentation Layer:** Single-Page Web UI and Server-Sent Events (SSE) bus with `Last-Event-ID` auto-reconnect.
- **Control Plane & Persistence:** FastAPI async runtime with SQLite in Write-Ahead Logging (`WAL`) mode.
- **Agent Intelligence Loop:** OODA loop coordinating repository intelligence, selective AST slicing, stale API screening, and Bifrost proxy calls.
- **Sandboxing & Verification:** Atomic search/replace patch application and isolated subprocess test runner.

### [Benchmark Suite & Accounting Methodology](benchmarks/BENCHMARK_METHODOLOGY.md)
The authoritative quantitative methodology evaluating 12 deterministic engineering tasks:
- **Context Token Reduction:** Measured at **31.4%** (slashed from 11,431 to 7,847 tokens; 3,584 prompt tokens spared).
- **Total Simulated Spend:** Measured at **28.4%** reduction (12,631 down to 9,047 tokens).
- **Deterministic Harness Disclosure:** Explains the 12/12 pass rate within the deterministic offline verification harness.
- **Token Accounting Formulas:** Strict taxonomy separating provider-reported tokens (`response.usage`), local estimates (`tiktoken cl100k`), and simulated mock tokens.
- **Audited Reference Pricing Catalog:** Official pricing rates ($/1M tokens) across OpenAI, Anthropic, and Google Cloud.

### [Security Model & Sandboxing Specification](security/SECURITY.md)
Comprehensive containment and defense-in-depth safeguards:
- **Ephemeral Sandboxing:** Clones repos into `%TEMP%\tokenslim_workspaces\run_<id>_\`; host repositories remain strictly immutable.
- **Subprocess Disarmament:** Executes strictly with `shell=False`, restricting binaries to an allowlist (`python`, `pytest`).
- **Process Tree Termination:** Recursive cleanup (`taskkill /F /T /PID` on Windows, `os.killpg` on POSIX) preventing orphan leaks.
- **Credential Scrubbing:** Automatically redacts API keys (`sk-*`, `tvly-*`, `ghp_*`, `Bearer`) from logs, database records, and SSE events.
- **Path Traversal Protection:** Rejects relative escapes (`../`) and external symlinks.

### [Demo & Verification Guide](guides/DEMO_GUIDE.md)
Practical guide for hackathon judges and evaluators:
- **Replay Mode vs Live Execution:** How to run the pre-recorded Pydantic v2 migration trace with zero external dependencies.
- **Live Mode Configuration:** Step-by-step instructions for attaching live Bifrost proxy endpoints and Tavily API keys.
- **Interactive UI Walkthrough:** Guide to the 6 dedicated views (Workspace, Trace, Stale Detector, Diff, Benchmark, and Gateway).

---

## 2. Historical Development & Audit Reports

The full progression of TokenSlim's development across all hackathon milestones is preserved below:

| Milestone Report | Primary Focus & Deliverables |
| :--- | :--- |
| **[Checkpoint 0: Environment Preflight](development/CHECKPOINT_REPORTS/CHECKPOINT_0_ENVIRONMENT_AND_PROJECT_PREFLIGHT_REPORT.md)** | Baseline layout, FastAPI health endpoints, SQLite schema, design system tokens. |
| **[Checkpoint 1: Repository Intelligence](development/CHECKPOINT_REPORTS/CHECKPOINT_1_CORE_REPOSITORY_INTELLIGENCE_REPORT.md)** | AST scanner, symbol tables, LeanCode selective context extraction, line/token budgets. |
| **[Checkpoint 2: Autonomous Coding Engine](development/CHECKPOINT_REPORTS/CHECKPOINT_2_AUTONOMOUS_CODING_ENGINE_REPORT.md)** | Atomic search/replace patch engine, ephemeral workspace cloning, subprocess test runner. |
| **[Checkpoint 3: Bifrost Gateway & Ledger](development/CHECKPOINT_REPORTS/CHECKPOINT_3_BIFROST_INTEGRATION_AND_TOKEN_ACCOUNTING_REPORT.md)** | Upstream Bifrost client, mock fallback adapter, granular token ledger, pricing catalog. |
| **[Checkpoint 4: Tavily Stale-Answer Detection](development/CHECKPOINT_REPORTS/CHECKPOINT_4_TAVILY_STALE_ANSWER_DETECTION_REPORT.md)** | API deprecation screening, dual-mode search, evidence confidence scoring, prompt injection. |
| **[Checkpoint 5: 3-Way Benchmark Suite](development/CHECKPOINT_REPORTS/CHECKPOINT_5_BENCHMARK_AND_STALE_REPAIR_INTEGRATION_REPORT.md)** | 12-task benchmark suite, 3-way evaluation harness, context reduction validation. |
| **[Checkpoint 6: Run Lifecycle & SSE Streaming](development/CHECKPOINT_REPORTS/CHECKPOINT_6_RUN_LIFECYCLE_SSE_AND_EXECUTION_VISIBILITY_REPORT.md)** | Real-time SSE streaming, `Last-Event-ID` reconnection, trace replay, cancelation. |
| **[Checkpoint 7: Reliability & Security Audit](development/CHECKPOINT_REPORTS/CHECKPOINT_7_RELIABILITY_AND_SECURITY_REPORT.md)** | Subprocess disarming, path traversal guards, secret scrubbing, regression suite expansion. |
| **[Checkpoint 8: Final Readiness Report](development/CHECKPOINT_REPORTS/CHECKPOINT_8_FINAL_READINESS_REPORT.md)** | Full system readiness audit, status honesty enforcement, and hackathon submission verification. |

---

## 3. Presentation Materials

Technical presentation assets prepared for the evaluation panel are located in [`presentation/`](../presentation/):
- **[TokenSlim Presentation Brief](../presentation/TokenSlim_Presentation_Brief.md):** 12-slide AI generation brief (Kreyato AI).
- **[Slide Content & Speaker Notes](../presentation/Slide_Content_and_Speaker_Notes.md):** Full slide copy, visual mappings, natural student speaker notes, and Q&A defense points.
- **[Architecture Diagram](../presentation/Architecture_Diagram.png):** High-resolution ($1920 \times 1080$) 4-tier system diagram.
- **[Benchmark Chart](../presentation/Benchmark_Chart.png):** High-resolution ($1920 \times 1080$) 3-way benchmark comparison visualization.
- **[Live Application Screenshots](../presentation/assets/):** 6 desktop application screenshots ($1440 \times 900$) from the live deployment.
