import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pcm import chunks, tone

from manura.config import Settings
from manura.domain.errors import LLMError
from manura.main import create_app


def _client(data_dir: Path) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, stt_engine="fake", llm_provider="fake", data_dir=data_dir
    )
    return TestClient(create_app(settings))


def _record_turn(client: TestClient) -> str:
    with client.websocket_connect("/ws/audio") as ws:
        ws.send_json({"type": "start"})
        turn_id: str = ws.receive_json()["turn_id"]
        for c in chunks(tone(3000)):
            ws.send_bytes(c)
        ws.send_json({"type": "stop"})
        while ws.receive_json()["type"] != "stopped":
            pass
    return turn_id


class CapturingLLM:
    def __init__(self, answer: str = "의견") -> None:
        self.prompts: list[str] = []
        self.answer = answer

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        self.prompts.append(user)
        yield self.answer


class FailingLLM:
    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        raise LLMError("모델 오류")
        yield ""  # pragma: no cover


def _use_llm(client: TestClient, llm: object) -> None:
    container = client.app.state.container  # type: ignore[attr-defined]
    container.advice._llm = llm
    container.sessions._llm = llm


PROFILE = {"name": "김민지", "age": "30대", "gender": "여성", "concern": "이직", "traits": ""}
RECORD: dict[str, Any] = {
    "started_at": "2026-11-19T09:58:00Z",
    "profile": PROFILE,
    "entries": [
        {"kind": "note", "text": "상담자 정보 적용", "at": "2026-11-19T09:59:00Z"},
        {"kind": "transcript", "turn": 1, "text": "회사가 힘들어요", "at": "2026-11-19T10:00:00Z"},
        {"kind": "advice", "turn": 1, "text": "들어주세요", "at": "2026-11-19T10:00:05Z"},
    ],
}


def _rows(db: Path, sql: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchall()


def test_profile_is_included_in_advice_prompt(tmp_path: Path) -> None:
    client = _client(tmp_path)
    llm = CapturingLLM()
    _use_llm(client, llm)
    turn_id = _record_turn(client)

    res = client.post(f"/api/turns/{turn_id}/advise", json={"profile": PROFILE})

    assert res.status_code == 200
    prompt = llm.prompts[0]
    assert "- 호칭: 김민지" in prompt
    assert "- 고민: 이직" in prompt
    assert "특징" not in prompt.split("[통화 내용]")[0]  # 빈 항목은 넣지 않는다


def test_advise_without_body_uses_empty_profile(tmp_path: Path) -> None:
    client = _client(tmp_path)
    turn_id = _record_turn(client)
    assert client.post(f"/api/turns/{turn_id}/advise").status_code == 200


def test_save_writes_profile_conversation_and_summary_to_sqlite(tmp_path: Path) -> None:
    client = _client(tmp_path)
    llm = CapturingLLM(answer="1. 고객 고민 요약: 이직 고민")
    _use_llm(client, llm)

    res = client.post("/api/sessions/save", json=RECORD)

    assert res.status_code == 200
    body = res.json()
    assert body["summary"] == "1. 고객 고민 요약: 이직 고민"
    assert body["summary_error"] is None
    # 정리 프롬프트에는 상담자 정보와 대화가 들어가고, 안내(note)는 빠진다
    assert "- 호칭: 김민지" in llm.prompts[0]
    assert "[녹음 1 · 통화]\n회사가 힘들어요" in llm.prompts[0]
    assert "상담자 정보 적용" not in llm.prompts[0]

    db = tmp_path / "manura.db"
    sessions = _rows(db, "SELECT id, started_at, name, age, gender, concern, summary FROM sessions")
    assert sessions == [
        (body["id"], "2026-11-19T09:58:00Z", "김민지", "30대", "여성", "이직", body["summary"])
    ]
    entries = _rows(db, "SELECT seq, kind, turn, text FROM session_entries ORDER BY seq")
    assert [e[1] for e in entries] == ["note", "transcript", "advice"]


def test_resave_updates_same_record(tmp_path: Path) -> None:
    client = _client(tmp_path)
    first = client.post("/api/sessions/save", json=RECORD).json()
    more = {
        **RECORD,
        "id": first["id"],
        "entries": [
            *RECORD["entries"],
            {"kind": "transcript", "turn": 2, "text": "그만둘까요", "at": "2026-11-19T10:01:00Z"},
        ],
    }
    second = client.post("/api/sessions/save", json=more).json()

    assert second["id"] == first["id"]
    db = tmp_path / "manura.db"
    assert _rows(db, "SELECT COUNT(*) FROM sessions") == [(1,)]
    assert _rows(db, "SELECT COUNT(*) FROM session_entries") == [(4,)]


def test_save_keeps_record_when_summary_fails(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _use_llm(client, FailingLLM())

    body = client.post("/api/sessions/save", json=RECORD).json()

    assert body["summary"] is None
    assert "모델 오류" in body["summary_error"]
    assert _rows(tmp_path / "manura.db", "SELECT summary FROM sessions") == [(None,)]


def test_profile_only_save_skips_summary(tmp_path: Path) -> None:
    client = _client(tmp_path)
    llm = CapturingLLM()
    _use_llm(client, llm)
    body = client.post("/api/sessions/save", json={"profile": PROFILE, "entries": []}).json()
    assert body["summary"] is None
    assert llm.prompts == []


def test_save_rejects_bad_input(tmp_path: Path) -> None:
    client = _client(tmp_path)
    bad_entry = {"profile": {}, "entries": [{"kind": "hack", "text": "x", "at": "t"}]}
    assert client.post("/api/sessions/save", json=bad_entry).status_code == 422
    bad_id = {"id": "../../etc", "profile": {}, "entries": []}
    assert client.post("/api/sessions/save", json=bad_id).status_code == 422
