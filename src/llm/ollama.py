"""Non-blocking client for a local Ollama server.

Shape and rationale
-------------------
This project's PC side is single-threaded and synchronous: a ``QTimer``
drives ``poll_once()``, which advances the runner and then every
dispatcher. There is no QThread and no asyncio, deliberately -- it is what
makes the whole data path drivable from a test. A CPU-only 4B model needs
several seconds per answer, so a blocking HTTP call would freeze the
interface for exactly that long.

So this client is driven the same way everything else is: :meth:`submit`
sends the request and returns immediately, :meth:`poll` is called once per
cycle and does whatever reading is possible without waiting. It is the
same non-blocking request/response pattern the firmware uses for the
Modbus noise sensor (``noise_sensor_poll()``), applied on the PC side.

Why it buffers instead of streaming to its caller
-------------------------------------------------
Ollama streams token by token, and this client consumes that stream so it
can detect completion and enforce a deadline -- but it hands nothing to
the caller until the response is **complete**. Two reasons:

- The caller (``service.assistant``) already displayed a correct template
  answer instantly; the model's version merely replaces it. Revealing a
  half-finished replacement character by character would look like the
  answer flickering, not like progress.
- A truncated sentence is dangerous here in a way it is not in a chat
  app: "噪声现在 76.3dB，一切正" would pass the grounding check and be
  shown as an answer. Emitting only complete responses removes that
  failure mode entirely rather than trying to detect it downstream.

Transport
---------
Written against a raw socket rather than a HTTP library because the
requirement is *non-blocking incremental reads*, which neither ``urllib``
nor ``httpx`` provides without a thread or an event loop. Ollama replies
with ``Transfer-Encoding: chunked`` carrying ``application/x-ndjson``, so
both layers are decoded here -- roughly forty lines, and the alternative
was a new dependency that still would not solve the blocking problem.

Never raises into its caller. A server that is missing, refusing
connections, or slow is an ordinary condition: the assistant falls back
to its template answer, which was already correct.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from time import monotonic

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11434
DEFAULT_MODEL = "qwen3.5:4b"
"""Measured at 10.4 tok/s on the target machine (i5-13500H, no GPU).

See docs/02_Architecture/Assistant_Design.md section 7.0 -- the tag
resolves to q4_K_M, which is the floor rather than a compromise.
"""

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_NUM_THREAD = 8
"""Four P-cores plus hyper-threading. Handing llama.cpp all 12/16 logical
cores is usually slower on this part, because the E-cores finish their
share late and the whole step waits for them."""

DEFAULT_NUM_PREDICT = 160
"""Hard cap on generated tokens. The task is rewording one sentence; a
model that starts rambling is bounded rather than left to fill the
deadline.

**Measured 2026-09-09 and deliberately left where it is.** Tightening it
looked like a cheaper version of the output-length check -- cut the
padding off at generation instead of judging it afterwards -- and across
100 rewordings at 160 / 80 / 48 / template-proportional the acceptance
rate was 25/25 every time with no truncation and no speed difference.
Once the temperature below is set, a reworded sentence runs to twenty or
thirty tokens and never approaches any of these ceilings.

The explain job is why it stays at 160 rather than dropping anyway: it
shares this client, and its answers run to about 57 tokens. At 48 one came
back as "…距离报警阈值 35℃ 仍有 11.0℃" -- cut immediately after a number,
which reads as a broken system rather than a chatty one. The rewording
measurements would never have shown this; they only exercised one of the
two jobs."""

DEFAULT_TEMPERATURE = 0.3
"""Sampling temperature. Ollama's own default is 0.8, which is what this
client used until 2026-09-09.

The additions that the output checks kept refusing -- "请注意保暖",
"环境状态良好", "目前已确认该数值为历史最高值" -- turned out to be
sampling noise rather than misunderstanding: across 90 rewordings at the
default temperature 72 were accepted, and across 60 at 0.3 and 0.0 all 60
were. Low temperature is also about 5% faster, because fewer tokens are
explored and fewer produced.

0.3 rather than 0.0, which scored the same and ran faster still: the retry
path needs the second attempt to differ from the first, and at 0.0 the
only thing making it differ is the changed system prompt. A little
sampling noise is a second way out of a refusal.

This does not relax any guarantee -- the output checks are unchanged, and
still refuse whatever gets through. It lowers how often they have to."""

_CONNECT_TIMEOUT_SECONDS = 1.0
"""Connecting and writing are left blocking: the peer is on loopback, so
both complete in well under a millisecond. Only *reading* -- which waits
on generation -- has to be non-blocking, and that is where all the
complexity would otherwise go for no benefit."""

SocketFactory = Callable[[str, int, float], socket.socket]


def _default_socket_factory(host: str, port: int, timeout: float) -> socket.socket:
    return socket.create_connection((host, port), timeout=timeout)


class OllamaClient:
    """Talks to a local Ollama server without ever blocking the caller."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        num_thread: int = DEFAULT_NUM_THREAD,
        num_predict: int = DEFAULT_NUM_PREDICT,
        temperature: float = DEFAULT_TEMPERATURE,
        socket_factory: SocketFactory = _default_socket_factory,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._model = model
        self._host = host
        self._port = port
        self._timeout = timeout_seconds
        self._num_thread = num_thread
        self._num_predict = num_predict
        self._temperature = temperature
        self._socket_factory = socket_factory
        self._clock = clock

        self._socket: socket.socket | None = None
        self._raw = b""
        self._headers_done = False
        self._text = ""
        self._deadline = 0.0
        self._complete = False
        self.last_error: str = ""
        self.request_count = 0
        self.timeout_count = 0
        self.failure_count = 0

    # -- LlmClient protocol ----------------------------------------------

    def submit(self, prompt: str, system: str = "") -> bool:
        """Open a connection and write the request. Returns False on failure.

        False rather than an exception because "the model is unavailable"
        is a normal state for this feature, not an error: the assistant
        simply keeps its template answer.
        """
        if self.is_busy():
            return False

        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": True,
            # Qwen3.5 advertises a thinking capability; leaving it on adds
            # tens of seconds of reasoning tokens to what is a one-sentence
            # rewording task.
            "think": False,
            "options": {
                "num_thread": self._num_thread,
                "num_predict": self._num_predict,
                "temperature": self._temperature,
            },
        }
        if system:
            payload["system"] = system

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = (
            b"POST /api/generate HTTP/1.1\r\n"
            b"Host: " + self._host.encode("ascii") + b"\r\n"
            b"Content-Type: application/json\r\n"
            b"Connection: close\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"\r\n" + body
        )

        try:
            sock = self._socket_factory(
                self._host, self._port, _CONNECT_TIMEOUT_SECONDS
            )
            sock.sendall(request)
            sock.setblocking(False)
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.failure_count += 1
            self._close()
            return False

        self._socket = sock
        self._raw = b""
        self._headers_done = False
        self._text = ""
        self._complete = False
        self._deadline = self._clock() + self._timeout
        self.request_count += 1
        return True

    def poll(self) -> str | None:
        """Read whatever has arrived. Returns the answer only once complete.

        - ``None``  -- nothing in flight.
        - ``""``    -- still generating (or the attempt failed, in which
          case the caller's accumulated text stays empty and it falls back
          to its template).
        - the text  -- the finished response, returned exactly once.
        """
        if self._socket is None:
            return None

        if self._clock() > self._deadline:
            self.timeout_count += 1
            self.last_error = f"timed out after {self._timeout:g}s"
            self._close()
            return ""

        try:
            while True:
                data = self._socket.recv(8192)
                if not data:
                    break
                self._raw += data
        except BlockingIOError:
            pass  # nothing more available right now -- expected every cycle
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.failure_count += 1
            self._close()
            return ""

        self._consume()

        if not self._complete:
            return ""

        text = self._text
        self._close()
        return text

    def is_busy(self) -> bool:
        return self._socket is not None

    def cancel(self) -> None:
        """Abandon an in-flight request. Safe to call when idle."""
        self._close()

    # -- reachability ------------------------------------------------------

    def probe(self) -> bool:
        """Whether the server answers at all, checked once at start-up.

        Deliberately blocking and deliberately brief: this runs during
        composition, before any UI exists, and a loopback connection
        either succeeds immediately or is not there.
        """
        try:
            sock = self._socket_factory(
                self._host, self._port, _CONNECT_TIMEOUT_SECONDS
            )
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False
        try:
            sock.sendall(
                b"GET /api/tags HTTP/1.1\r\n"
                b"Host: " + self._host.encode("ascii") + b"\r\n"
                b"Connection: close\r\n\r\n"
            )
            head = sock.recv(64)
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False
        finally:
            sock.close()
        return head.startswith(b"HTTP/1.1 200")

    # -- decoding ----------------------------------------------------------

    def _close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        self._socket = None

    def _consume(self) -> None:
        """Strip HTTP headers, de-chunk, then parse the NDJSON lines."""
        if not self._headers_done:
            marker = self._raw.find(b"\r\n\r\n")
            if marker < 0:
                return
            self._raw = self._raw[marker + 4 :]
            self._headers_done = True

        body, self._raw = _dechunk(self._raw)
        for line in body.split(b"\n"):
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                # A partial line can only appear if _dechunk handed back an
                # incomplete chunk, which it does not -- but tolerating it
                # is cheaper than trusting that forever.
                continue
            self._text += str(message.get("response", ""))
            if message.get("done"):
                self._complete = True


def _dechunk(raw: bytes) -> tuple[bytes, bytes]:
    """Decode as many complete HTTP chunks as ``raw`` holds.

    Returns ``(decoded, remainder)``; the remainder is whatever partial
    chunk is left for the next call. Ollama sends ``Transfer-Encoding:
    chunked`` with one NDJSON line per chunk, so a naive line split over
    the raw stream would swallow the hex size prefixes.
    """
    out = bytearray()
    while True:
        marker = raw.find(b"\r\n")
        if marker < 0:
            break
        try:
            size = int(raw[:marker].split(b";")[0], 16)
        except ValueError:
            # Not a chunk header -- give up rather than mis-frame the rest.
            break
        if size == 0:
            raw = b""
            break
        end = marker + 2 + size
        if len(raw) < end + 2:
            break  # chunk not fully arrived yet
        out += raw[marker + 2 : end]
        raw = raw[end + 2 :]
    return bytes(out), raw
