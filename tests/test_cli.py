import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from summer_camp_agent.cli import main
from summer_camp_agent.gitlink_issue_sync import GitLinkSyncSummary


class CLITest(unittest.TestCase):
    def test_sync_gitlink_command_reports_generated_documents(self):
        summary = GitLinkSyncSummary(
            fetched_issues=36,
            generated_official=8,
            generated_community=2,
            skipped_by_reason={"excluded_label:任务": 2},
            errors=[],
            repositories=[],
        )
        output = StringIO()

        with patch("summer_camp_agent.cli.sync_gitlink_issues", return_value=summary) as sync:
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "sync-gitlink",
                        "--config",
                        "sources.json",
                        "--documents",
                        "documents",
                        "--report",
                        "report.json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        sync.assert_called_once_with("sources.json", "documents", "report.json")
        self.assertIn("fetched_issues: 36", output.getvalue())
        self.assertIn("generated_official: 8", output.getvalue())
        self.assertIn("generated_community: 2", output.getvalue())

    def test_ask_command_returns_answer_payload(self):
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "summer_camp_agent.cli", "ask", "报名入口在哪里？"],
            check=True,
            capture_output=True,
            encoding="utf-8",
        )

        self.assertIn("action: auto_reply", completed.stdout)
        self.assertIn("intent: registration.link", completed.stdout)
        self.assertIn("https://developer.metax-tech.com/activities/18", completed.stdout)
        self.assertNotIn("v.wjx.cn", completed.stdout)
        self.assertIn("source: 官方咨询群海报", completed.stdout)

    def test_validate_command_accepts_default_knowledge_base(self):
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "summer_camp_agent.cli", "validate"],
            check=True,
            capture_output=True,
            encoding="utf-8",
        )

        self.assertIn("知识库校验通过", completed.stdout)

    def test_validate_script_accepts_default_knowledge_base(self):
        completed = subprocess.run(
            [sys.executable, "-B", "scripts/validate_knowledge.py", "data/faq.json"],
            check=True,
            capture_output=True,
            encoding="utf-8",
        )

        self.assertIn("知识库校验通过", completed.stdout)

    def test_review_command_outputs_operator_card(self):
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "summer_camp_agent.cli", "review", "报名入口在哪里？"],
            check=True,
            capture_output=True,
            encoding="utf-8",
        )

        self.assertIn("recommendation: send", completed.stdout)
        self.assertIn("available_actions: send, edit, escalate, mark_pending", completed.stdout)
        self.assertIn("source: 官方咨询群海报", completed.stdout)

    def test_review_command_can_save_pending_question(self):
        with tempfile.TemporaryDirectory() as directory:
            pending_path = f"{directory}/pending.jsonl"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "summer_camp_agent.cli",
                    "review",
                    "营服是什么颜色？",
                    "--pending-log",
                    pending_path,
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
            )

            self.assertIn("recommendation: mark_pending", completed.stdout)
            self.assertIn("pending_saved: true", completed.stdout)

    def test_import_weflow_requires_token_environment_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            empty_config = os.path.join(directory, "WeFlow-config.json")
            with open(empty_config, "w", encoding="utf-8") as handle:
                handle.write('{"httpApiToken": ""}')
            env = dict(os.environ)
            env.pop("WEFLOW_API_TOKEN", None)
            env["WEFLOW_CONFIG_PATH"] = empty_config
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "summer_camp_agent.cli",
                    "import-weflow",
                    "--group",
                    "测试群",
                    "--keywords",
                    "报名,住宿",
                ],
                capture_output=True,
                encoding="utf-8",
                env=env,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("缺少 WEFLOW_API_TOKEN", completed.stderr)

    def test_rag_index_requires_openai_api_key_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            documents = f"{directory}/documents"
            os.makedirs(documents)
            with open(f"{documents}/notice.md", "w", encoding="utf-8") as handle:
                handle.write("# 通知\n\n报名截止到 2026 年 7 月 15 日。")
            env = dict(os.environ)
            env.pop("OPENAI_API_KEY", None)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "summer_camp_agent.cli",
                    "rag-index",
                    "--documents",
                    documents,
                    "--index",
                    f"{directory}/index",
                ],
                capture_output=True,
                encoding="utf-8",
                env=env,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("缺少 OPENAI_API_KEY", completed.stderr)

    def test_rag_index_and_search_can_use_static_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            documents = f"{directory}/documents"
            index = f"{directory}/index"
            os.makedirs(documents)
            with open(f"{documents}/handbook.md", "w", encoding="utf-8") as handle:
                handle.write("# 线下手册\n\n## 住宿安排\n\n活动期间住宿由主办方统一安排。")

            index_completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "summer_camp_agent.cli",
                    "rag-index",
                    "--documents",
                    documents,
                    "--index",
                    index,
                    "--provider",
                    "static",
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
            )
            search_completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "summer_camp_agent.cli",
                    "rag-search",
                    "住宿怎么安排？",
                    "--index",
                    index,
                    "--provider",
                    "static",
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
            )

        self.assertIn("chunk_count: 1", index_completed.stdout)
        self.assertIn("score:", search_completed.stdout)
        self.assertIn("source: 线下手册", search_completed.stdout)
        self.assertIn("活动期间住宿由主办方统一安排", search_completed.stdout)

    def test_ask_can_use_rag_index_when_faq_misses(self):
        with tempfile.TemporaryDirectory() as directory:
            documents = f"{directory}/documents"
            index = f"{directory}/index"
            os.makedirs(documents)
            with open(f"{documents}/materials.md", "w", encoding="utf-8") as handle:
                handle.write("# 物料通知\n\n## 营服\n\n营服颜色为蓝色。")
            subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "summer_camp_agent.cli",
                    "rag-index",
                    "--documents",
                    documents,
                    "--index",
                    index,
                    "--provider",
                    "static",
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "summer_camp_agent.cli",
                    "ask",
                    "营服是什么颜色？",
                    "--rag-index",
                    index,
                    "--rag-provider",
                    "static",
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
            )

        self.assertIn("action: auto_reply", completed.stdout)
        self.assertIn("intent: rag.document", completed.stdout)
        self.assertIn("source: 物料通知", completed.stdout)
        self.assertIn("营服颜色为蓝色", completed.stdout)


if __name__ == "__main__":
    unittest.main()
