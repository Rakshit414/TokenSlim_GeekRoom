# TokenSlim — Demo Guide & Walkthrough

This guide provides step-by-step instructions for demonstrating TokenSlim across both available demonstration modes: **Deterministic Replay Demo** (zero external dependencies) and **Live Agent Execution** (with Bifrost and Tavily configured).

---

## 1. Demo Mode Selection

| Feature | Replay Demo (Recommended for Evaluation) | Live Demo Mode |
| :--- | :--- | :--- |
| **Prerequisites** | None (Works 100% offline) | Bifrost gateway daemon + Tavily API key |
| **Model Generation** | Pre-recorded deterministic telemetry trace | Live LLM completion via Bifrost |
| **Documentation Search**| Recorded Tavily migration evidence | Real-time Tavily search queries |
| **Simulation Labelling**| Explicitly labeled `[REPLAY ACTIVE]` | Real provider usage or honest `[UNVERIFIED]` status |
| **Ideal For** | Hackathon judging, local testing, offline evaluation | Production deployments with live API credentials |

---

## 2. Walkthrough: Deterministic Replay Demo (Zero Setup)

The Replay Demo walks through an end-to-end Pydantic v1 $\to$ v2 migration task (`user.dict()` deprecated in favor of `user.model_dump()`), demonstrating selective AST context extraction, stale syntax detection, unified diff generation, and test verification.

### Step 1: Start the Web Application
Open PowerShell in the project directory:
```powershell
.\.venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```
Navigate your browser to: `http://localhost:8000`

### Step 2: Observe the Gateway Status Indicators
- In the sidebar footer, observe the honest status pills:
  - If Bifrost is unconfigured: displays `OFFLINE / UNSET` in coral.
  - If Tavily is unconfigured: displays `OFFLINE / HEURISTIC` in coral.
  - No false "Connected" claims are made when credentials are not active.

### Step 3: Configure the Task
1. Target Directory: `benchmark/tasks/task_pydantic_v2`
2. Configuration Mode: `LeanCode + Tavily (Complete TokenSlim - Recommended)`
3. Ensure **"Replay Pre-recorded Trace"** is checked.
4. Click **"Execute Autonomous Agent"**.

### Step 4: Follow the Live Telemetry Stream
The terminal trace streams sequential events in real-time:
```text
[AGENT]  Starting task execution with config: leancode_tavily (Replay: true)...
[SYSTEM] Run created: run_20261114_xxxxxx. Streaming telemetry...
[STATE]  Run initialized in 'leancode_tavily' mode.
[AGENT]  Initiating TokenSlim autonomous coding loop for task: Migrate deprecated user.dict()...
[TEST]   Baseline test execution: 1 test failed (AttributeError: 'UserProfile' object has no attribute 'dict').
[AGENT]  RepositoryScanner mapped 2 files, 1 class, 2 functions, 23 total lines.
[AGENT]  Tavily Stale-Answer Detector flagged 1 candidate API claim: '.dict()' in Pydantic.
[CONTEXT] Retrieved 1 minimal AST slice from models.py (Lines 10-18). Estimated tokens: 145.
[BIFROST] Generated search/replace patch via Bifrost gateway (mock-adapter). Spent 237 tokens.
[DIFF]   PatchEngine applied 1 replacement block to models.py cleanly.
[TEST]   Targeted test execution: 1 passed in 0.18s.
[AGENT]  Tests passed! 1 passed in 0.18s. Early stopping triggered.
[METRICS] Final metrics: 237 tokens spent, 1 iteration(s).
[DIFF]   Final unified diff generated.
[AGENT]  Autonomous loop finished with status: COMPLETED_VERIFIED. Task successfully solved and verified by tests.
```

### Step 5: Inspect the Stale Evidence Card
- Navigate to the **Tavily Stale-Answer Evidence Inspector** panel.
- Inspect the generated card:
  - **Status:** `STALE`
  - **Technology:** `pydantic v2`
  - **Claim:** `user.dict()`
  - **Evidence:** `Pydantic v2 deprecated .dict() in favor of .model_dump().`
  - **Recommended Correction:** `Replace .dict() with .model_dump()`
  - **Badge:** `[OFFLINE SIMULATION]` (honestly disclosed)

### Step 6: Review the Unified Diff & Verification
- Navigate to the **Diff & Verification** panel.
- Inspect the generated diff:
```diff
--- models.py
+++ models.py
@@ -12,3 +12,3 @@
-    return user.dict()
+    return user.model_dump()
```
- Verification badge: `Tests Passed (100%)`.

### Step 7: Inspect Benchmark Comparison Dashboard
- Click **Benchmark Dashboard** in the navigation menu.
- Review the 3-configuration benchmark table across 12 tasks:
  - **Naive Baseline (Broad Context):** 12,633 simulated tokens spent (11,433 context tokens).
  - **LeanCode (Selective AST):** 9,047 simulated tokens spent (7,847 context tokens) $\to$ **31.4% context reduction**.
  - **LeanCode + Tavily (Complete TokenSlim):** 9,047 simulated tokens spent, 6 stale syntax detections flagged, 6 Tavily searches executed.

---

## 3. Walkthrough: Live Demo Mode (With Credentials)

When running in an environment with real credentials:

### Step 1: Configure `.env`
Create or update `.env` in the repository root:
```env
BIFROST_BASE_URL=http://localhost:8080/v1
TAVILY_API_KEY=tvly-your-live-tavily-key
MODEL_NAME=gpt-4o-mini
PROBE_BIFROST_LIVE=1
PROBE_TAVILY_LIVE=1
```

### Step 2: Start the Bifrost Daemon
Ensure your Bifrost daemon or Docker container is active:
```bash
docker run -p 8080:8080 ...
```

### Step 3: Run the Live Task
1. Uncheck **"Replay Pre-recorded Trace"** in the UI.
2. Select target repository and enter task directive.
3. Click **"Execute Autonomous Agent"**.
4. The system will make live network calls through the Bifrost proxy and Tavily search API.
5. Live provider tokens, latency in seconds, and calculated costs will appear in the top metric pills and SQLite trace ledger.
