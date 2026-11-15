# TokenSlim — Hackathon Presentation Brief & Slide Generation Guide

> **Project Name:** TokenSlim  
> **Subtitle:** Autonomous Token-Efficient Coding Agent with Selective AST Context & Stale-Answer Detection  
> **Event:** Geek Room × HackCulture Global AI Hackathon 2026  
> **Dual Track Alignment:**  
> - **Track 1:** Bifrost Gateway #01 (Model Routing, Telemetry, Reference Pricing & Token Accounting)  
> - **Track 2:** Tavily Stale-Answer Detector (Deprecated API / Syntax Detection & Remediation)  
> **Repository:** [https://github.com/Rakshit414/TokenSlim_GeekRoom](https://github.com/Rakshit414/TokenSlim_GeekRoom)  
> **Live Web Application:** [https://tokenslim-geekroom.onrender.com](https://tokenslim-geekroom.onrender.com)  
> **Verified Reference Commit:** `bba259ac597aee2143e14c1595a5d965eeb8325e`

---

## 1. Executive Summary

**TokenSlim** is an autonomous software engineering agent built to solve two widespread flaws in automated coding workflows:
1. **Context Window Waste:** Naive coding agents dump whole source files into prompts to fix small bugs, which consumes unnecessary tokens, triggers provider rate limits, and degrades LLM reasoning.
2. **Stale Syntax Hallucinations:** Large language models trained on historical data regularly output deprecated or superseded syntax (e.g., Pydantic v1 `.dict()` on modern v2 runtimes), leading to broken builds and failed repair cycles.

TokenSlim addresses both problems directly:
- **LeanCode AST Context Engine:** Parses code using Python's built-in `ast` module to extract only the target function, class, and immediate failure scope. In a 12-task benchmark suite, it cut ingested context tokens from **11,431 to 7,847**, achieving a **31.4% context token reduction** (saving 3,584 prompt tokens). Total simulated tokens dropped from **12,631 to 9,047**, a **28.4% total-token reduction**.
- **Tavily Stale-Answer Detector:** Analyzes directives and code for library version assumptions. When configured with an API key, it queries Tavily for live documentation; when unconfigured, it runs in an offline heuristic mode (`is_simulated = True`). It injects concise migration rules into the prompt before patch generation.
- **Bifrost Gateway & Token Ledger:** Targets upstream Bifrost proxy routing with automatic fallback to a local deterministic mock adapter. Its token ledger strictly separates provider-reported usage, local heuristic estimates (`tiktoken cl100k`), and simulated tokens, with an audited reference pricing catalog ($/1M tokens).
- **Isolated Workspace Sandbox & Subprocess Runner:** Applies atomic search-and-replace patches to isolated `%TEMP%` copies and runs tests through a locked-down subprocess runner (`shell=False`, allowlist binaries, process tree termination via `taskkill`).

---

## 2. Dual-Track Alignment & Operational Status

| Track | Requirement | Implementation in TokenSlim | Current Operational Status in Deployed Demo |
| :--- | :--- | :--- | :--- |
| **Track 1: Bifrost #01** | Unified AI gateway routing, fallback resilience, cost accounting, and request observability. | • `BifrostClient` routing in `agent/bifrost_client.py`<br>• Granular Token Ledger in `agent/metrics.py`<br>• Official reference pricing catalog ($/1M tokens)<br>• Gateway telemetry view in `server/static/` | **Unverified / Offline Simulation:** Upstream live Bifrost connectivity is unverified on the demo deployment. The deployed demo operates via local deterministic mock fallback and recorded replay. |
| **Track 2: Tavily Stale-Answer Detector** | Web search integration to detect and eliminate stale, deprecated, or superseded model outputs. | • AST & prompt claim extraction in `agent/stale_detector.py`<br>• Evidence confidence scoring ($0.0$ to $1.0$)<br>• Concise migration directive injection (e.g., Pydantic v1 `.dict()` &rarr; v2 `.model_dump()`) | **Offline Heuristic Fallback:** Live Tavily API credentials are not configured on the demo host. The detector operates in offline heuristic mode (`is_simulated = True`). |

---

## 3. Verified Benchmark Dataset (`benchmark/results.json`)

*Evaluated Reference Model: `gpt-4o-mini` | Benchmark Suite: 12 Deterministic SE Tasks*

```text
+------------------------------+------------------+-----------------+-----------------------+---------------------+
| Metric                       | Naive Baseline   | LeanCode AST    | LeanCode + Tavily     | Delta (Lean vs Base)|
+------------------------------+------------------+-----------------+-----------------------+---------------------+
| Evaluated Tasks              | 12               | 12              | 12                    | -                   |
| Deterministic Pass Rate      | 100.0% (12/12)*  | 100.0% (12/12)* | 100.0% (12/12)*       | 0.0%                |
| Ingested Context Tokens      | 11,431           | 7,847           | 7,847                 | -3,584 (-31.4%)     |
| Generation Tokens            | 1,200            | 1,200           | 1,200                 | 0.0%                |
| Total Simulated Tokens       | 12,631           | 9,047           | 9,047                 | -3,584 (-28.4%)     |
| Stale Claims Flagged         | 0                | 0               | 6 (simulated)**       | +6 deprecations     |
| Average Run Duration         | 1.22s            | 1.19s           | 1.17s                 | -0.05s              |
+------------------------------+------------------+-----------------+-----------------------+---------------------+
```

> **Important Technical Distinctions:**
> 1. **Context vs Total Token Reductions:**
>    - **Context Token Reduction:** $\frac{11,431 - 7,847}{11,431} = \mathbf{31.4\%}$ (3,584 context tokens spared).
>    - **Total Token Reduction:** $\frac{12,631 - 9,047}{12,631} = \mathbf{28.4\%}$ (including 1,200 generation tokens).
>    - These two metrics measure different parts of the pipeline and are kept strictly distinct.
> 2. **Harness Attribution Disclosure (\*):**
>    - The 12/12 (100.0%) pass rate belongs strictly to the **deterministic offline verification harness** and its mock patch generator. It is **not** evidence of live LLM model generation or live model accuracy.
> 3. **Stale Claim Detection (\*\*):**
>    - The 6 flagged cases were detected and repaired using **simulated/offline heuristic evidence** in the benchmark harness, not external live Tavily HTTP calls.
> 4. **Identical Token Counts in Config B and C:**
>    - Config B (`leancode`) and Config C (`leancode_tavily`) share identical token counts (7,847 context / 9,047 total) because Tavily search queries run out-of-band and are never dumped into the code prompt. The stale detector injects only a single-line guidance directive, leaving extracted AST slices unchanged.

---

## 4. Design Direction & Visual Palette

- **Primary Navy:** `#14213D` (Structure, deep panels, card surfaces, and dark background accents)
- **Base Cream:** `#F4EDE0` (Primary typography, high-contrast headings, and clean backgrounds)
- **Highlight Coral:** `#FF6B5B` (Callouts, deltas, accent badges, active nodes, and data highlights)
- **Aesthetic:** Premium technical engineering portfolio aesthetic: clean layouts, readable typography, clear data tables, restrained decoration, and zero generic AI filler imagery.

---

## 5. Slide-by-Slide Narrative Structure (12 Slides)

The presentation narrative follows a logical engineering progression:

| Slide # | Slide Title | Core Purpose | Primary Visual Asset | Key Content |
| :---: | :--- | :--- | :--- | :--- |
| **1** | **The Engineering Problem** | Introduce TokenSlim, its goals, and hackathon track alignment. | Title Card in Navy/Cream/Coral with Track 1 & Track 2 badges. | Project title, student introduction, dual-track focus (Bifrost Gateway #01 + Tavily Stale-Answer Detection), and high-level goal: eliminating context waste and obsolete API syntax. |
| **2** | **Why Existing Coding Workflows Fail** | Explain why dumping files wastes tokens and why models write stale code. | Context comparison diagram (Full File Concatenation vs AST Slice). | Full-file ingestion wastes tokens, inflates latency, and dilutes LLM attention. Training cutoffs cause persistent generation of deprecated syntax (e.g. Pydantic v1 `.dict()` on v2 runtimes). |
| **3** | **TokenSlim's Core Approach** | Present the solution principles behind TokenSlim. | Conceptual closed-loop workflow graphic. | Selective AST context slicing via Python `ast`, pre-prompt deprecation screening, unified gateway routing, atomic search-and-replace patching, and ephemeral test verification. |
| **4** | **System Architecture & Data Flow** | Walk through the implemented system architecture across all four tiers. | `presentation/Architecture_Diagram.png` | 4-tier design: Single-Page Web UI with SSE event bus, FastAPI backend with SQLite WAL persistence, Agent intelligence loop (AST slicer, stale detector, Bifrost client), and isolated sandbox runner. |
| **5** | **LeanCode Context Reduction Engine** | Explain the technical implementation of AST slicing and prompt savings. | `presentation/assets/01-workspace.png` (Coding Workspace & AST Slices Inspector) | Uses standard library `ast.parse` (no heavy embeddings or vector DBs). Extracts target function/class nodes with line limits and `[PARTIAL SLICE]` boundary annotations. Slashes context from 11,431 to 7,847 tokens (-31.4%). |
| **6** | **Tavily Stale-Answer Detection (Track 2)** | Detail how deprecated APIs are detected and corrected before patching. | `presentation/assets/03-stale-detector.png` (Stale-Answer Detector view) | Scans issue directives and code for version keywords. Injects concise migration directives into prompts. Honest disclosure: live Tavily API is unconfigured in demo; runs via offline heuristic simulation. |
| **7** | **Bifrost Gateway & Token Accounting (Track 1)** | Explain gateway routing, mock fallback, and granular token ledger. | `presentation/assets/06-bifrost-gateway.png` (Bifrost Gateway & Reference Pricing) | Multi-model routing client with deterministic mock fallback. Strict metric isolation: provider-reported, local estimates (`tiktoken`), and simulated tokens. Audited reference pricing catalog ($/1M tokens). Live gateway is unverified. |
| **8** | **Benchmark Methodology & Quantitative Results** | Present the verified 12-task benchmark results with rigorous disclosures. | `presentation/Benchmark_Chart.png` & `presentation/assets/05-benchmark-dashboard.png` | Context tokens: 11,431 &rarr; 7,847 (**-31.4%**). Total simulated tokens: 12,631 &rarr; 9,047 (**-28.4%**). 6 stale claims flagged. Full disclosure: 12/12 pass rate belongs to deterministic offline mock harness. |
| **9** | **Actual Product Interface & Execution Workflow** | Showcase the 6-view web UI and replay execution of the Pydantic v2 trace. | `presentation/assets/02-execution-trace.png` (Execution Trace with replay stream) | Built with Vanilla HTML5/CSS/JS. Real-time SSE streaming with `Last-Event-ID` lossless reconnect. Replay mode runs a recorded fixture (`traces/demo_pydantic_v2_migration.json`) with original timestamps preserved. |
| **10** | **Security, Sandboxing & Verification** | Detail sandboxing controls, test runner disarmament, and test coverage. | `presentation/assets/04-diff-verification.png` (Diff viewer & subprocess test output) | Atomic `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` patch blocks. Clones target repos into `%TEMP%` (zero repo mutation). Subprocess test runner uses `shell=False`, allowlists `pytest`, strips credentials, and terminates process trees (`taskkill`). 106 passed tests. |
| **11** | **Current Limitations & Honest Engineering Evaluation** | Candidly disclose what remains simulated, unverified, or incomplete. | Limitations matrix / engineering transparency card. | 1. Bifrost live gateway is unverified (mock fallback).<br>2. Tavily API key is unconfigured (offline heuristic).<br>3. 12/12 benchmark pass rate belongs to deterministic mock harness.<br>4. Replay demo uses recorded fixture.<br>5. AST engine is currently Python-specific. |
| **12** | **Future Scope & Conclusion** | Summarize achievements, future roadmap, and live project access. | Roadmap timeline & links (GitHub repository + live Render app). | Next steps: Tree-sitter for multi-language support (TypeScript, Go, Rust), live multi-model fallback cascades, and GitHub App CI integration. Live demo at `tokenslim-geekroom.onrender.com`. |

---

## 6. Screenshot & Visual Asset Directory Mapping

All assets are located in `presentation/` and `presentation/assets/`:
- `presentation/Architecture_Diagram.png`: High-resolution system architecture diagram in Navy/Cream/Coral.
- `presentation/Benchmark_Chart.png`: High-resolution 3-way benchmark comparison chart with explicit disclosures.
- `presentation/assets/01-workspace.png`: Workspace view with Task Spec and AST Slices Inspector.
- `presentation/assets/02-execution-trace.png`: Execution Trace view with chronological SSE stream.
- `presentation/assets/03-stale-detector.png`: Stale-Answer Detector view with flagged Pydantic claims.
- `presentation/assets/04-diff-verification.png`: Diff & Verification view with unified diff and pytest output.
- `presentation/assets/05-benchmark-dashboard.png`: Benchmark Dashboard with 3-way configuration table.
- `presentation/assets/06-bifrost-gateway.png`: Bifrost Gateway view with model catalog and reference pricing.
