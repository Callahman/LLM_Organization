# Rollout Steps

The steps to finish the rollout **on your machine** (Windows / PowerShell).
The code and tests are already authored; these steps register the repo, set up
the environment, and run the test suite to verify everything.

> **Working directory** for every command below: `D:\LLM\LLM_Organization`
> (the folder containing `EXECUTION_CHECKLIST.md`, `runtime/`, `tests/`, ...).

---

## Prerequisites

- **Python 3.10+** on your PATH. Check with:

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

You should see `EXECUTION_CHECKLIST.md`, `README.md`, `SETUP.md`, `runtime/`,
`org/`, `roles/`, `tests/`, `departments/`, `requirements.txt`, `.env.example`.

---

## Step 1 — Register the repo (`git init`)

```powershell
git init
```

**What happens:** Git creates a `.git/` directory and turns this folder into a
repository. This is the "register the repo" step (yours to do, per your note).
Nothing about the code changes — it only starts tracking versions.

**Verify:**

```powershell
git status
```

You should see a list of untracked files (the `*.py`, `*.md`, `.gitkeep` files).
The generated-state directories (`history/`, `archives/`, etc.) are git-ignored
and will not be listed.

---

## Step 2 — Create and activate the virtual environment

```powershell
python -m venv .venv
```

**What happens:** Python creates a self-contained `.venv/` folder with its own
Python interpreter and package set, isolated from your system Python. This is
the environment the code and tests will run in.

```powershell
.venv\Scripts\Activate.ps1
```

**What happens:** activates the venv. Your prompt prefix changes to
`( .venv )` — e.g. `( .venv ) PS D:\LLM\LLM_Organization>`. From here, `python`
and `pip` refer to the venv's, not the system's.

> **If activation is blocked** (a common PowerShell policy error: *"cannot be
> loaded because running scripts is disabled"*), run this **once** in an
> elevated PowerShell, then re-activate:
>
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

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

**What happens:** installs `python-dotenv` and `pytest` into the venv. The
core code is stdlib-only, so this is all that's needed to run the tests.

**Verify:**

```powershell
pip list
```

You should see `python-dotenv` and `pytest` in the list.

---

## Step 4 — Run the test suite

```powershell
pytest -v
```

**What happens:** pytest discovers every `tests/test_*.py` and runs each test
function, printing one line per test. The tests are **offline** (deterministic
`StubBackend` + temp directories) — no live model, no network.

**What to look for:**

- A line like `==================== 20 passed in 0.XXs ====================`
  (the count may differ; what matters is **all passed, 0 failed**).
- Each test maps to a Definition of Done in `EXECUTION_CHECKLIST.md`:
  - `test_tiers.py` → Epic 0 (read-scope / communication / pod invariants)
  - `test_intake.py` → Epic 1 (clarifying Q&A loop)
  - `test_mission.py` → Epic 2 (permission flow, out-of-flow write refusal)
  - `test_org.py` → Epic 3 (bootstrap, veto, offloading, 3-IC cap, IC can't initiate)
  - `test_dispatch.py` → Epic 4 (top-down dispatch, work propagates up)
  - `test_pods.py` → Epic 5 (the §2.8 worked example end-to-end)
  - `test_context.py` → Epic 6 (bounded assembly, truncation, cross-team memory)
  - `test_complexity.py` → Epic 7 (complexity routing, thinking budget, disagreement)
  - `test_session.py` → Epic 10 (the full Phase 1-6 pipeline, bounded loop, BAU)
  - `test_memory.py` → Step 3 (per-role isolated memory: isolation, decay, bound)
  - `test_pod_triggers.py` → Step 4 (pods A/B/C multi-trigger + 3-way carry-over)

**If a test fails:** read the failing assertion (pytest prints the diff), then
open the relevant module under `runtime/` or `org/`. Because the tests are
deterministic, a failure points at a specific logic branch. Fix the code and
re-run `pytest -v`.

---

## Step 5 — (Optional) Run a single end-to-end smoke test

To exercise one full pipeline path interactively, run just the pod worked
example:

```powershell
pytest tests/test_pods.py -v
```

Or the org bootstrap + resourcing path:

```powershell
pytest tests/test_org.py -v
```

**What happens:** runs only that module's tests. Useful when iterating on one
area.

---

## Step 6 — (Optional) Wire a real LLM backend

The default backend is the offline `StubBackend`. To run against a real model,
implement `LLMBackend.invoke` (see `SETUP.md` for a full example) and select it
where the `Session` is constructed:

```python
# example (see SETUP.md "Wiring a real backend")
from runtime.session import Session
from roles.leader import make_leader
from runtime.llm_api import ApiBackend   # your implementation

backend = ApiBackend(model="...", base_url="...", api_key="...")
session = Session(backend=backend, leader=make_leader(),
                  config={"confidence_threshold": 0.8, "question_budget": 5})
```

**What happens:** the same pipeline runs, but each role's structured output
comes from your model instead of the scripted stub. The session runtime still
validates the output envelope and retries (bounded) on a malformed response.

> This is a later task — the offline tests do not require it.

---

## Step 7 — First commit

```powershell
git add -A
git commit -m "Initial commit: Organization codebase (Epic 0-9, offline tests)"
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
2. A venv with `python-dotenv` + `pytest` installed.
3. `pytest -v` reporting **all tests passed, 0 failed**.
4. An initial commit in `git log`.
5. (Optional) A real LLM backend wired and a smoke run against it.

Once `pytest -v` is green, tick the Definitions of Done in
`EXECUTION_CHECKLIST.md` (they are intentionally left `- [ ]` until the tests
have actually been run and passed).