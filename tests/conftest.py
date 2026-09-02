"""Shared test setup.

The one thing here is a net guard, and it exists because of a real near miss. Every
test stubs the provider, but `clive.config` calls `load_dotenv` at import, so a real
`ANTHROPIC_API_KEY` is present while the suite runs. A test that stubs three of the
four modules that call a provider does not fail loudly on the fourth — it reaches the
live API, bills for it, and passes. That is the worst kind of green.

So: no outbound connection from the suite. Loopback stays open, for a test that wants
to stand up the Studio's own HTTP server.
"""

from __future__ import annotations

import socket

import pytest

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex

_LOCAL = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


def _is_local(address) -> bool:
    if isinstance(address, tuple) and address:
        return str(address[0]) in _LOCAL
    return False  # AF_UNIX and anything unrecognised: not our business to allow


class NetworkUsedInTests(RuntimeError):
    """A test tried to reach the network. Almost always a provider left unstubbed."""


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    def guard(self, address, *a, **kw):
        if not _is_local(address):
            raise NetworkUsedInTests(
                f"A test tried to connect to {address!r}. The suite runs offline — this is "
                "almost certainly a module whose `get_provider` was not monkeypatched, which "
                "would otherwise reach the live API and bill for it."
            )
        return _real_connect(self, address, *a, **kw)

    def guard_ex(self, address, *a, **kw):
        if not _is_local(address):
            raise NetworkUsedInTests(f"A test tried to connect to {address!r}. The suite runs offline.")
        return _real_connect_ex(self, address, *a, **kw)

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard_ex)
