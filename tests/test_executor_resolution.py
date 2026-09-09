"""`get_executor()`'s own resolution logic: the floor, CLIVE_EXECUTOR, and the
"nothing available" case.

Every test in `test_executors.py` goes through `available_executors()` directly, or
constructs a backend class itself -- nothing there exercises `get_executor()`'s own
code. That is exactly how a `CLIVE_SANDBOX_FLOOR` typo went unnoticed: it fails open,
silently, with nothing in the suite ever calling the function that fails open.

These are pure resolution-logic tests against fake backends, so unlike
`test_executors.py` they need no gcc, podman, or docker and must run everywhere.
"""

from __future__ import annotations

import pytest

from clive import config
from clive import executors as executors_module
from clive.executors import ExecutorError, get_executor
from clive.executors.base import ExecutionResult, Executor


def make_executor(name: str, isolation: str, probe_ok: bool = True) -> type[Executor]:
    """A fresh `Executor` subclass, probe and execute defined in the class body.

    `get_executor`'s probe cache (`_probed`) is keyed by `cls.name`, so two fakes
    reusing a name across tests would read each other's cached probe result --
    `_probed` is reset per test below too, but a unique-enough name is cheap
    insurance. `probe`/`execute` must be in the class dict at creation time: `ABCMeta`
    computes `__abstractmethods__` then, so assigning them afterward would still
    leave the class impossible to instantiate.
    """

    def probe(cls) -> bool:
        return probe_ok

    def execute(self, request):
        return ExecutionResult(True, "", "", [])

    return type(
        f"Fake_{name}",
        (Executor,),
        {"name": name, "isolation": isolation, "probe": classmethod(probe), "execute": execute},
    )


@pytest.fixture(autouse=True)
def _fresh_probe_cache(monkeypatch):
    """`get_executor` and `available_executors` share a module-level probe cache.
    Without resetting it, a fake registered under a name a real backend also uses
    (or reused across two tests in this file) would read a stale cached answer."""
    monkeypatch.setattr(executors_module, "_probed", {})


def _configure(monkeypatch, registry, floor="rlimit", executor_name=""):
    monkeypatch.setattr(executors_module, "REGISTRY", registry)
    monkeypatch.setattr(config, "SANDBOX_FLOOR", floor)
    monkeypatch.setattr(config, "EXECUTOR", executor_name)


# --------------------------------------------------------------------------- floor


def test_returns_the_strongest_backend_that_meets_the_floor(monkeypatch):
    weak = make_executor("fake-weak", "rlimit")
    strong = make_executor("fake-strong", "container")
    _configure(monkeypatch, [strong, weak], floor="rlimit")
    assert get_executor().name == "fake-strong"


def test_floor_refuses_a_weak_backend_even_when_nothing_stronger_was_requested_by_name(monkeypatch):
    """The finding this guards: a floor must hold even on the ordinary, no-CLIVE_EXECUTOR
    path -- refusing to fall back to a backend weaker than the floor demands, rather
    than silently serving whatever probed."""
    weak = make_executor("fake-weak", "rlimit")
    _configure(monkeypatch, [weak], floor="namespace")
    with pytest.raises(ExecutorError, match="below CLIVE_SANDBOX_FLOOR"):
        get_executor()


def test_an_unrecognised_floor_value_raises_rather_than_failing_open(monkeypatch):
    """Regression for the Critical-adjacent bug: `ISOLATION_RANK.get(floor, 0)` used
    to resolve any unknown or miscapitalized value to 0 -- the weakest floor -- rather
    than refusing to run. `CLIVE_SANDBOX_FLOOR` is set directly here (bypassing
    config.py's own lowering) so this holds regardless of whether that normalisation
    ever runs."""
    strong = make_executor("fake-strong", "container")
    _configure(monkeypatch, [strong], floor="Container")  # capital C: config.py normally lowercases
    with pytest.raises(ExecutorError, match="Unknown CLIVE_SANDBOX_FLOOR"):
        get_executor()
    _configure(monkeypatch, [strong], floor="bogus")
    with pytest.raises(ExecutorError, match="Unknown CLIVE_SANDBOX_FLOOR"):
        get_executor()


# ---------------------------------------------------------------------- CLIVE_EXECUTOR


def test_executor_env_var_picks_a_specific_backend_by_name(monkeypatch):
    weak = make_executor("fake-weak", "rlimit")
    strong = make_executor("fake-strong", "container")
    _configure(monkeypatch, [strong, weak], floor="rlimit", executor_name="fake-weak")
    assert get_executor().name == "fake-weak"


def test_executor_env_var_does_not_bypass_the_floor(monkeypatch):
    weak = make_executor("fake-weak", "rlimit")
    _configure(monkeypatch, [weak], floor="container", executor_name="fake-weak")
    with pytest.raises(ExecutorError, match="below CLIVE_SANDBOX_FLOOR"):
        get_executor()


def test_executor_env_var_naming_an_unregistered_backend_raises(monkeypatch):
    known = make_executor("fake-known", "rlimit")
    _configure(monkeypatch, [known], floor="rlimit", executor_name="no-such-backend")
    with pytest.raises(ExecutorError, match="Unknown executor"):
        get_executor()


def test_executor_env_var_naming_a_backend_that_fails_its_own_probe_raises(monkeypatch):
    broken = make_executor("fake-broken", "container", probe_ok=False)
    _configure(monkeypatch, [broken], floor="rlimit", executor_name="fake-broken")
    with pytest.raises(ExecutorError, match="does not work on this host"):
        get_executor()


# -------------------------------------------------------------------- nothing works


def test_no_backends_registered_at_all_raises(monkeypatch):
    _configure(monkeypatch, [], floor="rlimit")
    with pytest.raises(ExecutorError, match="No usable executor"):
        get_executor()


def test_backends_registered_but_none_probe_clean_raises(monkeypatch):
    broken = make_executor("fake-broken", "rlimit", probe_ok=False)
    _configure(monkeypatch, [broken], floor="rlimit")
    with pytest.raises(ExecutorError, match="No usable executor"):
        get_executor()
