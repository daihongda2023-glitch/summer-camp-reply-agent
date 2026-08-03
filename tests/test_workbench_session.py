import tempfile
import unittest
import json
from pathlib import Path

from summer_camp_agent.rag_ai import RagGenerationResult
from summer_camp_agent.workbench_models import ChatEvent, GroupConfig
from summer_camp_agent.workbench_session import WorkbenchSession


class FakeRagAnswerGenerator:
    model = "fake-model"

    def __init__(self):
        self.questions = []

    def generate(self, question, rag_result):
        self.questions.append(question)
        return RagGenerationResult(
            "generated",
            answer="AI 整理后的比赛镜像下载说明。",
            model=self.model,
        )


class WorkbenchSessionTest(unittest.TestCase):
    def test_session_passes_injected_semantic_analyzer_to_default_engine(self):
        analyzer = object()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群"),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                semantic_analyzer=analyzer,
            )

        self.assertIs(session.review.engine.semantic_analyzer, analyzer)

    def test_session_passes_injected_generator_to_default_engine(self):
        generator = FakeRagAnswerGenerator()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(
                    group_name="夏令营咨询群",
                    mode="auto",
                    keywords=["比赛"],
                ),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                trace_path=root / "trace.jsonl",
                rag_answer_generator=generator,
            )
            event = ChatEvent(
                "evt-rag-ai",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-07-23 10:00:00",
                "请问能否公开下载比赛镜像？",
                "text",
                "weflow_live",
            )

            item = session.process_event(event)
            session.confirm_reply(item, item.review_card.reply)
            log_row = json.loads(
                (root / "logs.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            trace_rows = [
                json.loads(line)
                for line in (root / "trace.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]

        self.assertEqual(item.review_card.reply, "AI 整理后的比赛镜像下载说明。")
        self.assertEqual(item.review_card.generation_mode, "rag_ai")
        self.assertEqual(item.review_card.generation_model, "fake-model")
        self.assertEqual(generator.questions, ["请问能否公开下载比赛镜像？"])
        self.assertEqual(log_row["generation_mode"], "rag_ai")
        self.assertEqual(log_row["generation_model"], "fake-model")
        think_row = next(row for row in trace_rows if row["phase"] == "think")
        self.assertEqual(think_row["details"]["generation_mode"], "rag_ai")

    def test_default_session_retrieves_official_gitlink_answer_for_image_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="auto", keywords=["比赛"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-rag-image",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-07-21 10:00:00",
                "请问能否公开下载比赛镜像？",
                "text",
                "weflow_live",
            )

            item = session.process_event(event)

        self.assertEqual(item.review_card.action, "auto_reply")
        self.assertEqual(item.review_card.intent, "rag.document")
        self.assertEqual(item.reply_decision.mode, "auto_send")
        self.assertIn("https://developer.metax-tech.com/", item.review_card.reply)
        self.assertIn("gitlink.org.cn/metax-maca/op_optimization/issues/19", item.review_card.source)

    def test_process_event_creates_draft_for_triggered_question(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-1",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-06-21 10:00:00",
                "报名入口在哪里？",
                "text",
                "manual",
            )

            item = session.process_event(event)

        self.assertTrue(item.trigger.should_process)
        self.assertEqual(item.reply_decision.mode, "draft")
        self.assertIn("报名已于 2026 年 7 月 15 日截止", item.review_card.reply)
        self.assertIn("https://developer.metax-tech.com/activities/18", item.review_card.reply)

    def test_untriggered_event_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-2",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-06-21 10:00:00",
                "收到，谢谢老师",
                "text",
                "manual",
            )

            item = session.process_event(event)

        self.assertFalse(item.trigger.should_process)
        self.assertEqual(item.reply_decision.mode, "ignored")

    def test_auto_mode_analyzes_untriggered_event_and_sends_faq_hit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(
                    group_name="夏令营咨询群",
                    mode="auto",
                    keywords=["报名"],
                ),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-auto-untriggered-faq",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-07-29 10:00:00",
                "线下地点",
                "text",
                "weflow_live",
            )

            item = session.process_event(event)

        self.assertFalse(item.trigger.should_process)
        self.assertEqual(item.review_card.generation_mode, "faq")
        self.assertEqual(item.reply_decision.mode, "auto_send")

    def test_auto_mode_analyzes_untriggered_event_and_marks_both_misses_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(
                    group_name="夏令营咨询群",
                    mode="auto",
                    keywords=["报名"],
                ),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-auto-untriggered-miss",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-07-29 10:01:00",
                "今天天气不错",
                "text",
                "weflow_live",
            )

            item = session.process_event(event)

        self.assertFalse(item.trigger.should_process)
        self.assertEqual(item.review_card.action, "needs_info")
        self.assertEqual(item.reply_decision.mode, "mark_pending")

    def test_debug_review_mode_generates_review_card_for_unmatched_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(
                    group_name="夏令营咨询群",
                    mode="auto",
                    keywords=["报名"],
                ),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-debug-unmatched",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-07-25 10:00:00",
                "今天天气不错",
                "text",
                "weflow_live",
            )

            item = session.process_event(event, debug_review_mode=True)

        self.assertFalse(item.trigger.should_process)
        self.assertNotEqual(item.review_card.action, "ignored")
        self.assertEqual(item.reply_decision.mode, "draft")
        self.assertTrue(item.reply_decision.requires_review)

    def test_debug_review_mode_never_auto_sends_high_confidence_faq(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(
                    group_name="夏令营咨询群",
                    mode="auto",
                    keywords=["报名"],
                ),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-debug-faq",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-07-25 10:05:00",
                "报名入口在哪里？",
                "text",
                "weflow_live",
            )

            item = session.process_event(event, debug_review_mode=True)

        self.assertTrue(item.trigger.should_process)
        self.assertEqual(item.review_card.action, "auto_reply")
        self.assertEqual(item.reply_decision.mode, "draft")
        self.assertTrue(item.reply_decision.requires_review)

    def test_send_edited_reply_saves_candidate_and_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-1",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-06-21 10:00:00",
                "报名入口在哪里？",
                "text",
                "manual",
            )
            item = session.process_event(event)

            session.confirm_reply(item, edited_reply="同学你好，报名入口请看官方链接。")

            self.assertIn("官方链接", (root / "candidates.jsonl").read_text(encoding="utf-8"))
            self.assertIn("edited_and_sent", (root / "logs.jsonl").read_text(encoding="utf-8"))

    def test_save_candidate_does_not_write_send_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["营服"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-2",
                "sha256:group",
                "夏令营咨询群",
                "成员002",
                "student",
                "2026-06-21 10:05:00",
                "营服是什么颜色？",
                "text",
                "manual",
            )
            item = session.process_event(event)

            session.save_candidate(item, edited_reply="营服颜色以后续官方通知为准。")

            self.assertIn("营服颜色", (root / "candidates.jsonl").read_text(encoding="utf-8"))
            self.assertFalse((root / "logs.jsonl").exists())

    def test_record_operator_action_logs_paste_without_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-paste",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-06-21 10:00:00",
                "报名入口在哪里？",
                "text",
                "manual",
            )
            item = session.process_event(event)

            session.record_operator_action(item, item.review_card.reply, operator_action="pasted_to_wechat", action="paste")

            log_text = (root / "logs.jsonl").read_text(encoding="utf-8")
            self.assertIn("pasted_to_wechat", log_text)
            self.assertNotIn("operator_confirmed_sent", log_text)

    def test_confirm_operator_sent_saves_edited_candidate_and_confirmed_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent(
                "evt-confirm",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-06-21 10:00:00",
                "报名入口在哪里？",
                "text",
                "manual",
            )
            item = session.process_event(event)

            session.confirm_operator_sent(item, "同学你好，报名入口请看官方链接。")

            self.assertIn("官方链接", (root / "candidates.jsonl").read_text(encoding="utf-8"))
            self.assertIn("edited_and_confirmed_sent", (root / "logs.jsonl").read_text(encoding="utf-8"))

    def test_records_work_trace_for_processing_and_confirmed_send(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace_path = root / "work_trace.jsonl"
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                trace_path=trace_path,
            )
            event = ChatEvent(
                "evt-trace",
                "sha256:group",
                "夏令营咨询群",
                "成员001",
                "student",
                "2026-06-21 10:00:00",
                "报名入口在哪里？",
                "text",
                "manual",
            )

            item = session.process_event(event)
            session.confirm_operator_sent(item, item.review_card.reply)

            rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([row["event_id"] for row in rows], ["evt-trace", "evt-trace", "evt-trace"])
        self.assertEqual([row["phase"] for row in rows], ["observe", "think", "act"])
        self.assertEqual(rows[-1]["action"], "confirm_sent")
        self.assertEqual(rows[-1]["outcome"], "ok")


if __name__ == "__main__":
    unittest.main()
