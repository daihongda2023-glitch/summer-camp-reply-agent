from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path


SUPPORTED_DOCUMENT_SUFFIXES = {".md", ".txt"}
SKIPPED_PATH_PARTS = (
    ("imports", "chat_logs"),
    ("data", "rag", "index"),
)


@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    source_path: str
    source_title: str
    source_sha256: str
    heading: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


def load_document_chunks(
    source_root: str | Path,
    target_chars: int = 800,
    overlap_chars: int = 100,
) -> list[DocumentChunk]:
    root = Path(source_root)
    if not root.exists():
        return []

    chunks: list[DocumentChunk] = []
    for path in _iter_document_files(root):
        raw_text = path.read_text(encoding="utf-8").strip()
        if not raw_text:
            continue
        source_sha256 = _sha256_text(raw_text)
        source_title = _source_title(path, raw_text)
        relative_path = path.relative_to(root).as_posix()
        sections = _markdown_sections(raw_text, source_title) if path.suffix.lower() == ".md" else [(source_title, raw_text)]
        for heading, section_text in sections:
            for part in split_text_into_chunks(section_text, target_chars=target_chars, overlap_chars=overlap_chars):
                chunk_text = _with_heading(heading, part)
                chunks.append(
                    DocumentChunk(
                        chunk_id=_chunk_id(relative_path, source_sha256, heading, chunk_text),
                        source_path=relative_path,
                        source_title=source_title,
                        source_sha256=source_sha256,
                        heading=heading,
                        text=chunk_text,
                    )
                )
    return chunks


def split_text_into_chunks(text: str, target_chars: int = 800, overlap_chars: int = 100) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    if target_chars <= 0:
        raise ValueError("target_chars must be positive")
    if overlap_chars < 0:
        raise ValueError("overlap_chars cannot be negative")
    if overlap_chars >= target_chars:
        raise ValueError("overlap_chars must be smaller than target_chars")
    if len(normalized) <= target_chars:
        return [normalized]

    chunks: list[str] = []
    step = target_chars - overlap_chars
    start = 0
    while start < len(normalized):
        chunk = normalized[start : start + target_chars].strip()
        if chunk:
            chunks.append(chunk)
        if start + target_chars >= len(normalized):
            break
        start += step
    return chunks


def _iter_document_files(root: Path) -> list[Path]:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_DOCUMENT_SUFFIXES
        and not _is_skipped_path(path, root)
    ]
    return sorted(files, key=lambda item: item.as_posix())


def _is_skipped_path(path: Path, root: Path) -> bool:
    parts = path.relative_to(root).parts
    for skipped in SKIPPED_PATH_PARTS:
        if _contains_subsequence(parts, skipped):
            return True
    return any(part.startswith(".") for part in parts)


def _contains_subsequence(parts: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if len(parts) < len(needle):
        return False
    return any(parts[index : index + len(needle)] == needle for index in range(len(parts) - len(needle) + 1))


def _source_title(path: Path, text: str) -> str:
    if path.suffix.lower() == ".md":
        for line in text.splitlines():
            match = re.match(r"^#\s+(.+)$", line.strip())
            if match:
                return match.group(1).strip()
    return path.stem


def _markdown_sections(text: str, source_title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading_stack: list[str] = [source_title]
    body_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(line for line in body_lines).strip()
        if body:
            sections.append((" > ".join(heading_stack), body))
        body_lines.clear()

    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if not match:
            body_lines.append(line)
            continue

        flush()
        level = len(match.group(1))
        title = match.group(2).strip()
        if level == 1:
            heading_stack = [title]
        else:
            heading_stack = heading_stack[:level - 1]
            heading_stack.append(title)
    flush()
    return sections


def _with_heading(heading: str, text: str) -> str:
    if text.startswith(heading):
        return text
    return f"{heading}\n{text}"


def _chunk_id(source_path: str, source_sha256: str, heading: str, text: str) -> str:
    return "sha256:" + _sha256_text(f"{source_path}\n{source_sha256}\n{heading}\n{text}")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
