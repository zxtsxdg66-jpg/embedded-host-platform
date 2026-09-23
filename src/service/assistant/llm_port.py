"""The port the assistant talks to a language model through.

Defined here -- in the consumer -- rather than beside the concrete
backend, following the same convention as
``service.control_service_impl.CommandTransport``: the layer that needs a
capability declares its shape, and whoever composes the application
injects something that fits. The concrete Ollama client therefore lives
outside ``service/`` and never has to be imported by it.

The port is deliberately **non-blocking**. A CPU-only 4B model takes
several seconds per answer, and this project's PC side is single-threaded
(``QTimer -> poll_once()``, no QThread, no asyncio) -- a blocking call
would freeze the UI for the whole generation. So a caller submits, then
polls from the same loop that already drives everything else. See
docs/decisions/02-llm.md.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LlmClient(Protocol):
    """A local language model, driven by polling rather than blocking."""

    def submit(self, prompt: str, system: str = "") -> bool:
        """Start generating. Returns False if a request is already running.

        Must not block: it may open a socket and write the request, but
        must not wait for the response.
        """
        ...

    def poll(self) -> str | None:
        """Return text produced since the last call, or None if idle.

        Returns an empty string when a request is in flight but nothing
        new has arrived yet, which is how a caller distinguishes "still
        working" from "nothing running".
        """
        ...

    def is_busy(self) -> bool:
        """Whether a submitted request is still in flight."""
        ...

    def cancel(self) -> None:
        """Abandon the in-flight request, if any."""
        ...


class NullLlmClient:
    """The always-available implementation: never produces anything.

    This is what gets injected when Ollama is not installed, not running,
    or deliberately disabled -- and it is also the default. The assistant
    then answers entirely from rules and templates, which is the whole
    point of making the model optional: nothing about the feature's
    correctness depends on a model being present.

    Named by analogy with ``communication.loopback.LoopbackChannel``: the
    implementation that lets everything above it be exercised with no
    external dependency attached.
    """

    def submit(self, prompt: str, system: str = "") -> bool:
        return False

    def poll(self) -> str | None:
        return None

    def is_busy(self) -> bool:
        return False

    def cancel(self) -> None:
        return None
