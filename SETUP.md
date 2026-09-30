# Setup & Initial Rollout

Initial setup instructions for the Organization: the environment, the
step-by-step rollout (with the exact PowerShell commands and what each step
does), the configuration knobs, and how to wire a real LLM backend.

> **Working directory** for every command below: `D:\LLM\LLM_Organization`
> (the folder containing `README.md`, `runtime/`, `tests/`, ...).

---

## Prerequisites

- **Python 3.10+** on your PATH (the code uses `dataclasses`, `json`,
  `pathlib`, `abc`). Check with:

  ```powershell
  python --version
  ```

  You should see `Python 3.10.x` or newer. If it says `Python 3.9` or lower,
  install a newer Python from python.org (tick "Add to PATH" during install).

- **Git** on your PATH (for Step 1). Check with:

  ```powershell
  git --version
  ```

---

## Step 0 — Move to the project folder

```powershell
cd D:\LLM\LLM_Organization
```

**What happens:** your PowerShell prompt is now rooted at the project folder.
All subsequent relative paths (`.venv`, `tests/`, `requirements.txt`) resolve
here.

**Verify you're in the right place:**

```powershell
Get-ChildItem
```

You should see `README.md`, `SETUP.md`, `EXECUTION_CHECKLIST.md`,
`Organization_Outline.md`, `MISSION.md`, `requirements.txt`, `.env.example`,
`run_session.py`, `run_org.bat`, and the `runtime/`, `org/`, `roles/`,
`tests/`, `departments/` directories (plus the state directories `pods/`,
`state/`, `history/`, `archives/`, `reports/` and the `.gitignore`).

---

## Step 1 — Register the repo (`git init`)

```powershell
git init
```

**What happens:** Git creates a `.git/` directory and turns this folder into a
repository. Nothing about the code changes — it only starts tracking versions.

**Verify:**

```powershell
git status
```

You should see a list of untracked files (the `*.py`, `*.md`, `.gitkeep`
files). The generated-state directories (`history/`, `archives/`, etc.) are
git-ignored and will not be listed.

---

## Step 2 — Create and activate the virtual environment

```powershell
python -m venv .venv
```

**What happens:** Python creates a self-contained `.venv/` folder with its own
Python interpreter and package set, isolated from your system Python.

```powershell
.venv\Scripts\Activate.ps1
```

**What happens:** activates the venv. Your prompt prefix changes to
`( .venv )`. From here, `python` and `pip` refer to the venv's, not the
system's.

**Verify:**

```powershell
python --version
```

It should report the venv's Python.

---

## Step 3 — Install the dependencies

```powershell
pip install -r requirements.txt
```

**What happens:** installs `python-dotenv`, `pytest`, and `httpx` into the
venv. The core code is stdlib-only, so the tests run with just the first
two; `httpx` is only needed by the real backend (`runtime/llm_api.py`,
`LLM_BACKEND=api`).

**Verify:**

```powershell
pip list
```

You should see `python-dotenv`, `pytest`, and `httpx` in the list.

---

## Step 4 — Run the test suite

```powershell
pytest -v
```

**What happens:** pytest discovers every `tests/test_*.py` and runs each test
function, printing one line per test. The tests are **offline** (deterministic
`StubBackend` + temp directories) — no live model, no network.

**What to look for:** **all passed, 0 failed** (the count may vary; what
matters is no failures).

**If a test fails:** read the failing assertion (pytest prints the diff), then
open the relevant module under `runtime/` or `org/`. Because the tests are
deterministic, a failure points at a specific logic branch. Fix the code and
re-run `pytest -v`.

---

## Step 5 — (Optional) Run a single module's tests

To exercise one area, run just that module's tests:

```powershell
pytest tests/test_pods.py -v
```

```powershell
pytest tests/test_org.py -v
```

**What happens:** runs only that module's tests. Useful when iterating on one
area.

---

## Configuration

Copy `.env.example` to `.env` and adjust. The code has safe defaults for every
knob; the important ones:

| Var | Default | Meaning |
|---|---|---|
| `CONFIDENCE_THRESHOLD` | `0.8` | Leader's "understands the task" threshold (0-1) |
| `QUESTION_BUDGET_ROUNDS` | `5` | Max clarifying-question rounds before marking assumptions |
| `MISSION_REASK_BUDGET` | `3` | Max re-asks on a rejected mission draft |
| `POD_MIN_ROLES` / `POD_MAX_ROLES` | `2` / `6` | Pod size bounds |
| `POD_MAX_ROUNDS` | `5` | Max deliberation rounds per pod |
| `DIRECT_IC_CAP` | `3` | Max ICs a non-manager may have as direct reports |
| `CONTEXT_BUDGET_TOKENS` | `4000` | Bounded-assembly token budget |
| `ROLE_MEMORY_MAX_ENTRIES` | `20` | Max entries in a role's short-term memory |
| `HISTORY_WINDOW_SESSIONS` | `50` | Rolling window before archiving |
| `ARCHIVE_CAP_MB` | `1024` | Archive size cap (oldest deleted beyond this) |
| `LLM_BACKEND` | `stub` | `stub` (offline) or `api` (real) |
| `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | (empty) | Credentials for a real backend (`LLM_BACKEND=api`) |
| `LLM_STRUCTURED` | `tools` | api backend's structured-output mode: `tools` (tool calls) or `json` (`json_object`) |

---

## The LLM backend

The Organization is a company of LLM agents, but the outline does not pin a
model. The code defines a clean `LLMBackend` interface (`runtime/llm.py`):

```python
class LLMBackend(ABC):
    def invoke(self, role, context: str,
               reasoning: Reasoning = Reasoning.LOW) -> Dict[str, Any]:
        ...
```

`reasoning` selects the model's thinking level (`Reasoning` enum:
`LOW` / `MEDIUM` / `HIGH`); the complexity router (`runtime/complexity.py`)
sets it per task — complex tasks run with thinking on, simple ones off.

Two implementations ship in the repo:

- **`StubBackend`** (default, `LLM_BACKEND=stub`) — deterministic, scripted
  per role. Every loop/budget/schema check runs offline. This is what the
  tests use. No live model required.
- **`OpenAIBackend`** (`runtime/llm_api.py`, `LLM_BACKEND=api`) — a real
  backend that calls any OpenAI-compatible chat endpoint (KoboldCpp,
  llama.cpp server, vLLM, LM Studio, ...). `make_backend()` in the same
  module selects the backend from the environment: `LLM_BACKEND=api` builds
  `OpenAIBackend` from `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY`; anything
  else falls back to `StubBackend`. `httpx` is imported lazily, so the stub
  path and the offline tests need no network dependency. Structured output
  uses **tool calls** by default: the role's output schema is offered as a
  single forced tool (`submit_output`), so the envelope arrives as the
  tool's JSON arguments — the path that needs the server's tool-call support
  (KoboldCpp's `--jinja --jinjatools`, which `run_org.bat` passes). Set
  `LLM_STRUCTURED=json` for the legacy `response_format: json_object`
  request on servers without tool support.

Every backend — stub or real — must return a dict containing the **shared
output envelope**:

  ```python
  {
      "summary": "...",            # one-line extractive digest
      "findings": [{"claim": "...", "evidence": "..."}],
      "recommendation": "...",
      "confidence": 0.9,           # 0-1
      # role-specific extensions (questions, assumptions, mission_draft,
      # decomposition, agenda, decision, rationale, open_items, verdict, ...)
  }
  ```

  The session runtime validates the envelope and retries (bounded) on a
  malformed output — so a flaky backend degrades visibly, never silently.

### How the `Session` uses the backend

`Session` never calls your backend raw; it wraps it in layers
(`runtime/session.py`):

1. **`TimeoutBackend`** — a per-invoke timeout (`timeout_seconds` config,
   default `60`); a slow call raises a visible `LLMTimeoutError` instead of
   hanging.
2. **`RoutingBackend` + `ThinkingBudget`** — routes every invoke by task
   complexity (complex -> thinking on, simple -> off) and bounds the number
   of high-thinking invokes per session (`thinking_budget` config, default
   `10`).
3. **`MemoryBackend`** — folds each role's isolated short-term memory into
   its own prompt before the invoke and appends the role's output after it.

### Wiring a real backend

The backend is already wired: `run_session.py` builds the `Session` with
`make_backend()`, which reads the environment. `.env.example` ships with the
localhost setup pre-filled (matching `run_org.bat`: local KoboldCpp hosting
Qwen3.8-27B on port 5001), so to run against the local model just copy
`.env.example` to `.env`:

```ini
LLM_BACKEND=api
LLM_MODEL=Qwen3.8-27B-UD-Q4_K_M.gguf
LLM_BASE_URL=http://localhost:5001/v1   # endpoint root (no /chat/completions)
LLM_API_KEY=not-needed
```

Then run `python run_session.py` (Step 7). `run_org.bat` is a worked example
that also starts the local KoboldCpp server first (with the `--jinja
--jinjatools` tool-call flags). Set `LLM_BACKEND=stub` for offline runs.

### The permission layer (self-mod)

The dispatch loop already lets active roles self-edit their code, and every
write goes through `runtime/permissions.write_file(role, path, content)`
(via `permissions.apply_code_edits`, which records refusals visibly). That
module enforces three invariants, each covered by `tests/test_permissions.py`:

- **Sandbox** — a path that resolves outside the workspace (e.g. `..` or a
  symlink escape) is refused, so an agent cannot break out of
  `D:\LLM\LLM_Organization`.
- **Mission lock** — `MISSION.md` is writable only by the `leader`.
- **Meta-rule lock** — the permission module itself (plus `org/tiers.py` and
  `roles/base.py`, which encode the org invariants and the role contract) is
  read-only for *every* role, including the leader. An agent can never edit the
  rules that bound it.

Everything else follows the normal scoping (department policy, team dirs).

---

## Step 6 — First commit

```powershell
git add -A
git commit -m "Initial commit: Organization codebase (offline tests)"
```

**What happens:** stages every tracked file (the generated-state directories
stay ignored) and records the first commit. The repo now has a baseline to
diff against.

**Verify:**

```powershell
git log --oneline
```

You should see your initial commit.

---

## Step 7 — Run the pipeline (smoke run)

Two entry points ship in the repo.

### Offline smoke run (no model needed)

With the default `LLM_BACKEND=stub`, run the full pipeline unattended
(auto-answer / auto-approve callbacks):

```powershell
python run_session.py
```

**What happens:** `run_session.py` loads the backend from the environment
(`make_backend()`), builds the `Session`, and runs one bounded end-to-end
cycle (intake -> mission -> org bootstrap -> dispatch -> synthesis ->
evaluation) against the deterministic `StubBackend`. It prints the final
status, phases, cycles, verdict, and evaluation.

**What to look for:** a clean completion (or a visible verdict/escalation)
with no exceptions.

### Live run (real model)

`run_org.bat` is a worked one-shot: it starts a local KoboldCpp server
(model + GPU flags), waits until the endpoint answers, then runs
`python run_session.py`. Adjust the paths at the top of the file for your
setup (model path, port, directories):

```powershell
run_org.bat
```

**What happens:** the same pipeline runs against the live model instead of
the stub. The KoboldCpp server window stays open afterwards.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `python` not recognized | Python isn't on PATH. Reinstall with "Add to PATH", or use the full path. |
| `Activate.ps1` can't be loaded | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (elevated), then re-activate. |
| `pip install` fails on a package | Usually a network/proxy issue. Check connectivity; retry. |
| `pytest` not found | The venv isn't active (no `( .venv )` prefix). Re-run `.venv\Scripts\Activate.ps1`. |
| A test fails | Read the assertion diff; the failure is deterministic and points at one branch in `runtime/` or `org/`. Fix and re-run. |

---

## What "done" looks like

When you're finished, you should have:

1. A registered Git repo (`.git/` present).
2. A venv with `python-dotenv` + `pytest` + `httpx` installed.
3. `pytest -v` reporting **all tests passed, 0 failed**.
4. An initial commit in `git log`.
5. (Optional) A live-model smoke run: `LLM_BACKEND=api` set in `.env` and
   `python run_session.py` (or `run_org.bat`) completing against the real
   model.

---

## Notes

- The repo layout uses drive-letter Windows paths in the docs, but the code
  itself uses `pathlib`/relative `os.path` so it is portable.
- Generated state (`history/`, `archives/`, `state/role_memory/`,
  `pods/transcripts/`, `pods/artifacts/`, `reports/offloading/`,
  `reports/evaluation/`) is git-ignored; the `.gitkeep` markers keep the
  directories in the repo.