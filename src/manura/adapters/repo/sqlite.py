"""상담 기록 SQLite 저장소 (data/manura.db — 로컬 전용, git 제외)."""

from pathlib import Path

import aiosqlite

from manura.domain.models import SessionRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,      -- 처음 저장한 시각 (서버 기준)
    saved_at    TEXT NOT NULL,      -- 마지막으로 저장한 시각
    started_at  TEXT,               -- 상담 시작 시각 (브라우저 기준)
    name        TEXT NOT NULL DEFAULT '',
    age         TEXT NOT NULL DEFAULT '',
    gender      TEXT NOT NULL DEFAULT '',
    traits      TEXT NOT NULL DEFAULT '',
    concern     TEXT NOT NULL DEFAULT '',
    summary     TEXT                -- LLM이 만든 최종 세션 정리 (실패 시 NULL)
);
CREATE TABLE IF NOT EXISTS session_entries (
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    kind        TEXT NOT NULL,      -- transcript | advice | note
    turn        INTEGER,
    text        TEXT NOT NULL,
    at          TEXT NOT NULL,
    PRIMARY KEY (session_id, seq)
);
"""

_UPSERT_SESSION = """
INSERT INTO sessions
    (id, created_at, saved_at, started_at, name, age, gender, traits, concern, summary)
VALUES (:id, :saved_at, :saved_at, :started_at, :name, :age, :gender, :traits, :concern, :summary)
ON CONFLICT(id) DO UPDATE SET
    saved_at = excluded.saved_at,
    started_at = excluded.started_at,
    name = excluded.name,
    age = excluded.age,
    gender = excluded.gender,
    traits = excluded.traits,
    concern = excluded.concern,
    summary = excluded.summary
"""


class SqliteSessionArchive:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def save(
        self, record_id: str, record: SessionRecord, summary: str | None, saved_at: str
    ) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.executescript(_SCHEMA)
            await db.execute(
                _UPSERT_SESSION,
                {
                    "id": record_id,
                    "saved_at": saved_at,
                    "started_at": record.started_at,
                    "summary": summary,
                    **record.profile.model_dump(),
                },
            )
            # 재저장 시 대화는 통째로 교체한다 (브라우저가 전체 기록을 다시 보낸다)
            await db.execute("DELETE FROM session_entries WHERE session_id = ?", (record_id,))
            await db.executemany(
                "INSERT INTO session_entries (session_id, seq, kind, turn, text, at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (record_id, seq, e.kind, e.turn, e.text, e.at)
                    for seq, e in enumerate(record.entries)
                ],
            )
            await db.commit()
