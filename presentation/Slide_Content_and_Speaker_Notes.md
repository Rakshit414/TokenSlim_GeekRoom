# TokenSlim — Slide Content, Visual Assets & Speaker Notes (12-Slide Deck)

> **Project Name:** TokenSlim  
> **Event:** Geek Room × HackCulture Global AI Hackathon 2026  
> **Dual-Track Submission:** Track 1 (Bifrost Gateway #01) & Track 2 (Tavily Stale-Answer Detection)  
> **Repository:** [https://github.com/Rakshit414/TokenSlim_GeekRoom](https://github.com/Rakshit414/TokenSlim_GeekRoom)  
> **Live App:** [https://tokenslim-geekroom.onrender.com](https://tokenslim-geekroom.onrender.com)  
> **Verified Commit:** `bba259ac597aee2143e14c1595a5d965eeb8325e`

---

## Slide 1: The Engineering Problem

- **Slide Number:** 1
- **Slide Title:** **TokenSlim: Autonomous, Token-Efficient Software Engineering Agent**
- **Subtitle:** Solving Context Waste & Deprecated Syntax in Automated Code Repair
- **Visual Asset:** Title Card Graphic in Navy (`#14213D`), Cream (`#F4EDE0`), and Coral (`#FF6B5B`) with Hackathon Track Badges:
  - `Track 1: Bifrost Gateway #01 (Model Routing & Token Ledger)`
  - `Track 2: Tavily Stale-Answer Detector (API Deprecation Screening)`
  - `Live Demo: tokenslim-geekroom.onrender.com`
- **Core Message:** TokenSlim is an autonomous coding agent designed to eliminate context bloat and obsolete code hallucinations by combining compiler-inspired AST slicing with pre-prompt deprecation screening.

### On-Slide Text / Bullet Points:
- **Project Goal:** Build an autonomous coding agent that diagnoses test failures, generates targeted patches, and verifies fixes without wasting prompt tokens or hallucinating deprecated APIs.
- **Track 1 (Bifrost #01):** Unified LLM proxy client with local mock fallback, granular token accounting ledger, and audited reference pricing.
- **Track 2 (Tavily Stale-Answer Detection):** Scans issue directives and code for outdated library syntax (e.g. Pydantic v1 vs v2) and enriches prompts with verified migration directives.
- **Verified Efficiency:** Cuts ingested context tokens by **31.4%** (3,584 prompt tokens spared across 12 benchmark tasks) while maintaining verified test repair.

### Speaker Notes (Student Tone):
> "Hi everyone, I'm excited to present TokenSlim. I built this project for the hackathon to solve two very concrete frustrations I kept running into while building and using AI coding agents.
> 
> First, almost every existing agent dumps entire source files into the prompt just to fix a tiny bug, wasting thousands of tokens and hitting rate limits. Second, because models are trained on older data, they constantly generate deprecated code — like writing Pydantic v1 `.dict()` calls in a v2 codebase — which breaks the build and wastes more repair cycles.
> 
> TokenSlim tackles both issues across two hackathon tracks: Track 1 for Bifrost gateway routing and token accounting, and Track 2 for Tavily stale-answer detection. Over the next few minutes, I'll walk you through how the system works, what we measured in our benchmarks, and what's currently operational versus simulated in our live demo."

### Technical Deep Dive & Q&A Backup:
- **Stack Summary:** FastAPI backend, SQLite in WAL mode, Server-Sent Events (SSE) with `Last-Event-ID` recovery, Vanilla JavaScript single-page application, and native Python `ast` parsing.
- **Hackathon Track Scope:** Addressed both Track 1 (Bifrost Gateway #01) and Track 2 (Tavily Stale-Answer Detection) within a single coherent code repair loop.

---

## Slide 2: Why Existing Coding Workflows Fail

- **Slide Number:** 2
- **Slide Title:** **Why Existing Coding Workflows Fail: Context Bloat & Stale APIs**
- **Visual Asset:** Split Problem Graphic:
  - *Left:* "The Full-File Concatenation Anti-Pattern" (Ingesting thousands of irrelevant lines &rarr; token waste & attention dilution).
  - *Right:* "The Stale API Trap" (Training cutoff &rarr; model emits deprecated Pydantic v1 `.dict()` &rarr; broken build).
- **Core Message:** Naive file dumping inflates costs and degrades model reasoning, while fixed training cutoffs cause agents to persistently hallucinate breaking, deprecated library syntax.

### On-Slide Text / Bullet Points:
- **Problem 1: Context Bloat (Full-File Ingestion):**
  - Most agents concatenate entire source files into the prompt to fix a 5-line defect.
  - Across multi-iteration test-and-repair loops, prompt tokens accumulate rapidly.
  - Provokes the "lost in the middle" attention problem, where models miss critical details buried in boilerplate.
- **Problem 2: Stale Syntax Hallucinations (Training Cutoffs):**
  - LLMs have fixed knowledge cutoffs and favor heavily represented older syntax in their pre-training data.
  - Example: Pydantic v1 `.dict()` and `.parse_obj()` vs Pydantic v2 `.model_dump()` and `.model_validate()`.
  - When models generate deprecated syntax against modern runtimes, automated builds crash immediately.
- **The Result:** Slower execution, unnecessary API spending, and agents stuck in retry loops trying to fix code they broke with obsolete syntax.

### Speaker Notes (Student Tone):
> "Let's look at why standard coding agents struggle in practice.
> 
> Take a look at the left side of this slide. When a typical agent tries to fix a function in `schemas.py`, it doesn't just read that function — it dumps the entire file, plus three other imported files, into the prompt. That's easily 10,000 tokens per call. When you run an agent through three or four iterative repair cycles, that context overhead multiplies fast. Research has also shown that when you drown the model in boilerplate, its reasoning accuracy actually drops because the relevant code gets lost in the middle.
> 
> The second problem on the right is even more annoying: stale syntax. Large language models were trained on millions of repositories written before major library upgrades. If you ask a model to write a Pydantic model today, it still instinctively outputs `.dict()` instead of `.model_dump()`. The code crashes at runtime with an `AttributeError`, and the agent burns more tokens trying to debug its own outdated suggestion."

### Technical Deep Dive & Q&A Backup:
- **Needle-in-a-Haystack Problem:** Academic literature (e.g. Liu et al., *Lost in the Middle*) confirms that transformer attention degrades when key information is placed in the middle of long contexts.
- **Empirical Token Waste:** In our 12-task benchmark suite, naive full-file concatenation consumed 11,431 context tokens. Slicing down to relevant AST nodes reduced this to 7,847 tokens without sacrificing repair capability.

---

## Slide 3: TokenSlim's Core Approach

- **Slide Number:** 3
- **Slide Title:** **TokenSlim's Core Approach: Precision Slicing & Pre-Prompt Screening**
- **Visual Asset:** Conceptual Closed-Loop Flowchart (Navy background with Coral accents):
  `Failing Test` &rarr; `AST Slicing (LeanCode)` &rarr; `Stale Screening (Tavily)` &rarr; `Bifrost Client` &rarr; `Atomic Patch` &rarr; `Ephemeral Verification`.
- **Core Message:** Instead of sending whole files or trusting raw model output, TokenSlim slices minimal structural AST nodes, screens for deprecated APIs upfront, and validates patches in an ephemeral sandbox.

### On-Slide Text / Bullet Points:
- **Compiler-Inspired AST Slicing (LeanCode Engine):**
  - Uses Python's native `ast` module to extract only the target function or class definition involved in the failure.
  - Injects `[PARTIAL SLICE]` boundary annotations so the model knows the snippet is deliberately scoped.
- **Pre-Prompt Stale API Screening (Tavily Detector):**
  - Parses directives and AST symbols for version-sensitive signatures before generating code.
  - Injects concise migration instructions directly into the LLM system prompt.
- **Atomic Search/Replace Patching:**
  - Enforces `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` blocks rather than full-file rewrites.
- **Ephemeral Sandbox Verification:**
  - Executes isolated `pytest` runs in temporary directory clones, exiting immediately once tests pass.

### Speaker Notes (Student Tone):
> "To fix these issues, I designed TokenSlim around four core principles.
> 
> First, instead of using heavy vector databases or embeddings that add latency, I used Python's built-in `ast` module. When a test fails at a specific line, our repository scanner finds the exact AST node for that function and extracts only those lines. We tag them with a comment saying `[PARTIAL SLICE]` so the model doesn't think the rest of the file was deleted.
> 
> Second, before we even call the LLM to write a patch, our Tavily detector screens the prompt and code for deprecated syntax. If it detects a Pydantic v1 pattern in a v2 task, it injects a one-line directive like: 'Use .model_dump() instead of .dict()'.
> 
> Third, the model generates atomic search-and-replace blocks rather than rewriting entire files.
> 
> And fourth, we verify everything in an ephemeral sandbox copy of the repo, terminating as soon as the test passes. Let's look at how these pieces connect in the architecture."

### Technical Deep Dive & Q&A Backup:
- **Why AST over RAG/Embeddings:** For code repair, symbol hierarchies and call graphs are deterministic. AST parsing takes milliseconds, costs zero tokens, and doesn't require embedding model calls or vector database indexing.
- **Early Exit Mechanism:** The loop terminates immediately on the first iteration where the targeted test suite exits with return code 0, preventing wasted follow-up iterations.

---

## Slide 4: System Architecture & Data Flow

- **Slide Number:** 4
- **Slide Title:** **System Architecture & Data Flow**
- **Visual Asset:** `presentation/Architecture_Diagram.png` (Displaying the 4-tier architecture in Navy `#14213D`, Cream `#F4EDE0`, and Coral `#FF6B5B`).
- **Core Message:** TokenSlim connects a reactive web frontend, an asynchronous FastAPI control plane, an AST-driven intelligence loop, and an isolated sandbox into a dependable pipeline.

### On-Slide Text / Bullet Points:
- **Tier 1: Presentation & Real-Time Telemetry (`server/static/`)**
  - Single-page application with 6 dedicated views: Workspace, Trace, Stale Detector, Diff, Benchmark, and Bifrost Gateway.
  - Server-Sent Events (SSE) with `Last-Event-ID` header support for lossless reconnection.
- **Tier 2: Control Plane & Storage (`server/app.py`, `server/database.py`)**
  - FastAPI asynchronous endpoints for runs, benchmarks, and gateway configuration.
  - SQLite database configured with Write-Ahead Logging (`PRAGMA journal_mode=WAL`) for concurrent streaming writes and reads.
- **Tier 3: Agent Intelligence Engine (`agent/`)**
  - Autonomous OODA loop coordinating AST context slicing, stale API screening, and Bifrost gateway calls.
  - Granular token accounting ledger (`agent/metrics.py`) separating provider, estimated, and simulated usage.
- **Tier 4: Sandbox & Verification (`agent/workspace.py`, `agent/verification.py`)**
  - Clones repositories to isolated `%TEMP%` directories.
  - Executes subprocess test runners with `shell=False`, process tree termination (`taskkill`), and credential stripping.

### Speaker Notes (Student Tone):
> "This diagram shows the complete system architecture as implemented in our repository.
> 
> On the left is our frontend. It's a single-page app built in vanilla JavaScript and CSS — no React or heavy build toolchains. It connects to the backend over Server-Sent Events. If your connection drops and you reconnect, the client passes a `Last-Event-ID` header, and the backend replays every missed event in exact order from SQLite before resuming the live stream.
> 
> In the control plane, FastAPI handles incoming requests, and SQLite stores run state in WAL mode so streaming event writes never block dashboard reads.
> 
> The core intelligence engine in the third column runs the loop: it maps the repo, pulls AST slices, runs the stale-answer detector, and formats prompts for the Bifrost client.
> 
> Finally, in the fourth column, patches are applied to an isolated `%TEMP%` clone. Tests run in subprocesses with `shell=False` and strict process tree termination. Your actual working repository is never touched."

### Technical Deep Dive & Q&A Backup:
- **Crash Recovery:** If the server is killed mid-run, the lifespan handler on startup queries SQLite for runs stuck in `running` status and marks them as `interrupted`.
- **Database Schema:** Tables include `runs`, `run_events` (with autoincrementing integer IDs for SSE ordering), and `llm_calls` (storing prompt, completion, tokens, and simulation flags).

---

## Slide 5: LeanCode Context Reduction Engine

- **Slide Number:** 5
- **Slide Title:** **LeanCode Context Engine: AST Slicing in Practice**
- **Visual Asset:** `presentation/assets/01-workspace.png` (Coding Workspace view showing repository scope, task directive, and the AST Slices Inspector).
- **Core Message:** By parsing native AST nodes rather than dumping whole files, LeanCode achieves a verified 31.4% context token reduction across our 12-task benchmark.

### On-Slide Text / Bullet Points:
- **Lightweight AST Parsing (`agent/repository.py`):**
  - Uses Python's standard `ast` module — zero vector database dependencies or external indexing overhead.
  - Maps classes, methods, decorators, and line ranges into a structural symbol index.
- **Targeted Slicing (`agent/context.py`):**
  - Extracts only the function or class enclosing the failure site, along with immediate decorators and module imports.
  - Enforces simultaneous ceilings on token budget, line count, and character length.
- **`[PARTIAL SLICE]` Boundary Annotations:**
  - Explicitly tags extracted blocks: `// [PARTIAL SLICE: Lines X-Y of Total Z Lines]`.
  - Prevents the LLM from hallucinating that truncated snippets are complete files.
- **Measured Context Token Reduction:**
  - Naive Baseline: **11,431 context tokens**
  - LeanCode AST: **7,847 context tokens**
  - **Context Reduction: 31.4% (3,584 context tokens spared)**

### Speaker Notes (Student Tone):
> "Here is our Coding Workspace in the live application, showing our AST Slices Inspector.
> 
> When a test fails, the agent doesn't send the entire file. `agent/repository.py` walks the Python AST and builds a symbol map of every class, function, and decorator. Once we know the failure line from the pytest traceback, `agent/context.py` extracts just that specific function node.
> 
> One problem we hit early on was that the LLM would see a truncated function and assume the rest of the file had been deleted. To fix that, we added an explicit boundary annotation at the top of every slice: `// [PARTIAL SLICE: Lines X-Y of Total Z Lines]`. That told the model exactly where it was in the file.
> 
> In our 12-task benchmark suite, naive full-file ingestion used 11,431 context tokens. LeanCode AST slicing brought that down to 7,847 tokens. That is a **31.4% reduction in ingested context tokens**, saving 3,584 tokens without missing any critical context."

### Technical Deep Dive & Q&A Backup:
- **Resource Safeguards:** Single-file parsing ceiling of 500 KB (`MAX_FILE_BYTES`) and total repository scan ceiling of 20 MB (`MAX_SCAN_BYTES`) to prevent memory exhaustion.
- **Token Estimation Formula:** Uses `tiktoken` (`cl100k_base`) with fallback to `len(text) // 4`, explicitly stored with `is_estimated = True`.

---

## Slide 6: Tavily Stale-Answer Detection (Track 2)

- **Slide Number:** 6
- **Slide Title:** **Tavily Stale-Answer Detector: Deprecation Screening (Track 2)**
- **Visual Asset:** `presentation/assets/03-stale-detector.png` (Stale-Answer Detector view showing flagged Pydantic v1 `.dict()` patterns, offline evidence, and verified migration rules).
- **Core Message:** TokenSlim detects deprecated API assumptions in directives and code, injecting concise migration directives into prompts before patch generation.

### On-Slide Text / Bullet Points:
- **The Challenge in Track 2:**
  - Code models continuously emit deprecated methods (e.g. Pydantic v1 `.dict()` instead of v2 `.model_dump()`).
- **Claim Extraction & Dual-Mode Search (`agent/stale_detector.py`):**
  - Scans user directives and code for library version assumptions and deprecated signatures.
  - **Live Mode:** Queries Tavily Search API when `TAVILY_API_KEY` is configured.
  - **Offline Heuristic Fallback:** Uses local heuristic rule matching when unconfigured (`is_simulated = True`).
- **Confidence Scoring & Prompt Enrichment:**
  - Computes a heuristic evidence confidence score ($0.0$ to $1.0$).
  - Injects concise migration instructions directly into the LLM system prompt.
  - Corrected **6 out of 6** stale claims in the benchmark evaluation.
- **Honest Status Disclosure:**
  - Live Tavily API credentials are not configured on the public Render demo; it operates in its offline heuristic simulation fallback.

### Speaker Notes (Student Tone):
> "Now let's talk about Track 2: the Tavily Stale-Answer Detector.
> 
> A major pain point with coding agents is that their training data is frozen. When Pydantic moved from v1 to v2, `.dict()` was deprecated in favor of `.model_dump()`. But LLMs still write `.dict()` because it appeared millions of times in their training data.
> 
> In TokenSlim, `agent/stale_detector.py` inspects the task directive and code for library version keywords. In live mode, it queries the Tavily Search API to pull current documentation. In our deployed demo, because we don't have live Tavily API keys configured, it automatically falls back to an offline heuristic simulation mode, clearly flagged as `is_simulated = True`.
> 
> When it detects a stale pattern, it calculates an evidence score and injects a concise one-line rule into the prompt, telling the model: 'Use .model_dump() instead of .dict()'. In our 12-task benchmark, it flagged all 6 deprecation instances, allowing the agent to generate valid v2 code on the first attempt."

### Technical Deep Dive & Q&A Backup:
- **Heuristic Confidence Formula:** Evaluates keyword overlap, domain authority, and migration keywords to produce an auditable score between $0.0$ and $1.0$.
- **Why Config B and C Have Identical Tokens:** Tavily searches run as out-of-band tool calls and are not dumped into the prompt. The stale detector adds only a single concise guidance line, keeping extracted AST context tokens identical (7,847 tokens).

---

## Slide 7: Bifrost Gateway & Token Accounting (Track 1)

- **Slide Number:** 7
- **Slide Title:** **Bifrost Gateway & Token Accounting Ledger (Track 1)**
- **Visual Asset:** `presentation/assets/06-bifrost-gateway.png` (Bifrost Gateway view showing model catalog, reference pricing table, and telemetry status).
- **Core Message:** TokenSlim integrates upstream Bifrost routing with a resilient mock fallback and a granular token ledger that separates provider, estimated, and simulated usage.

### On-Slide Text / Bullet Points:
- **Bifrost Gateway Routing (`agent/bifrost_client.py`):**
  - Unified client routing requests to the Bifrost HTTP proxy.
  - Automatic fallback to a local deterministic mock adapter if the gateway is unreachable or unconfigured.
- **Strict Separation in Token Accounting (`agent/metrics.py`):**
  - **Provider-Reported Usage:** Captured directly from HTTP response headers (`response.usage`).
  - **Locally Estimated Usage:** Heuristic `tiktoken` counts calculated pre-request (`is_estimated = True`).
  - **Simulated / Mock Usage:** Deterministic fixture tokens (`is_simulated = True`).
- **Official Audited Reference Pricing Catalog:**
  - Audited rates in USD per 1M tokens across OpenAI, Anthropic, and Google Cloud models.
  - Unconfigured models log `None` rather than inventing speculative numbers.
- **Honest Status Disclosure:**
  - Live Bifrost gateway connectivity is unverified on the public Render deployment; the demo runs in offline mock/replay mode.

### Speaker Notes (Student Tone):
> "For Track 1, we implemented the Bifrost Gateway client and our granular token accounting ledger.
> 
> Centralized gateway routing is critical for production AI systems to handle model fallbacks and telemetry. Our client targets the Bifrost proxy, but if the gateway is unconfigured or unreachable — which is the case on our public Render demo — it falls back gracefully to a local deterministic mock adapter without crashing.
> 
> What I really focused on here was accounting honesty in `agent/metrics.py`. A lot of agent tools blur the line between what the model provider actually billed you and what was just estimated locally. In TokenSlim:
> - Provider-reported tokens come strictly from HTTP response headers.
> - Locally estimated tokens from `tiktoken` are explicitly marked with `is_estimated = True`.
> - Mock or offline benchmark tokens are tagged `is_simulated = True`.
> 
> We also built an audited reference pricing table based on official provider documentation, giving users transparent visibility into theoretical model costs."

### Technical Deep Dive & Q&A Backup:
- **Handling Missing Gateway Data:** If the gateway is not connected, provider tokens are stored as `None` rather than synthesized, preventing contaminated billing records.
- **Pricing Catalog Coverage:** Rates verified as of 2026-11-14 for `gpt-4o-mini` ($0.15/$0.60), `gpt-4o` ($2.50/$10.00), `claude-3-5-sonnet` ($3.00/$15.00), and `gemini-1.5-flash` ($0.075/$0.30).

---

## Slide 8: Benchmark Methodology & Quantitative Results

- **Slide Number:** 8
- **Slide Title:** **Benchmark Methodology & Quantitative Results**
- **Visual Asset:** `presentation/Benchmark_Chart.png` (Authoritative bar chart and summary table in Navy `#14213D` and Coral `#FF6B5B`).
- **Core Message:** Across 12 deterministic engineering tasks, LeanCode AST slicing cuts context tokens by 31.4% and total simulated tokens by 28.4%.

### On-Slide Text / Bullet Points:
- **Authoritative Dataset (`benchmark/results.json`):**
  - Evaluated 12 deterministic software repair tasks using `gpt-4o-mini` as the reference model.
- **Ingested Context Tokens (Prompt AST / Files):**
  - Naive Baseline: **11,431 tokens**
  - LeanCode AST: **7,847 tokens**
  - LeanCode + Tavily: **7,847 tokens**
  - **Context Token Reduction: 31.4% (3,584 tokens saved)**
- **Total Simulated Tokens Spent (Context + 1,200 Generation):**
  - Naive Baseline: **12,631 tokens**
  - LeanCode AST: **9,047 tokens**
  - LeanCode + Tavily: **9,047 tokens**
  - **Total-Token Reduction: 28.4% (3,584 tokens saved)**
- **Stale Claims Flagged:** **6 out of 6** detected and repaired in Configuration C.
- **Crucial Methodological Disclosure:**
  - The 12/12 (100.0%) pass rate belongs to the **deterministic offline verification harness** and its mock patch generator. It is **not** evidence of live LLM model generation.

### Speaker Notes (Student Tone):
> "Here are the actual numbers from our benchmark run in `benchmark/results.json`.
> 
> We evaluated 12 deterministic software engineering repair tasks across three configurations: Config A is Naive Baseline with full file concatenation; Config B is LeanCode with AST slicing; and Config C adds Tavily stale-answer detection.
> 
> Looking at ingested context tokens: Naive consumed 11,431 tokens. LeanCode AST slicing brought that down to 7,847 tokens. That is a **31.4% reduction in context tokens**, saving 3,584 prompt tokens across the 12 tasks.
> 
> When you include simulated generation tokens, total spend dropped from 12,631 to 9,047 tokens, which is a **28.4% total-token reduction**.
> 
> In Configuration C, the detector flagged all 6 deprecation claims.
> 
> Now, I want to be 100% transparent about the pass rate: all 12 tasks passed, but that 12/12 pass rate belongs to our deterministic offline verification harness and its mock patch generator. We do not claim this as proof of 12 live LLM runs. What it proves is that our AST slicing and repair architecture works reliably end-to-end."

### Technical Deep Dive & Q&A Backup:
- **Why Separate Context and Total Reduction:** Context reduction (31.4%) measures the prompt savings achieved by AST slicing. Total reduction (28.4%) accounts for completion/generation tokens as well. Keeping them distinct avoids conflating input savings with total pipeline spend.
- **Line-Ending Normalization:** Initial draft reports noted minor token variations (11,433 vs 11,431) due to Windows CRLF vs POSIX LF character counts in local checkouts. The authoritative dataset in `benchmark/results.json` verifies 11,431.

---

## Slide 9: Actual Product Interface & Execution Workflow

- **Slide Number:** 9
- **Slide Title:** **Actual Product Interface & Execution Workflow**
- **Visual Asset:** Split Screenshot:
  - *Left:* `presentation/assets/02-execution-trace.png` (Execution Trace with chronological SSE events).
  - *Right:* `presentation/assets/04-diff-verification.png` (Diff & Verification view showing unified diff and test output).
- **Core Message:** TokenSlim provides a transparent, reactive web interface powered by real-time Server-Sent Events, complete with a deterministic replay mode for offline evaluation.

### On-Slide Text / Bullet Points:
- **Zero-Build Vanilla Web UI (`server/static/`):**
  - Lightweight single-page app built with HTML5, CSS, and vanilla JavaScript — zero node build steps or hydration overhead.
- **Real-Time SSE Streaming:**
  - Streams run progress over HTTP: baseline test results, AST slices, prompt dispatches, diffs, and verification logs.
  - Native `Last-Event-ID` support restores missed events in chronological order on reconnect.
- **Deterministic Replay Demonstration:**
  - Bundled recorded fixture: `traces/demo_pydantic_v2_migration.json`.
  - Replays the complete diagnostic and repair lifecycle for Pydantic v2 migration without requiring live API keys.
  - Preserves original event timestamps and clearly displays "REPLAY MODE" in the UI.

### Speaker Notes (Student Tone):
> "Let's look at the actual user interface running on Render right now.
> 
> On the left is the Execution Trace view. Everything the agent does is streamed live over Server-Sent Events: baseline test failures, repository mapping milestones, AST slice extraction, and verification results. Because we use native browser `EventSource` with `Last-Event-ID`, if your connection hiccups, the server replays any missed events in order before resuming live output.
> 
> On the right is our Diff and Verification view. Once a fix is generated, the UI renders a clean unified diff and shows the actual subprocess pytest output.
> 
> To allow judges to test the app without requiring live API keys, we built a replay mode. It plays back a recorded execution fixture of a Pydantic v2 migration. Every event timestamp is preserved from the original recording, and the UI explicitly labels it as 'REPLAY MODE' so there's no confusion with live model calls."

### Technical Deep Dive & Q&A Backup:
- **Frontend Performance:** Eliminating modern JavaScript frameworks kept initial page weight under 36 KB, allowing sub-second initial load times even on free-tier hosting.
- **Replay Integrity:** The replay runner reads directly from `traces/demo_pydantic_v2_migration.json`, feeding the exact event payload into the event bus to demonstrate system capabilities deterministically.

---

## Slide 10: Security, Sandboxing & Verification

- **Slide Number:** 10
- **Slide Title:** **Security, Sandboxing & Verification**
- **Visual Asset:** Security Controls Overview referencing test results from `presentation/assets/04-diff-verification.png`:
  - `106 / 106 Automated Pytest Tests Passing`
  - `Ephemeral %TEMP% Workspace Sandboxing`
  - `shell=False Disarmament`
  - `Process Tree Termination (taskkill /F /T)`
- **Core Message:** TokenSlim enforces defensive sandboxing boundaries, credential stripping, and process termination, backed by 106 automated regression tests.

### On-Slide Text / Bullet Points:
- **Ephemeral Workspace Sandbox (`agent/workspace.py`):**
  - Clones repositories to isolated `%TEMP%\tokenslim_workspaces\run_<id>_\` directories.
  - **Zero Repo Mutation:** Live project files are never modified directly.
  - Directory traversal protection rejects relative path escapes (`../../`) and external symlinks.
- **Subprocess Runner Disarmament (`agent/verification.py`):**
  - Restricts execution strictly to an allowlist of test runners (`pytest`, `python`).
  - Executes with `shell=False`, preventing shell command-chaining attacks (`&&`, `||`, `;`, `|`).
  - Cross-platform process tree termination (`taskkill /F /T` on Windows, `os.killpg` on POSIX) eliminates orphan processes.
  - Strips API keys and authorization headers from the subprocess environment.
- **Automated Test Coverage:**
  - **106 automated tests** in pytest suite passing in ~28 seconds.

### Speaker Notes (Student Tone):
> "Any time you build an agent that executes code in a terminal, security has to be handled defensively.
> 
> In TokenSlim, the agent never touches your actual repository files. When a run starts, `agent/workspace.py` creates an isolated clone in a temporary `%TEMP%` directory. All edits and test executions happen inside that clone.
> 
> In `agent/verification.py`, we strictly disarmed the test runner:
> - It executes with `shell=False`, so command injection like `pytest; rm -rf /` is structurally impossible.
> - It only permits approved binaries from our allowlist: `pytest` and `python`.
> - It sanitizes the environment, stripping out API keys and credentials before the subprocess launches.
> - If a test hangs in an infinite loop, our process tree termination kills the runner and any child processes cleanly.
> 
> We backed all of this with **106 automated tests** in our pytest suite, all passing in about 28 seconds."

### Technical Deep Dive & Q&A Backup:
- **Symlink Defense:** `os.path.realpath` is evaluated to ensure symlinks do not resolve outside the sandbox boundary.
- **Subprocess Allowlist:** If an LLM or directive attempts to pass an unapproved binary (e.g. `curl`, `bash`, `powershell`), `agent/verification.py` throws a `ValueError` immediately.

---

## Slide 11: Current Limitations & Engineering Evaluation

- **Slide Number:** 11
- **Slide Title:** **Current Limitations & Honest Engineering Evaluation**
- **Visual Asset:** Limitations Matrix / Engineering Transparency Card:
  - `Bifrost Live Gateway: Unverified (Mock Fallback Active)`
  - `Tavily Search: Unconfigured (Offline Heuristic Fallback Active)`
  - `Benchmark Pass Rate: Deterministic Offline Harness (Not Live LLM Proof)`
  - `Replay Mode: Recorded Fixture (Not Fresh Execution)`
  - `Language Scope: Python AST Only`
- **Core Message:** Engineering integrity requires being candid about what was built, what was measured offline, and what remains unverified or simulated in the deployed prototype.

### On-Slide Text / Bullet Points:
- **1. Gateway Connectivity:**
  - Upstream Bifrost live connectivity is unverified on the demo deployment.
  - The demo uses local deterministic mock adapters and recorded trace replay.
- **2. Search Credentials:**
  - Live Tavily API credentials are not configured on the public host.
  - The stale-answer detector runs in its offline heuristic simulation fallback.
- **3. Benchmark Interpretation:**
  - The 12/12 pass rate belongs to the deterministic offline verification harness with mock patches.
  - It demonstrates harness reliability and AST slice sufficiency, not live LLM repair performance.
- **4. Replay Demonstration:**
  - The Pydantic v2 migration demo is a pre-recorded fixture, not a fresh live model run.
- **5. Language Scope:**
  - AST parsing currently relies on Python's native `ast` module and does not yet support multi-language codebases (e.g. JavaScript, Go).

### Speaker Notes (Student Tone):
> "As an engineering student, I think it's vital to be completely honest about what is live versus what is simulated in a hackathon project.
> 
> First, our live Bifrost integration is currently unverified on the public Render host. The client code is implemented, but in the deployed demo, it runs using our local deterministic mock fallback.
> 
> Second, we do not have live Tavily API keys configured on the deployment. The stale-answer detector is using its offline heuristic mode, matching known deprecation patterns locally.
> 
> Third, regarding our benchmark: the 12/12 pass rate is from our deterministic offline verification harness using mock patches. It proves our slicing logic and test runner work together seamlessly, but it should not be taken as proof of live LLM model accuracy.
> 
> Fourth, the Pydantic v2 migration in the UI is a recorded replay fixture.
> 
> And finally, our AST slicer currently only works on Python code because it uses Python's standard library `ast` module. Knowing these boundaries helps us focus on what actually needs to be built next."

### Technical Deep Dive & Q&A Backup:
- **Likely Judge Question:** *Why did you evaluate with mock patches instead of live LLMs in the benchmark?*  
  **Answer:** *To establish a reproducible, deterministic baseline. Live LLM outputs fluctuate across runs, temperatures, and rate limits. By using a deterministic harness, we could isolate and verify the exact context token savings of AST slicing (31.4%) independently of LLM stochasticity.*
- **Likely Judge Question:** *Can the system run live if keys are supplied?*  
  **Answer:** *Yes. If `BIFROST_API_KEY` or `TAVILY_API_KEY` are provided in `.env`, the client code executes live HTTP requests. The fallback architecture was designed specifically to ensure graceful degradation when keys are absent.*

---

## Slide 12: Future Scope & Conclusion

- **Slide Number:** 12
- **Slide Title:** **Future Scope & Conclusion**
- **Visual Asset:** Roadmap Timeline & Project Access Badges:
  - `Phase 1 (Delivered): AST Slicer, Stale Detector, Token Ledger, 6-View UI, 106 Tests`
  - `Phase 2: Tree-sitter AST Slicing (TypeScript, Go, Rust)`
  - `Phase 3: Live Bifrost Multi-Model Fallback Cascades`
  - `Phase 4: Autonomous GitHub App with Pull Request Generation`
  - `Repository: github.com/Rakshit414/TokenSlim_GeekRoom`
  - `Live App: tokenslim-geekroom.onrender.com`
- **Core Message:** TokenSlim proves that compiler-inspired AST slicing and pre-prompt deprecation screening can make autonomous coding agents significantly more token-efficient and reliable.

### On-Slide Text / Bullet Points:
- **What Was Accomplished:**
  - Verified **31.4% context token reduction** (saving 3,584 prompt tokens across 12 tasks).
  - Built pre-prompt stale API screening to eliminate deprecated syntax hallucinations.
  - Implemented granular token accounting with audited reference pricing.
  - Developed a zero-build single-page app with SSE reconnection and replay mode.
  - Verified across **106 passing automated tests**.
- **Future Roadmap:**
  - **Multi-Language AST Support:** Integrate Tree-sitter for TypeScript, Go, and Rust repositories.
  - **Live Bifrost Cascades:** Dynamic fallback routing from primary to secondary models based on token limits.
  - **CI/CD Integration:** Autonomous GitHub App to open verified pull requests with attached test logs.
- **Project Links:**
  - **Live Web App:** `https://tokenslim-geekroom.onrender.com`
  - **GitHub Repo:** `https://github.com/Rakshit414/TokenSlim_GeekRoom` (Commit: `bba259ac597aee2143e14c1595a5d965eeb8325e`)

### Speaker Notes (Student Tone):
> "To wrap up: TokenSlim demonstrates that you don't need complex vector databases or massive context windows to build a reliable coding agent.
> 
> By taking a compiler-inspired approach with native AST slicing, we cut context tokens by 31.4% while preserving complete repair capability. And by screening for stale syntax upfront, we prevent agents from breaking builds with deprecated APIs.
> 
> In the next phase, we want to expand beyond Python by using Tree-sitter for TypeScript, Go, and Rust, configure live Bifrost model cascades, and package TokenSlim into a GitHub App that automatically opens verified PRs.
> 
> The application is live right now at `tokenslim-geekroom.onrender.com`, and the full codebase with all 106 tests is available on GitHub. Thank you so much for your time, and I'd be glad to answer any questions!"

### Technical Deep Dive & Q&A Backup:
- **Tree-sitter Roadmap:** Tree-sitter provides C-based, language-agnostic incremental parsing. Replacing `ast.parse` with Tree-sitter grammar bindings allows TokenSlim's slice extraction algorithm to operate identically across any programming language.
- **Reproducibility:** Anyone can clone the repository, run `pytest`, and re-run the deterministic benchmark suite locally to reproduce the exact 11,431 vs 7,847 token numbers.
