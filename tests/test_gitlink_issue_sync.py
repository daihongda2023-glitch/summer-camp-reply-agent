import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.gitlink_issue_sync import GitLinkSyncError, sync_gitlink_issues


class GitLinkIssueSyncTest(unittest.TestCase):
    def _write_config(self, root: Path) -> Path:
        path = root / "sources.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "repositories": [
                        {
                            "owner": "example",
                            "repository": "course",
                            "excluded_labels": ["任务"],
                            "excluded_title_patterns": ["任务", "打卡"],
                            "trusted_authors": ["organizer"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_successful_sync_paginates_filters_task_and_replaces_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            output = root / "documents"
            output.mkdir()
            (output / "stale.md").write_text("# 旧快照\n", encoding="utf-8")
            report = root / "report.json"

            def fetch_json(url: str):
                if url.endswith("/issues?page=1&limit=100"):
                    return {
                        "total_count": 2,
                        "issues": [
                            {"project_issues_index": 12, "subject": "课程任务", "tags": [{"name": "任务"}]},
                        ],
                    }
                if url.endswith("/issues?page=2&limit=100"):
                    return {
                        "total_count": 2,
                        "issues": [
                            {"project_issues_index": 13, "subject": "不同语言是否一起比较？", "tags": []},
                        ],
                    }
                if url.endswith("/issues/13"):
                    return {
                        "project_issues_index": 13,
                        "subject": "不同语言是否一起比较？",
                        "description": "是否分榜？",
                        "updated_at": "2026-07-06 16:00",
                        "tags": [],
                    }
                if url.endswith("/issues/13/journals?page=1&limit=100"):
                    return {
                        "total_count": 1,
                        "journals": [
                            {"user": {"login": "organizer"}, "notes": "同一 Track 不按语言分别设榜。"}
                        ],
                    }
                raise AssertionError(url)

            summary = sync_gitlink_issues(config, output, report, fetch_json=fetch_json)

            generated = list(output.rglob("*.md"))
            saved_report = json.loads(report.read_text(encoding="utf-8"))
            rendered = generated[0].read_text(encoding="utf-8")
            generated_names = [path.name for path in generated]
            stale_exists = (output / "stale.md").exists()

        self.assertEqual(summary.fetched_issues, 2)
        self.assertEqual(summary.generated_official, 1)
        self.assertEqual(len(generated), 1)
        self.assertFalse(stale_exists)
        self.assertTrue(all("issue-12" not in name for name in generated_names))
        self.assertIn("不按语言分别设榜", rendered)
        self.assertEqual(saved_report["generated_official"], 1)
        self.assertEqual(saved_report["repositories"][0]["fetched_issues"], 2)
        self.assertEqual(saved_report["skipped_by_reason"]["excluded_label:任务"], 1)

    def test_fetch_failure_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            output = root / "documents"
            output.mkdir()
            previous = output / "previous.md"
            previous.write_text("# 上次成功快照\n", encoding="utf-8")

            def failing_fetch_json(url: str):
                raise OSError("network down")

            with self.assertRaisesRegex(GitLinkSyncError, "example/course"):
                sync_gitlink_issues(config, output, root / "report.json", fetch_json=failing_fetch_json)

            self.assertTrue(previous.exists())
            self.assertEqual(previous.read_text(encoding="utf-8"), "# 上次成功快照\n")

    def test_single_malformed_issue_is_reported_without_blocking_valid_issue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            output = root / "documents"
            report = root / "report.json"

            def fetch_json(url: str):
                if url.endswith("/issues?page=1&limit=100"):
                    return {
                        "total_count": 2,
                        "issues": [
                            {"project_issues_index": 13, "subject": "正常问题？", "tags": []},
                            {"project_issues_index": 14, "subject": "格式异常问题？", "tags": []},
                        ],
                    }
                if url.endswith("/issues/13"):
                    return {
                        "project_issues_index": 13,
                        "subject": "正常问题？",
                        "description": "",
                        "updated_at": "2026-07-06 16:00",
                        "tags": [],
                    }
                if url.endswith("/issues/13/journals?page=1&limit=100"):
                    return {
                        "total_count": 1,
                        "journals": [{"user": {"login": "organizer"}, "notes": "这是明确答复。"}],
                    }
                if url.endswith("/issues/14"):
                    return {"subject": "缺少 Issue 编号", "tags": []}
                if url.endswith("/issues/14/journals?page=1&limit=100"):
                    return {
                        "total_count": 1,
                        "journals": [{"user": {"login": "organizer"}, "notes": "答复。"}],
                    }
                raise AssertionError(url)

            summary = sync_gitlink_issues(config, output, report, fetch_json=fetch_json)
            generated_count = len(list(output.rglob("*.md")))

        self.assertEqual(summary.generated_official, 1)
        self.assertEqual(len(summary.errors), 1)
        self.assertIn("issues/14", summary.errors[0]["issue_url"])
        self.assertEqual(generated_count, 1)


if __name__ == "__main__":
    unittest.main()
