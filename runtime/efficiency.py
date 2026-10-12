"""S22 — Efficiency trade-off in the Phase 3–6 loop.

The incentive: if the mission can be completed with **LESS headcount / compute
time**, that is **encouraged**. The key metric is **wall-clock uptime** (local
compute) — LLM invocations / token cost are secondary since the model is locally
hosted.

Two levers (this module owns the measurement; the levers live elsewhere):

1. **Dynamic headcount control** — the Leader/heads generate fewer roles as
   needed and can offload/fire/replace them dynamically (the firing cascade +
   the cascade size in the single HR approval request live in
   ``runtime/org.py::fire``).
2. **Automation over headcount** — for a recurring task, an IC **writes a Python
   script**, the script is created, the IC is **fired** if not needed for other
   work, and the recurring task is then done by **executing the script**
   (subprocess / tool call) instead of an IC each time (see
   ``runtime/dispatch.py::run_automation``).

This module provides the **measurement + scoring**:

- :func:`compute_m_satisfaction` — the mission satisfaction ``M_satisfaction``
  (0-1), generalized for **BOTH** terminal and recurring goals.
- :func:`efficiency_score` — the efficiency score
  ``E = M_satisfaction / (0.5·(T_total/T_ref) + 0.5·(C/C_ref))``.
- :class:`EfficiencyMeter` — instruments the Phase 3–6 loop **per iteration**,
  computes ``E`` with running-average refs over the last ``REF_WINDOW``
  iterations, and appends the per-iteration snapshot to
  ``history/efficiency_metrics.jsonl`` (auditable + the dashboard's Efficiency
  panel).
- :data:`EFFICIENCY_FLOOR` — the threshold (default ~0.4); when ``E`` is below
  the floor, the Leader must take a **visible** efficiency action.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# S22: the efficiency floor (default ~0.4). When E < EFFICIENCY_FLOOR, the
# Leader must take a visible efficiency action (reduce headcount / automate a
# recurring task / stop if the mission is satisfied).
EFFICIENCY_FLOOR = 0.4

# The number of prior iterations used for the running-average refs (T_ref/C_ref).
REF_WINDOW = 3

# Fixed 0.5/0.5 weights in the E denominator (time vs compute-uptime).
TIME_WEIGHT = 0.5
COMPUTE_WEIGHT = 0.5


# --- M_satisfaction ----------------------------------------------------------

def compute_m_satisfaction(
    mission: Optional[Dict[str, Any]],
    dispatch_results: Optional[List[Dict[str, Any]]],
    verdict: str,
) -> float:
    """S22: the mission satisfaction ``M_satisfaction`` (0-1), generalized for
    **BOTH** terminal and recurring goals.

    A pragmatic, deterministic estimate (no model needed):

    - The synthesis **verdict** sets the base (``complete`` -> 1.0,
      ``continue`` -> 0.5, ``escalate`` -> 0.2).
    - **Terminal goals**: scaled by the fraction of the mission's success
      criteria that have supporting dispatched work (``coverage``).
    - **Recurring goals**: the verdict already reflects the cycle-target
      attainment (a recurring goal is "met" when the synthesis says the cycle
      target is reached) — so the base already carries it.

    The result is clamped to ``[0, 1]``.
    """
    base = {"complete": 1.0, "continue": 0.5, "escalate": 0.2}.get(verdict, 0.2)
    criteria: List[Any] = []
    if isinstance(mission, dict):
        sc = mission.get("success_criteria", [])
        if isinstance(sc, list):
            criteria = sc
    if not criteria:
        # No explicit criteria — the verdict alone drives satisfaction.
        return max(0.0, min(1.0, base))
    done_units = sum(
        1 for d in (dispatch_results or [])
        if isinstance(d, dict) and (d.get("summary") or d.get("work_path"))
    )
    coverage = min(1.0, done_units / len(criteria))
    # Blend the base (the verdict, which carries recurring attainment) with the
    # terminal criteria progress (coverage).
    sat = 0.5 * base + 0.5 * coverage
    return max(0.0, min(1.0, sat))


# --- The efficiency score E --------------------------------------------------

def efficiency_score(
    m_satisfaction: float,
    t_total: float,
    c: float,
    t_ref: Optional[float],
    c_ref: Optional[float],
) -> float:
    """S22: the efficiency score ``E``.

    ``E = M_satisfaction / (0.5·(T_total/T_ref) + 0.5·(C/C_ref))``

    A **HIGHER** ``E`` is better (more mission satisfaction per unit of
    wall-clock time + compute-uptime). ``T_ref`` / ``C_ref`` are the running
    averages over the last ``REF_WINDOW`` prior iterations (fixed 0.5/0.5
    weights). When there are no prior refs (the first iteration), a neutral
    baseline (ratio 1.0) is used, so ``E = M_satisfaction``. Division by zero is
    guarded (a zero reference yields a ratio of 1.0).
    """
    if t_ref is None or c_ref is None:
        # First iteration: no prior refs — a neutral baseline (denominator 1.0).
        denom = TIME_WEIGHT + COMPUTE_WEIGHT
    else:
        t_ratio = (t_total / t_ref) if t_ref > 0 else 1.0
        c_ratio = (c / c_ref) if c_ref > 0 else 1.0
        denom = TIME_WEIGHT * t_ratio + COMPUTE_WEIGHT * c_ratio
    if denom <= 0:
        return 0.0
    return m_satisfaction / denom


# --- The per-iteration meter -------------------------------------------------

class EfficiencyMeter:
    """S22: instruments the Phase 3–6 loop **per iteration** and computes the
    efficiency score ``E``.

    Per iteration it records:

    - ``T_total`` — total loop time (the sum of the recorded phase times),
    - ``T_p`` — per-phase time (``{phase: seconds}``),
    - ``T_dept`` — per active department time,
    - ``T_role`` — per role time,
    - ``H_peak`` — peak concurrent headcount,
    - ``C`` — total role-minutes (Σ active time per role, the "compute-uptime"),
    - ``N_created`` — roles spun up.

    And it computes:

    - ``M_satisfaction`` (0-1),
    - ``T_ref`` / ``C_ref`` (running averages over the last ``REF_WINDOW``
      prior iterations),
    - ``E`` (the efficiency score),
    - ``below_floor`` (whether ``E < EFFICIENCY_FLOOR``).

    It appends the per-iteration snapshot to
    ``history/efficiency_metrics.jsonl`` (auditable + the dashboard's Efficiency
    panel). Thread-safe (a lock guards the accumulators; the file append is a
    single line).
    """

    def __init__(
        self,
        history_dir: str = "history",
        floor: float = EFFICIENCY_FLOOR,
    ):
        self.history_dir = history_dir
        self.floor = floor
        self._log_path = os.path.join(history_dir, "efficiency_metrics.jsonl")
        self._lock = threading.Lock()
        # Per-iteration accumulators (reset in start_iteration).
        self._t_p: Dict[int, float] = {}
        self._t_dept: Dict[str, float] = {}
        self._t_role: Dict[str, float] = {}
        self._headcount_samples: List[Tuple[float, float]] = []  # (n, dt)
        self._h_peak = 0
        self._n_created = 0
        # History of prior iterations' (T_total, C) for the running averages.
        self._history: List[Tuple[float, float]] = []
        self._last: Optional[Dict[str, Any]] = None

    # --- per-iteration accumulation ----------------------------------------

    def start_iteration(self) -> None:
        """Begin a new loop iteration (reset the per-iteration accumulators)."""
        with self._lock:
            self._t_p = {}
            self._t_dept = {}
            self._t_role = {}
            self._headcount_samples = []
            self._h_peak = 0
            self._n_created = 0

    def record_phase(self, phase: int, started: float, ended: float) -> None:
        """Record one phase's wall-clock time (``T_p[phase]``)."""
        with self._lock:
            self._t_p[phase] = self._t_p.get(phase, 0.0) + max(0.0, ended - started)

    def record_headcount(self, n: float, dt: float) -> None:
        """Record a headcount sample (``n`` roles in effect for ``dt`` seconds) —
        feeds ``H_peak`` (the max) and ``C`` (Σ n·dt, the role-minutes)."""
        with self._lock:
            self._headcount_samples.append((n, max(0.0, dt)))
            self._h_peak = max(self._h_peak, int(n))

    def record_role_time(self, role_id: str, department: str, elapsed: float) -> None:
        """Record one role's wall-clock time (``T_role`` + ``T_dept``)."""
        with self._lock:
            self._t_role[role_id] = self._t_role.get(role_id, 0.0) + max(0.0, elapsed)
            if department:
                self._t_dept[department] = \
                    self._t_dept.get(department, 0.0) + max(0.0, elapsed)

    def record_created(self, n: int) -> None:
        """Record roles spun up this iteration (``N_created``)."""
        with self._lock:
            self._n_created += n

    # --- derived values ----------------------------------------------------

    def _t_total(self) -> float:
        return sum(self._t_p.values())

    def _c(self) -> float:
        return sum(n * dt for n, dt in self._headcount_samples)

    def _running_averages(self) -> Tuple[Optional[float], Optional[float]]:
        """The running averages of (T_total, C) over the last ``REF_WINDOW``
        **prior** iterations. ``(None, None)`` when there are no prior
        iterations (the first iteration uses a neutral baseline)."""
        window = self._history[-REF_WINDOW:]
        if not window:
            return None, None
        t_ref = sum(t for t, _ in window) / len(window)
        c_ref = sum(c for _, c in window) / len(window)
        return t_ref, c_ref

    # --- finish + persist --------------------------------------------------

    def finish_iteration(self, m_satisfaction: float) -> Dict[str, Any]:
        """Finish the iteration: compute ``E`` (with the running-average refs),
        build the per-iteration snapshot, append it to the log, and return it."""
        with self._lock:
            t_total = self._t_total()
            c = self._c()
            t_ref, c_ref = self._running_averages()
            e = efficiency_score(m_satisfaction, t_total, c, t_ref, c_ref)
            below_floor = e < self.floor
            snap = {
                "ts": time.time(),
                "cycle": len(self._history) + 1,
                "T_total": t_total,
                "T_p": dict(self._t_p),
                "T_dept": dict(self._t_dept),
                "T_role": dict(self._t_role),
                "H_peak": self._h_peak,
                "C": c,
                "N_created": self._n_created,
                "M_satisfaction": m_satisfaction,
                "T_ref": t_ref,
                "C_ref": c_ref,
                "E": e,
                "EFFICIENCY_FLOOR": self.floor,
                "below_floor": below_floor,
            }
            # The current iteration becomes part of the history for the NEXT
            # iteration's running averages.
            self._history.append((t_total, c))
            self._last = snap
            self._append(snap)
            return snap

    def _append(self, snap: Dict[str, Any]) -> None:
        os.makedirs(self.history_dir, exist_ok=True)
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(snap, ensure_ascii=False) + "\n")

    def last(self) -> Optional[Dict[str, Any]]:
        """The most recent per-iteration snapshot (None if none yet)."""
        with self._lock:
            return self._last

    def panel_text(self) -> str:
        """Render the latest snapshot as text for the Leader's Phase 5/6 context
        (the full breakdown + ``E`` + the mandate to keep ``E`` high)."""
        snap = self.last()
        if snap is None:
            return ""
        lines = [
            "EFFICIENCY (S22) — per-iteration breakdown (wall-clock, local "
            "compute):"
        ]
        lines.append(
            f"  T_total={snap['T_total']:.1f}s  "
            f"H_peak={snap['H_peak']}  C={snap['C']:.1f} role-min  "
            f"N_created={snap['N_created']}"
        )
        if snap.get("T_p"):
            t_p = ", ".join(
                f"p{ph}={t:.1f}s" for ph, t in sorted(snap["T_p"].items())
            )
            lines.append(f"  per-phase: {t_p}")
        if snap.get("T_dept"):
            t_dept = ", ".join(
                f"{d}={t:.1f}s"
                for d, t in sorted(snap["T_dept"].items(), key=lambda kv: -kv[1])
            )
            lines.append(f"  per-department: {t_dept}")
        lines.append(
            f"  M_satisfaction={snap['M_satisfaction']:.2f}  "
            f"E={snap['E']:.3f}  (EFFICIENCY_FLOOR={snap['EFFICIENCY_FLOOR']})"
        )
        lines.append(
            "MANDATE: keep E HIGH — the mission should be completed with LESS "
            "headcount / compute time where possible (fire inefficient roles "
            "through HR, automate recurring tasks, or stop if the mission is "
            "already satisfied)."
        )
        if snap.get("below_floor"):
            lines.append(
                "E IS BELOW THE FLOOR — you MUST take a visible efficiency "
                "action (set `efficiency` with an `action` and a `target`)."
            )
        return "\n".join(lines)
