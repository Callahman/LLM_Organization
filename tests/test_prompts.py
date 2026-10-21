"""the pipeline's **prompts live in the ``prompts/`` location** with
**usage comments**.

 extracted every static prompt string the pipeline sends to the LLM
into a single ``prompts`` module (a pure move — the text is unchanged, so
behavior is preserved). This file verifies:

- the ``prompts`` module exists and exports the pipeline's prompt constants
  (the intake / mission / bootstrap / head / manager / IC / policy / pod
  prompts, and the prompt *parts* the phase modules compose);
- each prompt constant is a non-empty string;
- the runtime modules import + reference the prompts (the prompts are actually
  used, not just stored);
- the ``prompts`` module source carries **usage comments** (a comment above
  each prompt/part indicating how/where it is used, for auditing).

Offline (no LLM).
"""

from __future__ import annotations

import inspect
import os
import re

import prompts


# The prompt constants the pipeline's prompts live under (a representative
# subset — the main phase prompts + the prompt parts the phase modules compose).
_EXPECTED_PROMPT_NAMES = [
    # Phase 1 (intake) — the clarifying-questions rules.
    "INTAKE_RULES",
    # Phase 2 (mission) — the mission-codification + department-caps prompts.
    "MISSION_INSTRUCTION",
    "MISSION_DEPARTMENT_CAPS",
    # Phase 3 (org bootstrap) — the department-head proposal + retry prompts.
    "BOOTSTRAP_INSTRUCTION",
    "BOOTSTRAP_RETRY",
    # Phase 4 (plan) — the leader's mission-decomposition context parts.
    "LEADER_CTX_DIGEST",
    "LEADER_CTX_INSTRUCTION",
    "LEADER_CTX_NO_INVENT",
    # Phase 4 (plan) — the head's team-decomposition context parts.
    "HEAD_CTX_PREFIX",
    "HEAD_CTX_OBJ",
    "HEAD_CTX_DIGEST",
    "HEAD_CTX_INSTRUCTION",
    # Phase 4 (head) — the policy context parts.
    "POLICY_CTX_PREFIX",
    "POLICY_CTX_OBJ",
    "POLICY_CTX_DIRECTIVE",
    "POLICY_CTX_CLAR_PREFIX",
    "POLICY_CTX_EXISTING",
    "POLICY_CTX_INSTRUCTION",
    # Phase 4 (manager) — the decomposition context parts.
    "MANAGER_CTX_PREFIX",
    "MANAGER_CTX_OBJ",
    "MANAGER_CTX_CLAR_PREFIX",
    "MANAGER_CTX_DIGEST",
    "MANAGER_CTX_POLICY",
    "MANAGER_CTX_INSTRUCTION",
    # Phase 6 (IC) — the work context parts.
    "IC_CTX_PREFIX",
    "IC_CTX_WORK_DIR",
    "IC_CTX_WRITE_ALL",
    "IC_CTX_DIGEST",
    "IC_CTX_POLICY",
    "IC_CTX_TASK",
    "IC_CTX_CLAR_PREFIX",
    "IC_CTX_INSTRUCTION_PREFIX",
    "IC_CTX_INSTRUCTION_MID",
    "IC_CTX_INSTRUCTION_SUFFIX",
    "IC_CTX_PATH_RULES_CONCRETE_PREFIX",
    "IC_CTX_PATH_RULES_CONCRETE_MID",
    "IC_CTX_PATH_RULES_CONCRETE_SUFFIX",
    "IC_CTX_PATH_RULES_CONCRETE_TAIL",
    "IC_CTX_PATH_RULES_CONCRETE_END",
    "IC_CTX_PATH_RULES_BARE",
    # Phase 6 (IC) — the retry nudge + the self-edit correction parts.
    "IC_RETRY_NUDGE",
    "SELF_EDIT_CORRECTION_PREFIX",
    "SELF_EDIT_CORRECTION_MID",
    "SELF_EDIT_CORRECTION_SUFFIX",
    # Phase 4 (automation) — the script-authoring context parts.
    "AUTOMATION_CTX_PREFIX",
    "AUTOMATION_CTX_MID",
    "AUTOMATION_CTX_SUFFIX",
    # The pod upward-report + the pod context parts.
    "POD_UPWARD_REPORT_PREFIX",
    "POD_UPWARD_REPORT_MID",
    "POD_UPWARD_REPORT_SUFFIX",
    "POD_CTX_HEADER_PREFIX",
    "POD_CTX_HEADER_MID",
    "POD_CTX_HEADER_DASH",
    "POD_CTX_AGENDA_LABEL",
    "POD_CTX_ARTIFACTS_LABEL",
    "POD_CTX_PRIOR_LABEL",
    # Phase 7 (evaluate) + Phase 8 (decide) + the devil's advocate prompt.
    "EVALUATE_INSTRUCTION",
    "DECIDE_INSTRUCTION",
    "DEVILS_ADVOCATE_INSTRUCTION",
]


# --- The prompts live in the prompts/ location --------------------------------

def test_prompts_module_exists():
    # The prompts module is importable (it lives in the prompts/ location).
    assert hasattr(prompts, "__file__")
    # It is a real file on disk (not a namespace-only package).
    assert os.path.exists(prompts.__file__)


def test_prompts_module_exports_expected_constants():
    # Every expected prompt constant is exported by the prompts module.
    missing = [name for name in _EXPECTED_PROMPT_NAMES
               if not hasattr(prompts, name)]
    assert missing == [], f"prompts module is missing: {missing}"


def test_prompt_constants_are_nonempty_strings():
    # Each prompt constant is a non-empty string (a real prompt, not a stub).
    for name in _EXPECTED_PROMPT_NAMES:
        value = getattr(prompts, name)
        assert isinstance(value, str), f"{name} is not a string"
        assert value.strip(), f"{name} is empty"


# --- The runtime modules use the prompts --------------------------------------

def test_runtime_modules_use_prompts():
    # The runtime modules import + reference the prompts (the prompts are
    # actually used, not just stored in the prompts/ location). The imported
    # names are present in each module's namespace.
    import runtime.intake as intake_mod
    import runtime.mission as mission_mod
    import runtime.org as org_mod
    import runtime.dispatch_common as dispatch_mod
    import runtime.pods as pods_mod
    import runtime.session as session_mod

    # Phase 1 (intake) uses INTAKE_RULES.
    assert hasattr(intake_mod, "INTAKE_RULES")
    # Phase 2 (mission) uses the mission-codification + department-caps
    # prompts.
    for name in ("MISSION_INSTRUCTION", "MISSION_DEPARTMENT_CAPS"):
        assert hasattr(mission_mod, name), f"mission does not import {name}"
    # Phase 3 (org bootstrap) uses the bootstrap prompts.
    for name in ("BOOTSTRAP_INSTRUCTION", "BOOTSTRAP_RETRY"):
        assert hasattr(org_mod, name), f"org does not import {name}"
    # Phase 4/6 (the dispatch) uses the head / manager / IC / policy / pod
    # prompt parts.
    for name in ("POLICY_CTX_PREFIX", "MANAGER_CTX_PREFIX", "IC_CTX_PREFIX",
                 "IC_RETRY_NUDGE", "SELF_EDIT_CORRECTION_PREFIX",
                 "AUTOMATION_CTX_PREFIX", "POD_UPWARD_REPORT_PREFIX",
                 "LEADER_CTX_DIGEST", "HEAD_CTX_PREFIX"):
        assert hasattr(dispatch_mod, name), f"dispatch does not import {name}"
    # The pods module uses the pod context parts.
    for name in ("POD_CTX_HEADER_PREFIX", "POD_CTX_AGENDA_LABEL",
                 "POD_CTX_ARTIFACTS_LABEL", "POD_CTX_PRIOR_LABEL"):
        assert hasattr(pods_mod, name), f"pods does not import {name}"
    # Phase 7/8 (evaluate / decide) + the devil's advocate prompt.
    for name in ("EVALUATE_INSTRUCTION", "DECIDE_INSTRUCTION",
                 "DEVILS_ADVOCATE_INSTRUCTION"):
        assert hasattr(session_mod, name), f"session does not import {name}"


def test_intake_context_uses_intake_rules():
    # The intake context actually embeds INTAKE_RULES (the prompt is used in the
    # composed context, not just imported).
    from runtime.intake import _assemble_context
    ctx = _assemble_context("build a thing")
    assert prompts.INTAKE_RULES in ctx


# --- The prompts carry usage comments -----------------------------------------

def test_prompts_module_has_usage_comments():
    # The prompts module source carries usage comments — a comment above each
    # prompt/part indicating how/where it is used (for auditing). The source
    # references the phase / role / pod each prompt is used by.
    source = inspect.getsource(prompts)
    # The usage comments reference the phases the prompts are used by.
    for marker in ("Phase 1", "Phase 2", "Phase 3", "Phase 4", "Phase 6",
                   "pod"):
        assert marker in source, f"no usage comment referencing {marker!r}"
    # There are a substantial number of comment lines (one per prompt/part).
    comment_lines = [line for line in source.splitlines()
                     if line.strip().startswith("#")]
    assert len(comment_lines) >= 20


def test_usage_comment_density():
    # The prompts module carries a usage comment for each *group* of prompt
    # parts (a comment above the parts a context builder composes) — the
    # comment density is at least half the number of top-level prompt
    # constants (every prompt/part is covered by a nearby usage comment).
    source = inspect.getsource(prompts)
    lines = source.splitlines()
    # The top-level assignment lines (a name = "..." or a name = (...)).
    assign_re = re.compile(r"^[A-Z][A-Z0-9_]*\s*=")
    n_constants = sum(1 for line in lines if assign_re.match(line))
    n_comments = sum(1 for line in lines if line.strip().startswith("#"))
    assert n_constants > 0
    # At least half the constants are covered by a usage comment (the rest are
    # grouped under the same comment as a preceding part).
    assert n_comments >= n_constants // 2, (
        f"only {n_comments} usage comments for {n_constants} prompt constants"
    )
