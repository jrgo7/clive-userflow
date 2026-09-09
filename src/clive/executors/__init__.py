"""Executor registry and resolution.

Mirrors `clive.providers`: one module per backend, a REGISTRY, and an environment
variable that pins a choice. The difference is that a provider is chosen by name and
an executor is chosen by *capability* -- so `get_executor` probes, takes the strongest
backend that actually works on this host, and refuses anything weaker than
CLIVE_SANDBOX_FLOOR.
"""

from __future__ import annotations

from clive import config
from clive.executors.base import (
    ExecutionRequest,
    ExecutionResult,
    Executor,
    ExecutorError,
    Limits,
    RunOutcome,
)
from clive.executors.local import BwrapExecutor, LocalExecutor

__all__ = [
    "ExecutorError", "Executor", "ExecutionRequest", "ExecutionResult",
    "Limits", "RunOutcome", "REGISTRY", "get_executor", "available_executors",
]

#: Strongest first. `get_executor` takes the first one that probes clean.
REGISTRY: list[type[Executor]] = [BwrapExecutor, LocalExecutor]

#: Higher is stronger. CLIVE_SANDBOX_FLOOR names the weakest acceptable value.
ISOLATION_RANK = {"rlimit": 0, "namespace": 1, "container": 2}

_probed: dict[str, bool] = {}


def _probe(cls: type[Executor]) -> bool:
    """Cached, because probing runs a subprocess and the answer cannot change."""
    if cls.name not in _probed:
        try:
            _probed[cls.name] = bool(cls.probe())
        except Exception:
            _probed[cls.name] = False
    return _probed[cls.name]


def available_executors() -> list[type[Executor]]:
    """Every backend that works on this host, strongest first. Used by the tests."""
    return [cls for cls in REGISTRY if _probe(cls)]


def get_executor() -> Executor:
    floor = ISOLATION_RANK.get(config.SANDBOX_FLOOR, 0)

    if config.EXECUTOR:
        chosen = next((c for c in REGISTRY if c.name == config.EXECUTOR), None)
        if chosen is None:
            raise ExecutorError(
                f"Unknown executor {config.EXECUTOR!r}. Set CLIVE_EXECUTOR to one of: "
                f"{', '.join(c.name for c in REGISTRY)}."
            )
        if not _probe(chosen):
            raise ExecutorError(
                f"CLIVE_EXECUTOR names {chosen.name!r}, but it does not work on this host."
            )
        candidates = [chosen]
    else:
        candidates = available_executors()

    for cls in candidates:
        if ISOLATION_RANK[cls.isolation] >= floor:
            return cls()

    if not candidates:
        raise ExecutorError(
            "No usable executor. Install a C compiler, or a container runtime "
            "(podman or docker), to run student code."
        )
    raise ExecutorError(
        f"The strongest available executor is {candidates[0].name!r} with "
        f"{candidates[0].isolation!r} isolation, below CLIVE_SANDBOX_FLOOR="
        f"{config.SANDBOX_FLOOR!r}. Install podman or docker, or lower the floor."
    )
