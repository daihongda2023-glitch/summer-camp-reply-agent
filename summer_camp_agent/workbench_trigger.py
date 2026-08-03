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
QUESTION_WORDS = [
    "为什么",
    "为何",
    "怎么回事",
    "什么",
    "是啥",
    "有哪些",
    "哪些",
    "哪个",
    "怎么",
    "怎样",
    "如何",
    "怎么办",
    "哪里",
    "哪儿",
    "在哪",
    "什么地方",
    "什么时候",
    "何时",
    "多久",
    "几点",
    "哪天",
    "多少",
    "几个",
    "几次",
    "几天",
    "谁",
    "找谁",
    "联系谁",
    "是否",
    "是不是",
    "有没有",
    "能否",
    "可否",
    "可以吗",
    "能不能",
    "要不要",
    "需不需要",
    "是否需要",
    "怎么样",
    "进展如何",
    "什么情况",
    "咋",
    "咋办",
    "咋回事",
    "啥",
    "有啥",
    "在哪儿",
]
NO_REPLY_EXPRESSIONS = {
    "没什么问题",
    "没什么问题了",
    "没事了",
    "不用了",
    "不需要了",
    "收到",
    "知道了",
    "明白了",
}
TEXT_RAW_TYPES = {"text", "0", 0}


class TriggerEngine:
    def __init__(self, config: GroupConfig, camp_terms: list[str] | None = None):
        self.config = config
        self.camp_terms = camp_terms or DEFAULT_CAMP_TERMS

    def decide(self, event: ChatEvent) -> TriggerDecision:
        text = event.content.strip()
        if not text or event.raw_type not in TEXT_RAW_TYPES:
            return TriggerDecision(False, [], [])
        if _normalize_no_reply_expression(text) in NO_REPLY_EXPRESSIONS:
            return TriggerDecision(False, [], [])

        reasons: list[str] = []
        matched_keywords = [keyword for keyword in self.config.keywords if keyword and keyword in text]
        if any(mention and mention in text for mention in self.config.agent_mentions):
            reasons.append("mention")
        if matched_keywords:
            reasons.append("keyword")
        if any(mark in text for mark in QUESTION_MARKS):
            reasons.append("question_mark")
        if any(word in text for word in QUESTION_WORDS):
            reasons.append("question_word")

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
    if not any(word in text for word in QUESTION_WORDS):
        reasons.append("missing_question_word")
    if not any(keyword and keyword in text for keyword in config.keywords):
        reasons.append("missing_keyword")
    if not any(mention and mention in text for mention in config.agent_mentions):
        reasons.append("missing_agent_mention")
    return reasons


def _normalize_no_reply_expression(text: str) -> str:
    return "".join(text.split()).strip("。！!，,")
