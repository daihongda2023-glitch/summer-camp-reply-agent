from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .gitlink_issue_transform import (
    GitLinkSource,
    extract_generated_qas,
    render_generated_qa,
    should_exclude_issue,
)


GITLINK_BASE_URL = "https://www.gitlink.org.cn/api/v1"


class GitLinkSyncError(RuntimeError):
    """GitLink Issue 同步失败，旧快照仍应保持可用。"""


@dataclass(frozen=True)
class GitLinkSyncSummary:
    fetched_issues: int
    generated_official: int
    generated_community: int
    skipped_by_reason: dict[str, int]
    errors: list[dict[str, str]]
    repositories: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


FetchJson = Callable[[str], object]


def sync_gitlink_issues(
    config_path: str | Path,
    output_directory: str | Path,
    report_path: str | Path,
    *,
    fetch_json: FetchJson | None = None,
) -> GitLinkSyncSummary:
    """抓取并转换配置中的 GitLink Issue，成功后原子替换本地快照。"""

    sources = _load_sources(Path(config_path))
    output = Path(output_directory).resolve()
    report = Path(report_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    fetch = fetch_json or _fetch_json

    fetched_issues = 0
    generated_official = 0
    generated_community = 0
    skipped: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    repositories: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="gitlink-sync-", dir=output.parent) as temporary:
        staging = Path(temporary) / "snapshot"
        staging.mkdir()

        for source in sources:
            repository_url = f"{GITLINK_BASE_URL}/{source.owner}/{source.repository}"
            try:
                issues = _paged_items(
                    f"{repository_url}/issues",
                    "issues",
                    fetch,
                    source.repository_name,
                )
            except GitLinkSyncError:
                raise

            repository_fetched = len(issues)
            repository_official = 0
            repository_community = 0
            repository_skipped: Counter[str] = Counter()
            fetched_issues += repository_fetched

            for issue_summary in issues:
                issue_index = str(issue_summary.get("project_issues_index", "unknown"))
                issue_url = (
                    f"https://www.gitlink.org.cn/{source.owner}/"
                    f"{source.repository}/issues/{issue_index}"
                )
                try:
                    exclusion_reason = should_exclude_issue(issue_summary, source)
                    if exclusion_reason:
                        skipped[exclusion_reason] += 1
                        repository_skipped[exclusion_reason] += 1
                        continue

                    detail = _fetch_with_context(
                        f"{repository_url}/issues/{issue_index}",
                        fetch,
                        source.repository_name,
                    )
                    if not isinstance(detail, dict):
                        raise TypeError("Issue 详情不是 JSON 对象")
                    comments = _paged_items(
                        f"{repository_url}/issues/{issue_index}/journals",
                        "journals",
                        fetch,
                        source.repository_name,
                    )
                    qas = extract_generated_qas(detail, comments, source)
                    if not qas:
                        skipped["no_usable_answer"] += 1
                        repository_skipped["no_usable_answer"] += 1
                        continue

                    repository_output = staging / source.owner / source.repository
                    repository_output.mkdir(parents=True, exist_ok=True)
                    for qa in qas:
                        (repository_output / qa.filename).write_text(
                            render_generated_qa(qa),
                            encoding="utf-8",
                        )
                        if qa.trust_level == "official":
                            generated_official += 1
                            repository_official += 1
                        else:
                            generated_community += 1
                            repository_community += 1
                except GitLinkSyncError:
                    raise
                except (KeyError, TypeError, ValueError) as error:
                    errors.append(
                        {
                            "repository": source.repository_name,
                            "issue_url": issue_url,
                            "error": str(error),
                        }
                    )
                    skipped["malformed_issue"] += 1
                    repository_skipped["malformed_issue"] += 1

            repositories.append(
                {
                    "repository": source.repository_name,
                    "fetched_issues": repository_fetched,
                    "generated_official": repository_official,
                    "generated_community": repository_community,
                    "skipped_by_reason": dict(sorted(repository_skipped.items())),
                }
            )

        if generated_official + generated_community == 0:
            raise GitLinkSyncError("同步未生成任何可用问答，已保留上次成功快照")

        summary = GitLinkSyncSummary(
            fetched_issues=fetched_issues,
            generated_official=generated_official,
            generated_community=generated_community,
            skipped_by_reason=dict(sorted(skipped.items())),
            errors=errors,
            repositories=repositories,
        )
        _replace_directory(staging, output)
        _write_report(report, summary)
        return summary


def _load_sources(config_path: Path) -> list[GitLinkSource]:
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GitLinkSyncError(f"无法读取同步配置 {config_path}: {error}") from error

    if raw.get("schema_version") != 1 or not isinstance(raw.get("repositories"), list):
        raise GitLinkSyncError("GitLink 同步配置格式无效")

    sources: list[GitLinkSource] = []
    try:
        for item in raw["repositories"]:
            sources.append(
                GitLinkSource(
                    owner=str(item["owner"]),
                    repository=str(item["repository"]),
                    excluded_labels=tuple(str(value) for value in item.get("excluded_labels", [])),
                    excluded_title_patterns=tuple(
                        str(value) for value in item.get("excluded_title_patterns", [])
                    ),
                    trusted_authors=tuple(str(value) for value in item.get("trusted_authors", [])),
                )
            )
    except (KeyError, TypeError) as error:
        raise GitLinkSyncError(f"GitLink 同步配置字段无效: {error}") from error
    if not sources:
        raise GitLinkSyncError("GitLink 同步配置中没有仓库")
    return sources


def _fetch_json(url: str) -> object:
    request = Request(url, headers={"User-Agent": "summer-camp-reply-agent/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GitLinkSyncError(f"请求 GitLink 失败：{url}（{error}）") from error


def _fetch_with_context(url: str, fetch: FetchJson, repository: str) -> object:
    try:
        return fetch(url)
    except GitLinkSyncError as error:
        raise GitLinkSyncError(f"同步 {repository} 失败：{error}") from error
    except (OSError, TimeoutError, ValueError) as error:
        raise GitLinkSyncError(f"同步 {repository} 失败：{url}（{error}）") from error


def _paged_items(
    base_url: str,
    key: str,
    fetch: FetchJson,
    repository: str,
    *,
    limit: int = 100,
) -> list[dict]:
    page = 1
    items: list[dict] = []
    while True:
        payload = _fetch_with_context(
            f"{base_url}?page={page}&limit={limit}",
            fetch,
            repository,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
            raise GitLinkSyncError(
                f"同步 {repository} 失败：分页响应缺少列表字段 {key}"
            )
        page_items = payload[key]
        items.extend(page_items)
        total = payload.get("total_count")
        if isinstance(total, int):
            if len(items) >= total:
                break
        elif len(page_items) < limit:
            break
        if not page_items:
            raise GitLinkSyncError(
                f"同步 {repository} 失败：分页结果在达到 total_count 前为空"
            )
        page += 1
    return items


def _replace_directory(staging: Path, output: Path) -> None:
    backup = output.with_name(f"{output.name}.previous-{uuid4().hex}")
    had_previous = output.exists()
    try:
        if had_previous:
            os.replace(output, backup)
        os.replace(staging, output)
    except OSError as error:
        if had_previous and backup.exists() and not output.exists():
            os.replace(backup, output)
        raise GitLinkSyncError(f"替换 RAG 快照失败，已尝试恢复旧快照：{error}") from error
    if backup.exists():
        shutil.rmtree(backup)


def _write_report(report_path: Path, summary: GitLinkSyncSummary) -> None:
    payload = {
        "schema_version": 1,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        **summary.to_dict(),
    }
    temporary = report_path.with_name(f"{report_path.name}.tmp-{uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, report_path)
    except OSError as error:
        if temporary.exists():
            temporary.unlink()
        raise GitLinkSyncError(f"写入同步报告失败：{error}") from error
