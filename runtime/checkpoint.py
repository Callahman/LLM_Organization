"""Work-item checkpointing — fine-grained crash recovery.

Two pieces:

- :class:`WorkItemTracker` tracks per-phase work-item progress (which
  departments / teams / ICs are completed, which is in progress). This is the
  checkpoint's recovery state, persisted to ``state/checkpoint.json`` and used
  on resume to skip completed work items (exact next-role resumption).

- :class:`CheckpointBackend` is a transparent ``LLMBackend`` wrapper (mirrors
  :class:`runtime.timing.TimingBackend`) that counts every ``invoke`` and fires
  the session's N-action checkpoint callback every N invokes. It also injects
  the (scoped) "verify your work" preamble when resuming from a checkpoint.
"""

from typing import Any, Callable, Dict, List, Optional

# The "verify your work" preamble, prepended to a role's prompt only while
# resuming the phase that was interrupted (see ``CheckpointBackend.resuming``).
# It turns blind re-execution of the in-progress work item into
# confirm-or-complete, so a partially-written artifact is confirmed rather than
# duplicated.
VERIFY_WORK_PREAMBLE = (
    "You are resuming from a checkpoint. Some of your work (or your team's) "
    "may already be on disk. Before producing output, check the existing "
    "artifacts; if the work is already complete, confirm it rather than "
    "redoing it."
)


class WorkItemTracker:
    """Per-phase work-item progress (the checkpoint's recovery state).

    ``completed`` maps a phase number to the list of completed work-item ids
    (department head ids for Phase 4, team manager ids for Phase 5, IC ids for
    Phase 6). ``current`` is the work item in progress at the last checkpoint
    (``{phase, id, kind}`` with ``kind`` in ``department`` / ``team`` / ``ic``).
    """

    def __init__(self) -> None:
        self.completed: Dict[int, List[str]] = {}
        self.current: Optional[Dict[str, Any]] = None

    def mark_started(self, phase: int, item_id: str, kind: str) -> None:
        """Record that ``item_id`` (of ``kind``) in ``phase`` just started."""
        self.current = {"phase": phase, "id": item_id, "kind": kind}

    def mark_completed(self, phase: int, item_id: str) -> None:
        """Record that ``item_id`` in ``phase`` is fully done."""
        if not self.is_completed(phase, item_id):
            self.completed.setdefault(phase, []).append(item_id)
        if self.current and self.current.get("id") == item_id:
            self.current = None

    def is_completed(self, phase: int, item_id: str) -> bool:
        """True if ``item_id`` in ``phase`` is already completed (skip it)."""
        return item_id in self.completed.get(phase, [])

    def seed(self, completed: Optional[Dict[Any, List[str]]]) -> None:
        """Load a prior checkpoint's completed set (resume).

        ``completed`` may have string keys (from JSON); they are coerced to
        ints. Ids are de-duplicated against the existing buckets.
        """
        for ph, ids in (completed or {}).items():
            bucket = self.completed.setdefault(int(ph), [])
            for i in ids:
                if i not in bucket:
                    bucket.append(i)

    def snapshot(self) -> Dict[str, Any]:
        """The dict persisted into ``state/checkpoint.json``."""
        return {
            "completed_work_items": self.completed,
            "current_work_item": self.current,
        }

    def reset(self) -> None:
        """Clear all recorded progress (a fresh start).

        The Phases 4-8 self-improving loop re-runs every phase from scratch on
        each iteration, so the previous iteration's completed work items must
        NOT carry over: a department already planned last iteration is
        re-planned this one (skipping it would dispatch zero work and escalate
        a no-op cycle). The resume seed (loaded from a crashed run's
        checkpoint) is consumed by the FIRST iteration only — the session
        resets the tracker before each subsequent iteration.
        """
        self.completed = {}
        self.current = None


class CheckpointBackend:
    """A transparent ``LLMBackend`` wrapper that counts invokes and fires the
    N-action checkpoint callback.

    ``invoke`` forwards ``*args`` / ``**kwargs`` to the inner backend (so it is
    compatible with every backend's invoke signature), then increments
    ``action_count`` and — every ``every_n`` invokes — calls ``on_checkpoint``
    (the session's light N-action checkpoint). While ``resuming`` is True it
    prepends :data:`VERIFY_WORK_PREAMBLE` to the prompt (scoped to the resumed
    phase only). All other attributes are delegated to the inner backend
    (``__getattr__``), so the wrapper is drop-in at the outermost position of
    the chain.
    """

    def __init__(self, inner: Any, every_n: int = 5,
                 verify_preamble: str = VERIFY_WORK_PREAMBLE) -> None:
        # ``inner`` / ``every_n`` / ... are plain attributes; ``__getattr__``
        # only fires for *missing* attributes, so they resolve normally.
        self.inner = inner
        self.every_n = every_n
        self.verify_preamble = verify_preamble
        self.action_count = 0
        self.on_checkpoint: Optional[Callable[[], None]] = None
        self.resuming = False

    def invoke(self, role: Any, context: Any, *args: Any, **kwargs: Any) -> Any:
        if self.resuming and self.verify_preamble:
            context = self.verify_preamble + "\n\n" + context
        out = self.inner.invoke(role, context, *args, **kwargs)
        self.action_count += 1
        if (self.on_checkpoint is not None and self.every_n > 0
                and self.action_count % self.every_n == 0):
            self.on_checkpoint()
        return out

    def __getattr__(self, name: str) -> Any:
        # Delegate any attribute the wrapper does not define (save_state,
        # load_state, seed_cross_team, ...). ``__getattr__`` is only called
        # when normal lookup fails, so ``self.inner`` / ``self.every_n`` / ...
        # are never re-routed here.
        return getattr(self.inner, name)
