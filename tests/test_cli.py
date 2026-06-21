import os
import subprocess
import sys
import tempfile
import unittest


class CLITest(unittest.TestCase):
    def test_ask_command_returns_answer_payload(self):
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "summer_camp_agent.cli", "ask", "报名入口在哪里？"],
            check=True,
            capture_output=True,
            encoding="utf-8",
        )

        self.assertIn("action: auto_reply", completed.stdout)
        self.assertIn("intent: registration.link", completed.stdout)
        self.assertIn("https://v.wjx.cn/vm/r9BqUzR.aspx#", completed.stdout)
        self.assertIn("source: 招募文章", completed.stdout)

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
        self.assertIn("source: 招募文章", completed.stdout)

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
        env = dict(os.environ)
        env.pop("WEFLOW_API_TOKEN", None)
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


if __name__ == "__main__":
    unittest.main()
