import tempfile
import unittest
from datetime import date
from pathlib import Path

from summer_camp_agent.engine import AnswerEngine
from summer_camp_agent.knowledge import KnowledgeBase
from summer_camp_agent.rag_ai import RagGenerationResult
from summer_camp_agent.rag_runtime import load_default_rag_retriever
from summer_camp_agent.review import OperatorReview
from summer_camp_agent.wechat_assisted_paste import PasteResult
from summer_camp_agent.wechat_live_listener import ListenerPollResult
from summer_camp_agent.workbench_api import WorkbenchApiState
from summer_camp_agent.workbench_models import ChatEvent


class SimulatedListener:
    def __init__(self, events):
        self.events = events

    def poll_once(self, *, include_seen=False):
        events, self.events = self.events, []
        return ListenerPollResult("ok", "模拟消息已拉取", events)


class SimulatedPublishAdapter:
    def __init__(self):
        self.sent = []

    def send_to_wechat_foreground(self, text, target_group_name=""):
        self.sent.append((target_group_name, text))
        return PasteResult(
            "sent_verified",
            "模拟自动发布成功。",
            "测试群 - 微信",
            target_found=True,
            input_focused=True,
            filled=True,
            verified=True,
            target_status="matched",
            input_status="focused",
            verification_status="matched",
        )


class ScenarioGenerator:
    model = "fake-model"

    def __init__(self, result=None):
        self.result = result
        self.questions = []

    def generate(self, question, rag_result):
        self.questions.append(question)
        if self.result is not None:
            return self.result
        return RagGenerationResult(
            "generated",
            answer=f"AI 已根据官方资料回答：{question}",
            model=self.model,
        )


def make_event(event_id, content):
    return ChatEvent(
        event_id,
        "sha256:simulation-group",
        "测试群",
        "成员001",
        "student",
        "2026-07-15 12:00:00",
        content,
        "text",
        "simulation",
    )


class FullReplyChainSimulationTest(unittest.TestCase):
    def make_state(self, root, rag_answer_generator=None):
        state = WorkbenchApiState(
            candidate_path=root / "candidates.jsonl",
            log_path=root / "logs.jsonl",
            wechat_config_path=root / "wechat_bridge_config.json",
            rag_answer_generator=rag_answer_generator,
        )
        state.configure_wechat(
            {
                "base_url": "http://127.0.0.1:5031",
                "token_env": "WEFLOW_API_TOKEN",
                "group_name": "测试群",
                "session_id": "",
                "keywords": ["测试"],
                "poll_interval_seconds": 5,
                "enabled": True,
                "show_debug_config": False,
                "send_mode": "auto_send",
                "debug_review_mode": False,
            }
        )
        state.paste_adapter = SimulatedPublishAdapter()
        return state

    def test_all_faq_questions_and_aliases_reach_simulated_auto_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge = KnowledgeBase.from_default()
            generator = ScenarioGenerator()
            state = self.make_state(root, generator)
            state.session.review = OperatorReview(
                AnswerEngine(
                    knowledge,
                    today=date(2026, 7, 15),
                    rag_retriever=load_default_rag_retriever(),
                    rag_answer_generator=generator,
                )
            )
            utterances = [
                (item.intent, question)
                for item in knowledge.items
                for question in [item.question, *item.question_aliases]
            ]
            events = [
                make_event(f"faq-simulation-{index}", f"@Agent {question}")
                for index, (_, question) in enumerate(utterances)
            ]
            state.wechat_listener = SimulatedListener(events)

            state.poll_wechat_once()
            items = state.list_items(scope="all")["items"]

        self.assertEqual(len(items), len(utterances))
        self.assertEqual(len(state.paste_adapter.sent), len(utterances))
        self.assertTrue(all(item["status"] == "已发送" for item in items))
        self.assertTrue(all(item["mode"] == "auto_send" for item in items))
        self.assertTrue(all(item["generation_mode"] == "faq" for item in items))
        self.assertEqual(generator.questions, [])
        self.assertEqual(
            [item["intent"] for item in items],
            [intent for intent, _ in utterances],
        )

    def test_natural_registration_time_question_reaches_simulated_auto_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = self.make_state(root)
            state.wechat_listener = SimulatedListener(
                [make_event("faq-registration-time", "报名时间是什么时候？")]
            )

            state.poll_wechat_once()
            history = state.list_items(scope="all")["items"]

        item = history[0]
        self.assertIn("question_mark", item["trigger_reasons"])
        self.assertEqual(item["intent"], "registration.deadline")
        self.assertEqual(item["mode"], "auto_send")
        self.assertEqual(item["status"], "已发送")
        self.assertIn("报名已于 2026 年 7 月 15 日截止", item["reply"])
        self.assertEqual(len(state.paste_adapter.sent), 1)

    def test_faq_miss_uses_official_rag_and_reaches_simulated_auto_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = self.make_state(root)
            state.wechat_listener = SimulatedListener(
                [make_event("rag-simulation-1", "请问能否公开下载比赛镜像？")]
            )

            state.poll_wechat_once()
            history = state.list_items(scope="all")["items"]

        item = history[0]
        self.assertEqual(item["intent"], "rag.document")
        self.assertEqual(item["mode"], "auto_send")
        self.assertEqual(item["status"], "已发送")
        self.assertIn("https://developer.metax-tech.com/", item["reply"])
        self.assertIn("gitlink.org.cn/metax-maca/op_optimization/issues/19", item["answer_source"])
        self.assertEqual(len(state.paste_adapter.sent), 1)

    def test_official_rag_scenarios_use_ai_and_reach_simulated_auto_publish(self):
        cases = [
            "请问能否公开下载比赛镜像？",
            "页面选择 3.7.2.1，进入服务器发现实际是 3.7.1.5，为什么？",
            "MACA C++、Triton 和 TileLang 是放在一个榜里比吗？",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generator = ScenarioGenerator()
            state = self.make_state(root, generator)
            state.wechat_listener = SimulatedListener(
                [
                    make_event(f"rag-ai-simulation-{index}", question)
                    for index, question in enumerate(cases)
                ]
            )

            state.poll_wechat_once()
            items = state.list_items(scope="all")["items"]

        self.assertEqual(len(items), len(cases))
        self.assertEqual(len(state.paste_adapter.sent), len(cases))
        self.assertEqual(generator.questions, cases)
        for question, item, sent in zip(
            cases,
            items,
            state.paste_adapter.sent,
            strict=True,
        ):
            with self.subTest(question=question):
                self.assertEqual(item["intent"], "rag.document")
                self.assertEqual(item["generation_mode"], "rag_ai")
                self.assertEqual(item["generation_model"], "fake-model")
                self.assertEqual(item["mode"], "auto_send")
                self.assertEqual(item["status"], "已发送")
                self.assertEqual(sent[1], item["reply"])

    def test_community_and_unknown_questions_never_call_ai_or_auto_publish(self):
        questions = [
            "CMake 构建失败怎么办？",
            "营服是什么颜色？",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generator = ScenarioGenerator()
            state = self.make_state(root, generator)
            state.wechat_listener = SimulatedListener(
                [
                    make_event(f"blocked-simulation-{index}", question)
                    for index, question in enumerate(questions)
                ]
            )

            payload = state.poll_wechat_once()

        self.assertEqual(generator.questions, [])
        self.assertEqual(state.paste_adapter.sent, [])
        self.assertEqual(
            [item["generation_mode"] for item in payload["items"]],
            ["rag_community", "needs_info"],
        )
        self.assertTrue(all(item["mode"] != "auto_send" for item in payload["items"]))

    def test_ai_failures_fall_back_to_official_rag_and_still_auto_publish(self):
        failures = [
            RagGenerationResult(
                "unavailable",
                model="fake-model",
                error="timeout",
            ),
            RagGenerationResult(
                "invalid",
                model="fake-model",
                error="unsupported_url",
            ),
        ]
        for index, failure in enumerate(failures):
            with self.subTest(error=failure.error), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                generator = ScenarioGenerator(failure)
                state = self.make_state(root, generator)
                state.wechat_listener = SimulatedListener(
                    [
                        make_event(
                            f"rag-fallback-{index}",
                            "请问能否公开下载比赛镜像？",
                        )
                    ]
                )

                state.poll_wechat_once()
                item = state.list_items(scope="all")["items"][0]
                self.assertEqual(item["generation_mode"], "rag_fallback")
                self.assertEqual(item["generation_error"], failure.error)
                self.assertEqual(item["mode"], "auto_send")
                self.assertEqual(item["status"], "已发送")
                self.assertIn("developer.metax-tech.com", item["reply"])
                self.assertEqual(state.paste_adapter.sent[0][1], item["reply"])


if __name__ == "__main__":
    unittest.main()
