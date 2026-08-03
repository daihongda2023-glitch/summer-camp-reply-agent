"""使用真实 DeepSeek V4、模拟微信收发，验证 RAG 自动回复闭环。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from summer_camp_agent.rag_runtime import load_default_rag_answer_generator
from summer_camp_agent.wechat_assisted_paste import PasteResult
from summer_camp_agent.wechat_live_listener import ListenerPollResult
from summer_camp_agent.workbench_api import WorkbenchApiState
from summer_camp_agent.workbench_models import ChatEvent


QUESTIONS = [
    "请问能否公开下载比赛镜像？",
    "页面选择 3.7.2.1，进入服务器发现实际是 3.7.1.5，为什么？",
    "MACA C++、Triton 和 TileLang 是放在一个榜里比吗？",
]


class SimulatedListener:
    def __init__(self, events: list[ChatEvent]):
        self.events = events

    def poll_once(self, *, include_seen: bool = False) -> ListenerPollResult:
        del include_seen
        events, self.events = self.events, []
        return ListenerPollResult("ok", "模拟消息已拉取", events)


class SimulatedPublishAdapter:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send_to_wechat_foreground(
        self,
        text: str,
        target_group_name: str = "",
    ) -> PasteResult:
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


def make_event(index: int, question: str) -> ChatEvent:
    return ChatEvent(
        f"rag-ai-live-{index}",
        "sha256:rag-ai-live-group",
        "测试群",
        "成员001",
        "student",
        "2026-07-23 12:00:00",
        question,
        "text",
        "rag-ai-live-simulation",
    )


def build_verification_wechat_config() -> dict[str, object]:
    return {
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


def collect_verification_items(
    state: WorkbenchApiState,
) -> list[dict[str, object]]:
    return state.list_items(scope="all")["items"]


def is_completed_auto_send(item: dict[str, object]) -> bool:
    return item.get("status") == "已发送" and item.get("mode") == "auto_send"


def main() -> int:
    generator = load_default_rag_answer_generator()
    if generator is None:
        raise RuntimeError("未检测到 OPENAI_API_KEY，无法执行真实 DeepSeek 验证。")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = WorkbenchApiState(
            candidate_path=root / "candidates.jsonl",
            log_path=root / "logs.jsonl",
            wechat_config_path=root / "wechat_bridge_config.json",
            rag_answer_generator=generator,
        )
        state.configure_wechat(build_verification_wechat_config())
        state.wechat_listener = SimulatedListener(
            [make_event(index, question) for index, question in enumerate(QUESTIONS)]
        )
        publisher = SimulatedPublishAdapter()
        state.paste_adapter = publisher

        state.poll_wechat_once()
        items = collect_verification_items(state)

    if len(items) != len(QUESTIONS):
        raise AssertionError(f"期望生成 {len(QUESTIONS)} 条回复，实际为 {len(items)} 条。")
    if len(publisher.sent) != len(QUESTIONS):
        errors = [
            item.get("generation_error", "")
            for item in items
            if item.get("generation_mode") != "rag_ai"
        ]
        raise AssertionError(
            f"期望模拟发送 {len(QUESTIONS)} 条，实际为 {len(publisher.sent)} 条；"
            f"AI 错误：{errors}"
        )

    print(f"真实模型：{items[0]['generation_model']}")
    for index, (question, item) in enumerate(zip(QUESTIONS, items, strict=True), start=1):
        if item["generation_mode"] != "rag_ai":
            raise AssertionError(
                f"场景 {index} 未使用 AI：{item['generation_mode']}，"
                f"原因：{item.get('generation_error', '')}"
            )
        if not is_completed_auto_send(item):
            raise AssertionError(f"场景 {index} 未完成自动回复闭环：{item}")
        if not item["reply"] or len(item["reply"]) > 600:
            raise AssertionError(f"场景 {index} 的回复为空或超过 600 字。")

        print(f"\n场景 {index}：{question}")
        print(f"资料来源：{item['answer_source']}")
        print(f"AI 回复：{item['reply']}")

    print(f"\n验证通过：{len(items)} 个 RAG 场景均由真实 AI 生成并完成模拟自动发送。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
