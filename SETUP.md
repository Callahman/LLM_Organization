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

You should see `README.md`, `SETUP.md`, `runtime/`, `org/`, `roles/`,
`tests/`, `departments/`, `requirements.txt`, `.env.example`.

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
| `HISTORY_WINDOW_SESSIONS` | `50` | Rolling window before archiving |
| `ARCHIVE_CAP_MB` | `1024` | Archive size cap (oldest deleted beyond this) |
| `LLM_BACKEND` | `stub` | `stub` (offline) or `api` (real) |

---

## The LLM backend

The Organization is a company of LLM agents, but the outline does not pin a
model. The code defines a clean `LLMBackend` interface (`runtime/llm.py`):

```python
class LLMBackend(ABC):
    def invoke(self, role, context: str) -> Dict[str, Any]:
        ...
```

Two implementations:

- **`StubBackend`** (default, `LLM_BACKEND=stub`) — deterministic, scripted
  per role. Every loop/budget/schema check runs offline. This is what the
  tests use. No live model required.
- **A real backend** (e.g. `LLM_BACKEND=api`) — you implement `invoke` to call
  your model, and return a dict containing the **shared output envelope**:

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

### Wiring a real backend (example)

```python
# runtime/llm_api.py  (add to the repo; a later task)
import json, httpx
from runtime.llm import LLMBackend

class ApiBackend(LLMBackend):
    def __init__(self, model, base_url, api_key):
        self.model, self.base_url, self.api_key = model, base_url, api_key
    def invoke(self, role, context):
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": role.mandate},
                    {"role": "user", "content": context},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        return json.loads(resp.json()["choices"][0]["message"]["content"])
```

Then select it where the `Session` is constructed:

```python
from runtime.session import Session
from roles.leader import make_leader

backend = ApiBackend(model="...", base_url="...", api_key="...")
session = Session(backend=backend, leader=make_leader(),
                  config={"confidence_threshold": 0.8, "question_budget": 5})
```

> This is a later task — the offline tests do not require it.

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

---

## Notes

- The repo layout uses drive-letter Windows paths in the docs, but the code
  itself uses `pathlib`/relative `os.path` so it is portable.
- Generated state (`history/`, `archives/`, `state/role_memory/`,
  `pods/transcripts/`, `pods/artifacts/`, `reports/offloading/`,
  `reports/evaluation/`) is git-ignored; the `.gitkeep` markers keep the
  directories in the repo.