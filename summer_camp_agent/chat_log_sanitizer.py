from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit


PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])")
ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
BANK_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
URL_RE = re.compile(r"https?://[^\s，。；、)）]+")
MEDIA_ONLY_RE = re.compile(r"^\[[^\]]+\]$")


@dataclass(frozen=True)
class SanitizedMessage:
    source: str
    group_name: str
    group_id_hash: str
    message_time: str
    sender_alias: str
    sender_hash: str
    sender_role: str
    content: str
    matched_keywords: list[str]
    platform_message_id_hash: str
    raw_type: int | str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class AliasRegistry:
    def __init__(self) -> None:
        self._aliases: dict[str, str] = {}

    def alias_for(self, sender_id: str) -> str:
        key = sender_id or "unknown"
        if key not in self._aliases:
            self._aliases[key] = f"成员{len(self._aliases) + 1:03d}"
        return self._aliases[key]


def hash_identifier(value: str) -> str:
    normalized = value or "unknown"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def sanitize_content(content: str, max_chars: int = 2000) -> str:
    sanitized = str(content or "").strip()
    sanitized = EMAIL_RE.sub("[邮箱]", sanitized)
    sanitized = ID_CARD_RE.sub("[身份证]", sanitized)
    sanitized = PHONE_RE.sub("[手机号]", sanitized)
    sanitized = BANK_CARD_RE.sub("[银行卡号]", sanitized)
    sanitized = URL_RE.sub(_sanitize_url, sanitized)
    if len(sanitized) > max_chars:
        sanitized = sanitized[:max_chars].rstrip() + "..."
    return sanitized


def content_matches_keywords(content: str, keywords: list[str]) -> list[str]:
    if not keywords:
        return []
    hits: list[str] = []
    for keyword in keywords:
        normalized = keyword.strip()
        if normalized and normalized in content and normalized not in hits:
            hits.append(normalized)
    return hits


def build_sanitized_message(
    *,
    source: str,
    group_name: str,
    group_id: str,
    message_time: str,
    sender_id: str,
    content: str,
    keywords: list[str],
    platform_message_id: str,
    raw_type: int | str,
    alias_registry: AliasRegistry,
    include_media: bool = False,
) -> SanitizedMessage | None:
    sanitized_content = sanitize_content(content)
    if not sanitized_content:
        return None
    if MEDIA_ONLY_RE.match(sanitized_content) and not include_media:
        return None
    matched = content_matches_keywords(sanitized_content, keywords)
    if keywords and not matched:
        return None
    return SanitizedMessage(
        source=source,
        group_name=group_name,
        group_id_hash=hash_identifier(group_id),
        message_time=message_time,
        sender_alias=alias_registry.alias_for(sender_id),
        sender_hash=hash_identifier(sender_id),
        sender_role="unknown",
        content=sanitized_content,
        matched_keywords=matched,
        platform_message_id_hash=hash_identifier(platform_message_id),
        raw_type=raw_type,
    )


def _sanitize_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return "[链接]"
    return f"{parsed.scheme}://{parsed.netloc}"
