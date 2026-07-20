from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GitLinkSource:
    owner: str
    repository: str
    excluded_labels: tuple[str, ...]
    excluded_title_patterns: tuple[str, ...]
    trusted_authors: tuple[str, ...]

    @property
    def repository_name(self) -> str:
        return f"{self.owner}/{self.repository}"


@dataclass(frozen=True)
class GeneratedQA:
    question: str
    answer: str
    trust_level: str
    source_url: str
    source_updated_at: str
    repository: str
    issue_index: str
    answer_author: str
    filename: str


def should_exclude_issue(issue: dict, source: GitLinkSource) -> str | None:
    labels = {str(tag.get("name", "")).strip() for tag in issue.get("tags", [])}
    for label in source.excluded_labels:
        if label in labels:
            return f"excluded_label:{label}"

    subject = str(issue.get("subject", "")).strip()
    for pattern in source.excluded_title_patterns:
        match = re.search(pattern, subject, flags=re.IGNORECASE)
        if match:
            return f"excluded_title:{match.group(0)}"
    return None


def extract_generated_qas(issue: dict, comments: list[dict], source: GitLinkSource) -> list[GeneratedQA]:
    if should_exclude_issue(issue, source):
        return []

    subject = str(issue.get("subject", "")).strip()
    description = str(issue.get("description", "")).strip()
    if "FAQ" in subject.upper():
        return _extract_faq_table(issue, description, source)

    official_comments = [
        comment
        for comment in comments
        if _comment_author(comment) in source.trusted_authors
        and _is_conclusive(str(comment.get("notes", "")))
    ]
    if official_comments:
        answer = sanitize_answer("\n\n".join(str(comment["notes"]) for comment in official_comments))
        if not answer:
            return []
        return [
            _make_qa(
                issue,
                source,
                subject,
                answer,
                "official",
                _comment_author(official_comments[-1]),
                "",
            )
        ]

    community_qas: list[GeneratedQA] = []
    for sequence, comment in enumerate(comments, start=1):
        notes = str(comment.get("notes", ""))
        if "已解决" not in notes or _looks_like_submission(notes):
            continue
        question = _first_markdown_heading(notes) or subject
        answer = sanitize_answer(_without_first_heading(notes))
        if answer:
            community_qas.append(
                _make_qa(
                    issue,
                    source,
                    question,
                    answer,
                    "community",
                    _comment_author(comment),
                    f"-community-{sequence:02d}",
                )
            )
    return community_qas


def sanitize_answer(text: str) -> str:
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    cleaned = re.sub(r"<img\b[^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*用户名\s*[:：].*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(
        r"^\s*issue区打卡提交记录截图\s*[:：]?.*$",
        "",
        cleaned,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def render_generated_qa(qa: GeneratedQA) -> str:
    return (
        "---\n"
        "source_type: gitlink_issue\n"
        f"trust_level: {qa.trust_level}\n"
        f"source_url: {qa.source_url}\n"
        f'source_updated_at: "{qa.source_updated_at}"\n'
        f"repository: {qa.repository}\n"
        f'issue_index: "{qa.issue_index}"\n'
        f"answer_author: {qa.answer_author}\n"
        "---\n"
        f"# {qa.question}\n\n"
        f"{qa.answer.strip()}\n"
    )


def _extract_faq_table(issue: dict, description: str, source: GitLinkSource) -> list[GeneratedQA]:
    rows = [
        _split_markdown_row(line)
        for line in description.splitlines()
        if line.strip().startswith("|")
    ]
    data_rows = [
        row
        for row in rows
        if len(row) >= 3 and row[0] != "问题" and not _is_separator_row(row)
    ]
    qas: list[GeneratedQA] = []
    for sequence, row in enumerate(data_rows, start=1):
        question = sanitize_answer(row[0])
        answer = sanitize_answer(
            re.sub(r"<br\s*/?>", "\n", row[2], flags=re.IGNORECASE)
        )
        if question and answer:
            qas.append(
                _make_qa(
                    issue,
                    source,
                    question,
                    answer,
                    "official",
                    str(issue.get("author", {}).get("login", "")),
                    f"-faq-{sequence:02d}",
                )
            )
    return qas


def _make_qa(
    issue: dict,
    source: GitLinkSource,
    question: str,
    answer: str,
    trust_level: str,
    answer_author: str,
    filename_suffix: str,
) -> GeneratedQA:
    index = str(issue["project_issues_index"])
    return GeneratedQA(
        question=question.strip(),
        answer=answer.strip(),
        trust_level=trust_level,
        source_url=f"https://www.gitlink.org.cn/{source.owner}/{source.repository}/issues/{index}",
        source_updated_at=str(issue.get("updated_at", "")),
        repository=source.repository_name,
        issue_index=index,
        answer_author=answer_author,
        filename=f"issue-{index}{filename_suffix}.md",
    )


def _comment_author(comment: dict) -> str:
    return str(comment.get("user", {}).get("login", "")).strip()


def _is_conclusive(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    pending_phrases = (
        "会认真排查",
        "有结果后",
        "后续同步",
        "正在整理",
        "待确认",
        "尽快修复",
    )
    return not any(phrase in normalized for phrase in pending_phrases)


def _looks_like_submission(text: str) -> bool:
    markers = ("作业提交", "打卡提交", "issue区打卡提交记录截图")
    return any(marker in text for marker in markers)


def _first_markdown_heading(text: str) -> str:
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+)$", line.strip())
        if match:
            return match.group(1).strip()
    return ""


def _without_first_heading(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#{1,6}\s+", line.strip()):
            return "\n".join(lines[index + 1 :]).strip()
    return text.strip()


def _split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def _is_separator_row(row: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in row)
