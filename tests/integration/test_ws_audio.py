from typing import Any

from fastapi.testclient import TestClient
from pcm import chunks, tone

from manura.config import Settings
from manura.main import create_app


def _client() -> TestClient:
    settings = Settings(_env_file=None, stt_engine="fake", llm_provider="fake")  # type: ignore[call-arg]
    return TestClient(create_app(settings))


def _receive_until_stopped(ws: Any) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    while True:
        msg = ws.receive_json()
        messages.append(msg)
        if msg["type"] in ("stopped", "error"):
            return messages


def test_client_config() -> None:
    res = _client().get("/api/client-config")
    assert res.status_code == 200
    assert res.json()["sample_rate"] == 16000


def test_index_is_served() -> None:
    res = _client().get("/")
    assert res.status_code == 200
    assert "신규상담" in res.text


def test_start_stream_stop_flow() -> None:
    with _client().websocket_connect("/ws/audio") as ws:
        ws.send_json({"type": "start"})
        started = ws.receive_json()
        assert started["type"] == "started"
        for c in chunks(tone(2000)):
            ws.send_bytes(c)
        ws.send_json({"type": "stop"})
        messages = _receive_until_stopped(ws)

    assert messages[-1] == {"type": "stopped", "turn_id": started["turn_id"]}
    kinds = {m["type"] for m in messages}
    assert {"partial", "final"} <= kinds


def _parse_sse(body: str) -> list[tuple[str, str]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], lines["data"]))
    return events


def test_stop_then_advise_streams_answer() -> None:
    client = _client()
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_json({"type": "start"})
        turn_id = ws.receive_json()["turn_id"]
        for c in chunks(tone(3000)):
            ws.send_bytes(c)
        ws.send_json({"type": "stop"})
        _receive_until_stopped(ws)

    res = client.post(f"/api/turns/{turn_id}/advise")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(res.text)
    assert events[-1] == ("done", "{}")
    assert {name for name, _ in events[:-1]} == {"token"}


def test_advise_unknown_turn_is_404() -> None:
    assert _client().post("/api/turns/nope/advise").status_code == 404


def test_advise_without_speech_is_422() -> None:
    client = _client()
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_json({"type": "start"})
        turn_id = ws.receive_json()["turn_id"]
        ws.send_json({"type": "stop"})
        _receive_until_stopped(ws)
    assert client.post(f"/api/turns/{turn_id}/advise").status_code == 422


def test_continue_recording_on_same_connection() -> None:
    with _client().websocket_connect("/ws/audio") as ws:
        turn_ids = []
        for _ in range(2):
            ws.send_json({"type": "start"})
            turn_ids.append(ws.receive_json()["turn_id"])
            for c in chunks(tone(500)):
                ws.send_bytes(c)
            ws.send_json({"type": "stop"})
            assert _receive_until_stopped(ws)[-1]["type"] == "stopped"
    assert turn_ids[0] != turn_ids[1]


def test_double_start_is_rejected() -> None:
    with _client().websocket_connect("/ws/audio") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        ws.send_json({"type": "start"})
        assert ws.receive_json()["code"] == "ALREADY_RECORDING"
