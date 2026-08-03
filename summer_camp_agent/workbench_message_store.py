from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from .review import ReviewCard
from .workbench_models import (
    MATCH_STATUSES,
    REVIEW_STATUSES,
    ChatEvent,
    ReplyDecision,
    StoredWorkbenchMessage,
    TriggerDecision,
)
from .workbench_session import WorkbenchItem


class WorkbenchMessageStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = RLock()
        self._initialize()

    def insert_pending(
        self,
        item: WorkbenchItem,
        match_status: str,
        unmatched_reasons: list[str],
    ) -> bool:
        event_id = item.event.event_id.strip()
        if not event_id:
            raise ValueError("event_id 不能为空")
        self._validate_match_status(match_status)
        now = _utc_now()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO workbench_messages (
                    event_id,
                    review_status,
                    match_status,
                    unmatched_reasons_json,
                    item_snapshot_json,
                    created_at,
                    updated_at
                ) VALUES (?, 'pending_review', ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    match_status,
                    json.dumps(unmatched_reasons, ensure_ascii=False),
                    _encode_item(item),
                    now,
                    now,
                ),
            )
            return cursor.rowcount == 1

    def get(self, event_id: str) -> StoredWorkbenchMessage | None:
        value = event_id.strip()
        if not value:
            return None
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM workbench_messages WHERE event_id = ?",
                (value,),
            ).fetchone()
        return _decode_row(row) if row is not None else None

    def list_pending(self) -> list[StoredWorkbenchMessage]:
        return self.list_all(review_status="pending_review")

    def list_all(
        self,
        review_status: str | None = None,
    ) -> list[StoredWorkbenchMessage]:
        if review_status:
            self._validate_review_status(review_status)
            sql = (
                "SELECT * FROM workbench_messages "
                "WHERE review_status = ? ORDER BY created_at ASC"
            )
            parameters: tuple[str, ...] = (review_status,)
        else:
            sql = "SELECT * FROM workbench_messages ORDER BY created_at ASC"
            parameters = ()
        with self._lock, self._connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [_decode_row(row) for row in rows]

    def complete(
        self,
        event_id: str,
        review_status: str,
        review_action: str,
        review_note: str,
    ) -> StoredWorkbenchMessage:
        value = event_id.strip()
        if not value:
            raise ValueError("event_id 不能为空")
        self._validate_review_status(review_status)
        if review_status == "pending_review":
            raise ValueError("review_status 必须是完成状态")
        now = _utc_now()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE workbench_messages
                SET review_status = ?,
                    review_action = ?,
                    review_note = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE event_id = ? AND review_status = 'pending_review'
                """,
                (
                    review_status,
                    review_action.strip(),
                    review_note.strip(),
                    now,
                    now,
                    value,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("消息不存在或已处理")
            row = connection.execute(
                "SELECT * FROM workbench_messages WHERE event_id = ?",
                (value,),
            ).fetchone()
        assert row is not None
        return _decode_row(row)

    def get_metadata(self, key: str) -> str:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM workbench_metadata WHERE key = ?",
                (key.strip(),),
            ).fetchone()
        return str(row["value"]) if row is not None else ""

    def set_metadata(self, key: str, value: str) -> None:
        normalized_key = key.strip()
        if not normalized_key:
            raise ValueError("metadata key 不能为空")
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO workbench_metadata (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (normalized_key, value),
            )

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workbench_messages (
                    event_id TEXT PRIMARY KEY,
                    review_status TEXT NOT NULL,
                    match_status TEXT NOT NULL,
                    unmatched_reasons_json TEXT NOT NULL,
                    item_snapshot_json TEXT NOT NULL,
                    review_action TEXT NOT NULL DEFAULT '',
                    review_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_workbench_messages_review_status
                ON workbench_messages(review_status, created_at DESC);
                CREATE TABLE IF NOT EXISTS workbench_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _validate_review_status(review_status: str) -> None:
        if review_status not in REVIEW_STATUSES:
            raise ValueError(f"无效 review_status：{review_status}")

    @staticmethod
    def _validate_match_status(match_status: str) -> None:
        if match_status not in MATCH_STATUSES:
            raise ValueError(f"无效 match_status：{match_status}")


def _encode_item(item: WorkbenchItem) -> str:
    return json.dumps(
        {
            "event": asdict(item.event),
            "trigger": asdict(item.trigger),
            "review_card": asdict(item.review_card),
            "reply_decision": asdict(item.reply_decision),
        },
        ensure_ascii=False,
    )


def _decode_row(row: sqlite3.Row) -> StoredWorkbenchMessage:
    snapshot = json.loads(str(row["item_snapshot_json"]))
    item = WorkbenchItem(
        event=ChatEvent(**snapshot["event"]),
        trigger=TriggerDecision(**snapshot["trigger"]),
        review_card=ReviewCard(**snapshot["review_card"]),
        reply_decision=ReplyDecision(**snapshot["reply_decision"]),
    )
    return StoredWorkbenchMessage(
        message_id=str(row["event_id"]),
        item=item,
        review_status=str(row["review_status"]),
        match_status=str(row["match_status"]),
        unmatched_reasons=[
            str(value)
            for value in json.loads(str(row["unmatched_reasons_json"]))
        ],
        review_action=str(row["review_action"]),
        review_note=str(row["review_note"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        completed_at=str(row["completed_at"]),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
