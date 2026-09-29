# Setup

Deployment guide for the Organization, and how to wire a real LLM backend.

> The full step-by-step rollout (with the exact PowerShell commands and what
> each step does) is in `ROLLOUT_STEPS.md`. This file is the reference for the
> environment and the LLM backend.

## Environment

- **Python 3.10+** (the code uses `dataclasses`, `json`, `pathlib`, `abc`).
- A virtual environment (`.venv`).
- Dependencies: `requirements.txt` (`python-dotenv`, `pytest`).

## Configuration

Copy `.env.example` to `.env` and adjust. The code has safe defaults for every
knob; the important ones:

| Var | Default | Meaning |
|---|---|---|
| `CONFIDENCE_THRESHOLD` | `0.8` | Leader's "understands the task" threshold (0–1) |
| `QUESTION_BUDGET_ROUNDS` | `5` | Max clarifying-question rounds before marking assumptions |
| `MISSION_REASK_BUDGET` | `3` | Max re-asks on a rejected mission draft |
| `POD_MIN_ROLES` / `POD_MAX_ROLES` | `2` / `6` | Pod size bounds |
| `POD_MAX_ROUNDS` | `5` | Max deliberation rounds per pod |
| `DIRECT_IC_CAP` | `3` | Max ICs a non-manager may have as direct reports |
| `CONTEXT_BUDGET_TOKENS` | `4000` | Bounded-assembly token budget |
| `HISTORY_WINDOW_SESSIONS` | `50` | Rolling window before archiving |
| `ARCHIVE_CAP_MB` | `1024` | Archive size cap (oldest deleted beyond this) |
| `LLM_BACKEND` | `stub` | `stub` (offline) or `api` (real) |

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

## Running the tests

```powershell
pytest -v
```

The tests are offline (deterministic `StubBackend` + temp directories) and
require no live model. Each test targets a Definition of Done in
`EXECUTION_CHECKLIST.md`.

## Notes

- The repo layout uses drive-letter Windows paths in the docs, but the code
  itself uses `pathlib`/relative `os.path` so it is portable.
- Generated state (`history/`, `archives/`, `state/role_memory/`,
  `pods/transcripts/`, `pods/artifacts/`, `reports/offloading/`,
  `reports/evaluation/`) is git-ignored; the `.gitkeep` markers keep the
  directories in the repo.
