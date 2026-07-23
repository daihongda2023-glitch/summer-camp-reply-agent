from __future__ import annotations

import json
import tempfile
from pathlib import Path

from summer_camp_agent.rag_ai import RagGenerationResult
from summer_camp_agent.semantic_router import SemanticAnalysisResult, SemanticCatalog
from summer_camp_agent.wechat_assisted_paste import PasteResult
from summer_camp_agent.wechat_live_listener import ListenerPollResult
from summer_camp_agent.workbench_api import WorkbenchApiState
from summer_camp_agent.workbench_models import ChatEvent


QUESTIONS = [
    "XPUOJ测评 MoE 耗时减少了但是分数反而降低了？",
    "夏令营期间我碰到问题该找谁处理？",
    "线下夏令营在哪？",
]

SUPPORT_REPLY = (
    "建议优先通过 GitLink Issue 提交问题，相关问题及解答会统一沉淀，"
    "也可以加入赛事专属答疑群获取通知。如需进一步沟通，"
    "请按比赛方案联系章老师或杨老师。"
)


class ScenarioSemanticAnalyzer:
    model = "scenario-semantic-v1"

    def analyze(
        self,
        question: str,
        catalog: SemanticCatalog,
    ) -> SemanticAnalysisResult:
        if question == QUESTIONS[0]:
            return SemanticAnalysisResult(
                status="analyzed",
                canonical_question="XPUOJ 测评中 MoE 耗时下降但分数降低是什么原因？",
                intent="evaluation.scoring",
                rag_candidate_ids=[
                    _unique_rag_id(catalog, "MoE 初赛正式排名")
                ],
                rag_queries=["XPUOJ MoE 耗时 分数 评分规则"],
                semantic_confidence=0.94,
                model=self.model,
            )
        if question == QUESTIONS[1]:
            return SemanticAnalysisResult(
                status="analyzed",
                canonical_question="夏令营期间遇到问题应通过什么渠道联系谁处理？",
                intent="support.contact",
                rag_candidate_ids=[_unique_rag_id(catalog, "联系人")],
                rag_queries=["夏令营 问题 联系人 答疑渠道"],
                semantic_confidence=0.95,
                model=self.model,
            )
        if question == QUESTIONS[2]:
            return SemanticAnalysisResult(
                status="analyzed",
                canonical_question="线下夏令营在哪里举办？",
                intent="offline.location",
                faq_candidate_ids=["faq.offline.location"],
                semantic_confidence=0.98,
                model=self.model,
            )
        return SemanticAnalysisResult(
            status="analyzed",
            canonical_question=question,
            semantic_confidence=0.40,
            requires_human=True,
            reason="scenario_unknown",
            model=self.model,
        )


class ScenarioRagAnswerGenerator:
    model = "scenario-answer-v1"

    def generate(self, question, rag_result) -> RagGenerationResult:
        if question == QUESTIONS[0]:
            return RagGenerationResult(
                status="invalid",
                model=self.model,
                error="not_grounded",
            )
        if question == QUESTIONS[1]:
            return RagGenerationResult(
                status="generated",
                answer=SUPPORT_REPLY,
                model=self.model,
            )
        raise AssertionError(f"不应为该问题调用 RAG 回答生成器：{question}")


class ScenarioListener:
    def __init__(self, events: list[ChatEvent]):
        self.events = events
        self.replied_event_ids: list[str] = []

    def poll_once(self, *, include_seen: bool = False) -> ListenerPollResult:
        return ListenerPollResult("ok", "已拉取 3 条场景消息", self.events)

    def mark_replied(self, event_id: str, reply: str = "") -> None:
        self.replied_event_ids.append(event_id)

    def is_replied(self, event_id: str) -> bool:
        return event_id in self.replied_event_ids


class ScenarioPasteAdapter:
    def __init__(self):
        self.sent: list[str] = []

    def send_to_wechat_foreground(
        self,
        text: str,
        target_group_name: str = "",
    ) -> PasteResult:
        self.sent.append(text)
        return PasteResult(
            action="sent_verified",
            message="已模拟发送并校验",
            foreground_window_title=f"{target_group_name} - 微信",
            target_found=True,
            input_focused=True,
            filled=True,
            verified=True,
            target_status="matched",
            input_status="focused",
            verification_status="matched",
        )


def run_verification(root: Path) -> dict[str, object]:
    paths = {
        "candidate_path": root / "reply_candidates.jsonl",
        "log_path": root / "reply_logs.jsonl",
        "trace_path": root / "work_trace.jsonl",
        "inbox_path": root / "workbench_inbox.jsonl",
        "wechat_config_path": root / "wechat_bridge_config.json",
        "desktop_settings_path": root / "desktop_settings.json",
    }
    analyzer = ScenarioSemanticAnalyzer()
    generator = ScenarioRagAnswerGenerator()
    state = WorkbenchApiState(
        **paths,
        semantic_analyzer=analyzer,
        rag_answer_generator=generator,
    )
    state.configure_wechat(
        {
            "base_url": "http://127.0.0.1:5031",
            "token_env": "WEFLOW_API_TOKEN",
            "group_name": "测试工具",
            "session_id": "",
            "keywords": ["XPUOJ", "夏令营", "线下"],
            "poll_interval_seconds": 5,
            "enabled": True,
            "show_debug_config": False,
            "send_mode": "auto_send",
        }
    )
    listener = ScenarioListener(_events())
    paste_adapter = ScenarioPasteAdapter()
    state.wechat_listener = listener
    state.paste_adapter = paste_adapter

    payload = state.poll_wechat_once()
    items = payload["items"]

    restarted = WorkbenchApiState(
        **paths,
        semantic_analyzer=analyzer,
        rag_answer_generator=generator,
    )
    return {
        "status": payload["status"],
        "results": [
            {
                "question": item["question"],
                "reply": item["reply"],
                "mode": item["mode"],
                "replied": item["replied"],
                "generation_mode": item["generation_mode"],
                "semantic_intent": item["semantic_intent"],
                "semantic_confidence": item["semantic_confidence"],
                "faq_confidence": item["faq_confidence"],
                "rag_confidence": item["rag_confidence"],
                "reason": item["reason"],
            }
            for item in items
        ],
        "sent_replies": paste_adapter.sent,
        "pending_after_restart": [
            item.event.content
            for item in restarted.items
        ],
    }


def _unique_rag_id(catalog: SemanticCatalog, heading_fragment: str) -> str:
    matches = [
        str(item["id"])
        for item in catalog.rag_items
        if heading_fragment in str(item["heading"])
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"RAG 目录中“{heading_fragment}”候选数量应为 1，实际为 {len(matches)}"
        )
    return matches[0]


def _events() -> list[ChatEvent]:
    return [
        ChatEvent(
            event_id=f"scenario-{index}",
            group_id_hash="sha256:scenario-group",
            group_name="测试工具",
            sender_alias="成员001",
            sender_role="student",
            message_time=f"2026-07-23 22:0{index}:00",
            content=question,
            raw_type="text",
            source="scenario_validation",
        )
        for index, question in enumerate(QUESTIONS, start=1)
    ]


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        result = run_verification(Path(directory))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
