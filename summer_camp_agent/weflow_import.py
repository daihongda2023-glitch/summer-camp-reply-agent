from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen as default_urlopen

from .chat_log_sanitizer import AliasRegistry, build_sanitized_message, hash_identifier


class WeFlowImportError(RuntimeError):
    pass


class WeFlowAuthError(WeFlowImportError):
    pass


class WeFlowHttpError(WeFlowImportError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


class WeFlowSessionNotFoundError(WeFlowImportError):
    pass


class WeFlowSessionSelectionRequired(WeFlowImportError):
    def __init__(self, sessions: list["WeFlowSession"]):
        self.sessions = sessions
        super().__init__("找到多个匹配群聊，请使用 --session-id 明确指定。")


@dataclass(frozen=True)
class WeFlowSession:
    id: str
    name: str
    type: str
    last_message_at: int = 0
    message_count: int = 0


@dataclass(frozen=True)
class WeFlowImportConfig:
    group_name: str
    keywords: list[str]
    start: str = ""
    end: str = ""
    limit: int = 5000
    output_dir: Path = Path("imports/chat_logs")
    base_url: str = "http://127.0.0.1:5031"
    token_env: str = "WEFLOW_API_TOKEN"
    session_id: str = ""
    include_media: bool = False


@dataclass(frozen=True)
class WeFlowImportSummary:
    output_path: Path
    session_id_hash: str
    group_name: str
    pulled_count: int
    written_count: int
    skipped_count: int


class WeFlowImportClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        urlopen: Callable[..., Any] = default_urlopen,
        timeout_seconds: int = 10,
    ):
        self.base_url = _validate_local_base_url(base_url)
        self.token = token
        self._urlopen = urlopen
        self.timeout_seconds = timeout_seconds

    def search_sessions(self, keyword: str) -> list[WeFlowSession]:
        payload = self._get_json("/api/v1/sessions", {"format": "chatlab", "keyword": keyword, "limit": 100})
        raw_sessions = payload.get("sessions", [])
        sessions = []
        for raw in raw_sessions:
            if not isinstance(raw, dict):
                continue
            session = _session_from_chatlab(raw)
            if session.type == "group":
                sessions.append(session)
        return sessions

    def pull_messages(
        self,
        session_id: str,
        *,
        since: int | None,
        end: int | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        params: dict[str, object] = {"limit": min(max(limit, 1), 5000), "offset": max(offset, 0)}
        if since is not None:
            params["since"] = since
        if end is not None:
            params["end"] = end
        try:
            return self._get_json(f"/api/v1/sessions/{session_id}/messages", params)
        except WeFlowHttpError as exc:
            if exc.status_code != 404:
                raise
            legacy_params: dict[str, object] = {
                "talker": session_id,
                "limit": params["limit"],
                "offset": params["offset"],
                "chatlab": "1",
            }
            if since is not None:
                legacy_params["start"] = since
            if end is not None:
                legacy_params["end"] = end
            return self._get_json("/api/v1/messages", legacy_params)

    def _get_json(self, path: str, params: dict[str, object]) -> dict[str, Any]:
        query = urlencode(params)
        url = urljoin(self.base_url, path)
        if query:
            url = f"{url}?{query}"
        request = Request(url, headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
        try:
            with self._urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise WeFlowAuthError("WeFlow API 鉴权失败，请检查 WEFLOW_API_TOKEN。") from exc
            raise WeFlowHttpError(exc.code, f"WeFlow API 返回错误: HTTP {exc.code}") from exc
        except URLError as exc:
            raise WeFlowImportError("无法连接 WeFlow API，请确认 WeFlow 已启动并开启 API 服务。") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WeFlowImportError("WeFlow API 返回内容不是有效 JSON。") from exc
        if not isinstance(payload, dict):
            raise WeFlowImportError("WeFlow API 返回结构不是 JSON 对象。")
        return payload


def import_weflow_chat(
    config: WeFlowImportConfig,
    *,
    client: WeFlowImportClient | None = None,
    token: str | None = None,
) -> WeFlowImportSummary:
    token_value = token or os.environ.get(config.token_env, "")
    if not token_value:
        raise WeFlowAuthError(f"缺少 {config.token_env}，请先设置 WeFlow API Token 环境变量。")
    active_client = client or WeFlowImportClient(config.base_url, token_value)
    session = _select_session(active_client, config)
    output_path = _build_output_path(config.output_dir, config.group_name, config.start, config.end)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    since = _date_to_timestamp(config.start)
    end = _end_date_to_timestamp(config.end)
    alias_registry = AliasRegistry()
    seen_hashes: set[str] = set()
    pulled_count = 0
    written_count = 0
    offset = 0

    with output_path.open("w", encoding="utf-8") as handle:
        while True:
            payload = active_client.pull_messages(session.id, since=since, end=end, limit=config.limit, offset=offset)
            messages = payload.get("messages", [])
            if not isinstance(messages, list):
                raise WeFlowImportError("WeFlow API messages 字段不是列表。")
            pulled_count += len(messages)
            meta = payload.get("meta", {}) if isinstance(payload.get("meta", {}), dict) else {}
            group_id = str(meta.get("groupId") or session.id)
            for raw in messages:
                if not isinstance(raw, dict):
                    continue
                message = _sanitize_chatlab_message(raw, config, session.name, group_id, alias_registry)
                if message is None:
                    continue
                dedupe_key = message.platform_message_id_hash
                if dedupe_key in seen_hashes:
                    continue
                seen_hashes.add(dedupe_key)
                handle.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
                written_count += 1
            sync = payload.get("sync", {}) if isinstance(payload.get("sync", {}), dict) else {}
            if not sync.get("hasMore"):
                break
            offset = int(sync.get("nextOffset") or offset + len(messages))

    return WeFlowImportSummary(
        output_path=output_path,
        session_id_hash=hash_identifier(session.id),
        group_name=session.name,
        pulled_count=pulled_count,
        written_count=written_count,
        skipped_count=pulled_count - written_count,
    )


def _validate_local_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise WeFlowImportError("WeFlow base_url 只允许连接本机 127.0.0.1 或 localhost。")
    return base_url.rstrip("/") + "/"


def _session_from_chatlab(raw: dict[str, Any]) -> WeFlowSession:
    return WeFlowSession(
        id=str(raw.get("id") or raw.get("username") or ""),
        name=str(raw.get("name") or raw.get("displayName") or ""),
        type=str(raw.get("type") or ""),
        last_message_at=int(raw.get("lastMessageAt") or raw.get("lastTimestamp") or 0),
        message_count=int(raw.get("messageCount") or 0),
    )


def _select_session(client: WeFlowImportClient, config: WeFlowImportConfig) -> WeFlowSession:
    if config.session_id:
        return WeFlowSession(id=config.session_id, name=config.group_name or config.session_id, type="group")
    sessions = client.search_sessions(config.group_name)
    if not sessions:
        raise WeFlowSessionNotFoundError(f"没有找到匹配群聊：{config.group_name}")
    exact = [session for session in sessions if session.name == config.group_name]
    candidates = exact or sessions
    if len(candidates) > 1:
        raise WeFlowSessionSelectionRequired(candidates)
    return candidates[0]


def _sanitize_chatlab_message(
    raw: dict[str, Any],
    config: WeFlowImportConfig,
    group_name: str,
    group_id: str,
    alias_registry: AliasRegistry,
):
    timestamp = int(raw.get("timestamp") or 0)
    message_time = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else ""
    return build_sanitized_message(
        source="weflow_api",
        group_name=group_name,
        group_id=group_id,
        message_time=message_time,
        sender_id=str(raw.get("sender") or "unknown"),
        content=str(raw.get("content") or ""),
        keywords=config.keywords,
        platform_message_id=str(raw.get("platformMessageId") or raw.get("id") or timestamp),
        raw_type=raw.get("type", ""),
        alias_registry=alias_registry,
        include_media=config.include_media,
    )


def _date_to_timestamp(value: str) -> int | None:
    if not value:
        return None
    return int(datetime.strptime(value, "%Y%m%d").timestamp())


def _end_date_to_timestamp(value: str) -> int | None:
    if not value:
        return None
    end_date = datetime.strptime(value, "%Y%m%d") + timedelta(days=1)
    return int(end_date.timestamp())


def _build_output_path(output_dir: Path, group_name: str, start: str, end: str) -> Path:
    safe_group = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in group_name).strip("_") or "chatroom"
    date_part = "-".join(part for part in [start, end] if part) or datetime.now().strftime("%Y%m%d%H%M%S")
    candidate = output_dir / f"weflow-{safe_group}-{date_part}.jsonl"
    if not candidate.exists():
        return candidate
    suffix = datetime.now().strftime("%H%M%S")
    return output_dir / f"weflow-{safe_group}-{date_part}-{suffix}.jsonl"
