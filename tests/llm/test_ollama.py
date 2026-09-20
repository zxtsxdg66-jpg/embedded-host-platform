"""OllamaClient against a fake socket replaying real server bytes.

The byte fixtures below are the actual shape a live Ollama 0.33.3 returns
(``Transfer-Encoding: chunked`` wrapping ``application/x-ndjson``),
captured from the server before this client was written. Testing against
a hand-simplified format would have missed the chunk framing entirely --
which was the one part of this module that could not be guessed.
"""

from __future__ import annotations

import socket

from llm import ollama
from llm.ollama import OllamaClient, _dechunk

_HEADERS = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: application/x-ndjson\r\n"
    b"Connection: close\r\n"
    b"Transfer-Encoding: chunked\r\n"
    b"\r\n"
)


def _chunk(payload: bytes) -> bytes:
    return f"{len(payload):x}".encode() + b"\r\n" + payload + b"\r\n"


def _ndjson(text: str, done: bool = False) -> bytes:
    body = f'{{"response":"{text}","done":{"true" if done else "false"}}}\n'
    return _chunk(body.encode("utf-8"))


PAUSE = None
"""Sentinel in a script meaning "nothing more is available this cycle".

Needed because ``poll()`` correctly drains everything the socket has
before returning -- without an explicit pause the fake would hand over
the whole response in one call, and a test for "still generating" would
be testing nothing.
"""


class _FakeSocket:
    """Replays a script of byte batches, pausing where told to."""

    def __init__(
        self, batches: list[bytes | None], fail_on_send: bool = False
    ) -> None:
        self._batches = list(batches)
        self._fail_on_send = fail_on_send
        self.sent = b""
        self.closed = False
        self.blocking = True

    def sendall(self, data: bytes) -> None:
        if self._fail_on_send:
            raise OSError("connection reset")
        self.sent += data

    def setblocking(self, flag: bool) -> None:
        self.blocking = flag

    def recv(self, _size: int) -> bytes:
        if not self._batches:
            raise BlockingIOError
        batch = self._batches.pop(0)
        if batch is PAUSE:
            raise BlockingIOError
        return batch

    def close(self) -> None:
        self.closed = True


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _client(
    batches: list[bytes | None] | None = None,
    *,
    connect_error: bool = False,
    fail_on_send: bool = False,
    clock: _Clock | None = None,
    timeout: float = 20.0,
) -> tuple[OllamaClient, list[_FakeSocket]]:
    made: list[_FakeSocket] = []

    def factory(host: str, port: int, connect_timeout: float) -> socket.socket:
        if connect_error:
            raise OSError("connection refused")
        sock = _FakeSocket(list(batches or []), fail_on_send=fail_on_send)
        made.append(sock)
        return sock  # type: ignore[return-value]

    client = OllamaClient(
        socket_factory=factory,
        clock=clock or _Clock(),
        timeout_seconds=timeout,
    )
    return client, made


# -- chunked transfer decoding ------------------------------------------------


def test_dechunk_decodes_complete_chunks() -> None:
    raw = _chunk(b"hello") + _chunk(b"world")
    decoded, rest = _dechunk(raw)
    assert decoded == b"helloworld"
    assert rest == b""


def test_dechunk_keeps_an_incomplete_chunk_for_next_time() -> None:
    """A chunk split across two TCP reads must not be mis-framed."""
    raw = _chunk(b"hello") + b"5\r\nwor"
    decoded, rest = _dechunk(raw)
    assert decoded == b"hello"
    assert rest == b"5\r\nwor"


def test_dechunk_stops_at_the_terminating_zero_chunk() -> None:
    raw = _chunk(b"a") + b"0\r\n\r\n"
    decoded, rest = _dechunk(raw)
    assert decoded == b"a"
    assert rest == b""


# -- the happy path -----------------------------------------------------------


def test_submit_writes_a_well_formed_request() -> None:
    client, made = _client([])
    assert client.submit("改写这句", system="你是助手")

    sent = made[0].sent.decode("utf-8")
    assert sent.startswith("POST /api/generate HTTP/1.1")
    assert '"stream": true' in sent
    assert '"think": false' in sent  # thinking would add tens of seconds
    assert "改写这句" in sent
    assert "你是助手" in sent


def test_socket_is_switched_to_non_blocking_after_the_write() -> None:
    """Reading is what waits on generation; only that must not block."""
    client, made = _client([])
    client.submit("x")
    assert made[0].blocking is False


def test_nothing_is_returned_until_the_response_is_complete() -> None:
    """A truncated sentence could pass the grounding check and be shown
    as an answer, so partial text never leaves this client."""
    client, _ = _client(
        [
            _HEADERS + _ndjson("噪声"),
            PAUSE,
            _ndjson("现在 62.5dB。", done=True),
        ]
    )
    client.submit("x")

    assert client.poll() == ""
    assert client.is_busy()

    assert client.poll() == "噪声现在 62.5dB。"
    assert not client.is_busy()


def test_a_response_split_mid_chunk_still_decodes() -> None:
    full = _HEADERS + _ndjson("一切") + _ndjson("正常。", done=True)
    client, _ = _client([full[:60], PAUSE, full[60:]])
    client.submit("x")

    result = ""
    while client.is_busy():
        result = client.poll() or ""
    assert result == "一切正常。"


def test_poll_returns_none_when_idle() -> None:
    client, _ = _client([])
    assert client.poll() is None


def test_a_second_submit_while_busy_is_refused() -> None:
    client, _ = _client([_HEADERS])
    assert client.submit("first")
    assert not client.submit("second")


# -- degradation --------------------------------------------------------------


def test_connection_refused_returns_false_rather_than_raising() -> None:
    """A missing model server is an ordinary state: the assistant keeps
    its template answer and the UI never sees an exception."""
    client, _ = _client(connect_error=True)

    assert client.submit("x") is False
    assert not client.is_busy()
    assert "connection refused" in client.last_error
    assert client.failure_count == 1


def test_a_failed_send_is_reported_not_raised() -> None:
    client, _ = _client([], fail_on_send=True)
    assert client.submit("x") is False
    assert client.failure_count == 1


def test_timeout_ends_the_request_with_no_text() -> None:
    clock = _Clock()
    client, made = _client([_HEADERS], clock=clock, timeout=5.0)
    client.submit("x")

    clock.now = 6.0
    assert client.poll() == ""
    assert not client.is_busy()
    assert client.timeout_count == 1
    assert made[0].closed


def test_cancel_closes_the_connection() -> None:
    client, made = _client([_HEADERS])
    client.submit("x")
    client.cancel()

    assert not client.is_busy()
    assert made[0].closed


def test_cancel_is_safe_when_idle() -> None:
    client, _ = _client([])
    client.cancel()  # must not raise


# -- probe --------------------------------------------------------------------


def test_probe_true_when_the_server_answers_200() -> None:
    client, _ = _client([b"HTTP/1.1 200 OK\r\n"])
    assert client.probe() is True


def test_probe_false_when_nothing_is_listening() -> None:
    client, _ = _client(connect_error=True)
    assert client.probe() is False
    assert client.last_error


def test_probe_closes_its_socket() -> None:
    client, made = _client([b"HTTP/1.1 200 OK\r\n"])
    client.probe()
    assert made[0].closed


def test_sampling_temperature_is_pinned_low() -> None:
    """出口检查反复退回的那些补话——"请注意保暖""环境状态良好"——2026-09-09
    实测下来是**采样随机性**而非模型不懂：默认温度 0.8 下 90 次改写采纳 72，
    0.3 与 0.0 下 60 次全部采纳，且低温还快约 5%。

    这项没有任何检查会因它被改回默认而失败——出口检查照样把补话拦下、
    答复照样正确，只是失败率悄悄从 0 回到两成。故在此钉住。
    """
    import json

    client, made = _client([])
    assert client.submit("改写这句")

    body = made[0].sent.decode("utf-8").split("\r\n\r\n", 1)[1]
    options = json.loads(body)["options"]
    assert options["temperature"] == ollama.DEFAULT_TEMPERATURE
    assert 0.0 <= ollama.DEFAULT_TEMPERATURE <= 0.5


def test_the_token_cap_leaves_room_for_the_explain_job() -> None:
    """`num_predict` 由改写档与解释档共用。改写档只用二三十个 token，看起来
    收紧到 48 毫无代价——25/25 采纳、零截断；但解释档要用约 57 个，48 时会
    断在"…仍有 11.0℃"这样紧跟数字的地方，读起来像系统坏了而不是话多。

    只测改写档就会得出"48 完全安全"的结论。此处钉住下限。
    """
    assert ollama.DEFAULT_NUM_PREDICT >= 120
