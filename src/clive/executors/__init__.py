"""Executor registry and resolution.

Mirrors `clive.providers`: one module per backend, a REGISTRY, and an environment
variable that pins a choice. The difference is that a provider is chosen by name and
an executor is chosen by *capability* -- so `get_executor` probes, takes the strongest
backend that actually works on this host, and refuses anything weaker than
CLIVE_SANDBOX_FLOOR.
"""

from __future__ import annotations

import subprocess

from clive import config
from clive.executors.base import (
    ExecutionRequest,
    ExecutionResult,
    Executor,
    ExecutorError,
    Limits,
    RunOutcome,
)
from clive.executors.container import ContainerExecutor
from clive.executors.local import BwrapExecutor, LocalExecutor

__all__ = [
    "ExecutorError", "Executor", "ExecutionRequest", "ExecutionResult",
    "Limits", "RunOutcome", "REGISTRY", "get_executor", "available_executors",
    "describe_toolchain",
]

#: Strongest first. `get_executor` takes the first one that probes clean.
REGISTRY: list[type[Executor]] = [ContainerExecutor, BwrapExecutor, LocalExecutor]

#: Higher is stronger. CLIVE_SANDBOX_FLOOR names the weakest acceptable value.
ISOLATION_RANK = {"rlimit": 0, "namespace": 1, "container": 2}

_probed: dict[str, bool | str] = {}


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
    # `.get(..., 0)` used to be the rule here, which fails open: an unrecognised or
    # miscapitalized CLIVE_SANDBOX_FLOOR (a typo, or "Container" with a capital C)
    # silently resolved to 0 -- the weakest floor -- rather than refusing to run, on
    # the one setting that exists to refuse a weak sandbox on a multi-participant
    # host. `get_provider()` fails loudly on an unknown CLIVE_PROVIDER; this now does
    # the same for CLIVE_SANDBOX_FLOOR. (config.SANDBOX_FLOOR is already
    # lowercased/stripped at read time, so this only ever rejects a genuinely unknown
    # value, not a casing difference.)
    floor_name = config.SANDBOX_FLOOR
    try:
        floor = ISOLATION_RANK[floor_name]
    except KeyError:
        raise ExecutorError(
            f"Unknown CLIVE_SANDBOX_FLOOR {floor_name!r}. Set it to one of: "
            f"{', '.join(ISOLATION_RANK)}."
        ) from None

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


def describe_toolchain(executor: Executor) -> str:
    """What compiled the code, in one line.

    The container backend answers with its image, which is the whole reason it is the
    default: the image is the toolchain. Everything else has to ask the host's gcc, and
    the answer is cached because it cannot change while the process runs.
    """
    if executor.isolation == "container":
        return config.EXECUTOR_IMAGE
    if "gcc" not in _probed:
        try:
            done = subprocess.run(["gcc", "--version"], capture_output=True, text=True, timeout=10)
            _probed["gcc"] = done.stdout.splitlines()[0] if done.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError, IndexError):
            _probed["gcc"] = ""
    return _probed["gcc"] or "unknown"
