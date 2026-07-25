from __future__ import annotations

from .workbench_models import ChatEvent, GroupConfig, TriggerDecision


DEFAULT_CAMP_TERMS = [
    "夏令营",
    "报名",
    "住宿",
    "交通",
    "作业",
    "面试",
    "入营",
    "线下",
    "课程",
    "通知",
    "比赛",
    "赛题",
    "镜像",
    "评测",
    "算力",
    "GPU",
    "算子",
]
QUESTION_MARKS = ["?", "？"]
TEXT_RAW_TYPES = {"text", "0", 0}


class TriggerEngine:
    def __init__(self, config: GroupConfig, camp_terms: list[str] | None = None):
        self.config = config
        self.camp_terms = camp_terms or DEFAULT_CAMP_TERMS

    def decide(self, event: ChatEvent) -> TriggerDecision:
        text = event.content.strip()
        if not text or event.raw_type not in TEXT_RAW_TYPES:
            return TriggerDecision(False, [], [])

        reasons: list[str] = []
        matched_keywords = [keyword for keyword in self.config.keywords if keyword and keyword in text]
        if any(mention and mention in text for mention in self.config.agent_mentions):
            reasons.append("mention")
        if matched_keywords:
            reasons.append("keyword")
        if any(mark in text for mark in QUESTION_MARKS):
            reasons.append("question_mark")

        return TriggerDecision(bool(reasons), reasons, matched_keywords)


def unmatched_reason_codes(
    event: ChatEvent,
    config: GroupConfig,
    decision: TriggerDecision | None = None,
) -> list[str]:
    """返回消息未命中旧触发规则的可解释原因。"""
    trigger = decision or TriggerEngine(config).decide(event)
    if trigger.should_process:
        return []

    text = event.content.strip()
    reasons: list[str] = []
    if not any(mark in text for mark in QUESTION_MARKS):
        reasons.append("missing_question_mark")
    if not any(keyword and keyword in text for keyword in config.keywords):
        reasons.append("missing_keyword")
    if not any(mention and mention in text for mention in config.agent_mentions):
        reasons.append("missing_agent_mention")
    return reasons
