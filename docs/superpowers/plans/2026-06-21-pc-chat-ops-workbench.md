# PC 端群聊答疑运营工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan step by step. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有夏令营自动回复 agent 升级为 PC 端客服运营工作台，支持群聊消息流、触发规则、半自动草稿、候选库、回复日志和受控全自动决策。

**Architecture:** 先新增独立的工作台核心模块，复用现有 `AnswerEngine`、`OperatorReview`、RAG 和 WeFlow 导入能力；再用 Tkinter 实现三栏工作台 UI。第一版不做真实微信自动发送，只提供半自动草稿、日志和 dry-run 全自动决策，避免高风险微信客户端自动化。

**Tech Stack:** Python 标准库、Tkinter、`unittest`、JSONL 本地存储、现有 FAQ/RAG/WeFlow 模块。

---

## 文件结构

- 新建 `summer_camp_agent/workbench_models.py`：工作台数据模型，包含 `ChatEvent`、`GroupConfig`、`TriggerDecision`、`ReplyDecision`、`ReplyCandidate`、`ReplyLogEntry`。
- 新建 `summer_camp_agent/workbench_trigger.py`：触发规则，处理 `@Agent`、关键词、问号消息。
- 新建 `summer_camp_agent/workbench_store.py`：候选库和回复日志 JSONL 存储。
- 新建 `summer_camp_agent/workbench_modes.py`：半自动/全自动/转人工决策控制器。
- 新建 `summer_camp_agent/workbench_sources.py`：群聊消息源适配器，第一版读取已导入的 JSONL 文件。
- 新建 `summer_camp_agent/workbench_session.py`：工作台会话编排，串联消息源、触发器、审核卡、模式决策、候选库和日志。
- 新建 `summer_camp_agent/workbench_gui.py`：Tkinter 三栏客服运营工作台 UI。
- 修改 `启动夏令营Agent.cmd`：默认启动工作台 UI。
- 测试文件：`tests/test_workbench_trigger.py`、`tests/test_workbench_store.py`、`tests/test_workbench_modes.py`、`tests/test_workbench_sources.py`、`tests/test_workbench_session.py`、`tests/test_workbench_gui.py`。

## 安全边界

- 不破解微信数据库。
- 不实现微信客户端 hook、注入或隐藏式自动发送。
- 第一版发送适配器只做 `manual` 和 `dry_run`。
- 聊天记录只作为触发、风格和候选输入，不进入事实 RAG。
- 人工修改后的内容写入候选库，不直接写入 `data/faq.json`。
- 本地运行数据继续忽略 Git：`data/chat_groups.json`、`data/reply_candidates.jsonl`、`data/reply_logs.jsonl`、`data/listener_state.json`。

## 任务 1：工作台数据模型与触发规则

**Files:**
- Create: `summer_camp_agent/workbench_models.py`
- Create: `summer_camp_agent/workbench_trigger.py`
- Test: `tests/test_workbench_trigger.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from summer_camp_agent.workbench_models import ChatEvent, GroupConfig
from summer_camp_agent.workbench_trigger import TriggerEngine


class WorkbenchTriggerTest(unittest.TestCase):
    def make_event(self, content: str) -> ChatEvent:
        return ChatEvent(
            event_id="evt-1",
            group_id_hash="sha256:group",
            group_name="夏令营咨询群",
            sender_alias="成员001",
            sender_role="student",
            message_time="2026-06-21 10:00:00",
            content=content,
            raw_type="text",
            source="manual",
        )

    def test_triggers_on_agent_mention(self):
        config = GroupConfig(group_name="夏令营咨询群", agent_mentions=["@Agent"], keywords=["报名"])

        decision = TriggerEngine(config).decide(self.make_event("@Agent 报名入口在哪里？"))

        self.assertTrue(decision.should_process)
        self.assertIn("mention", decision.reasons)

    def test_triggers_on_keyword(self):
        config = GroupConfig(group_name="夏令营咨询群", keywords=["住宿"])

        decision = TriggerEngine(config).decide(self.make_event("住宿怎么安排"))

        self.assertTrue(decision.should_process)
        self.assertEqual(decision.matched_keywords, ["住宿"])

    def test_triggers_on_question_mark_with_camp_term(self):
        config = GroupConfig(group_name="夏令营咨询群")

        decision = TriggerEngine(config).decide(self.make_event("夏令营什么时候开始？"))

        self.assertTrue(decision.should_process)
        self.assertIn("question_mark", decision.reasons)

    def test_ignores_unrelated_chat(self):
        config = GroupConfig(group_name="夏令营咨询群", keywords=["报名"])

        decision = TriggerEngine(config).decide(self.make_event("收到，谢谢老师"))

        self.assertFalse(decision.should_process)
        self.assertEqual(decision.reasons, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```text
python -B -m unittest tests.test_workbench_trigger
```

Expected: FAIL with `ModuleNotFoundError: No module named 'summer_camp_agent.workbench_models'`.

- [ ] **Step 3: Write minimal implementation**

Create `summer_camp_agent/workbench_models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChatEvent:
    event_id: str
    group_id_hash: str
    group_name: str
    sender_alias: str
    sender_role: str
    message_time: str
    content: str
    raw_type: str
    source: str


@dataclass(frozen=True)
class GroupConfig:
    group_name: str
    group_id_hash: str = ""
    enabled: bool = True
    mode: str = "semi_auto"
    keywords: list[str] = field(default_factory=lambda: ["报名", "住宿", "交通", "作业", "面试", "通知", "报到", "GPU", "算子"])
    agent_mentions: list[str] = field(default_factory=lambda: ["@Agent", "@夏令营助手"])
    auto_reply_intents: list[str] = field(default_factory=list)
    daily_auto_reply_limit: int = 50


@dataclass(frozen=True)
class TriggerDecision:
    should_process: bool
    reasons: list[str]
    matched_keywords: list[str]
```

Create `summer_camp_agent/workbench_trigger.py`:

```python
from __future__ import annotations

from .workbench_models import ChatEvent, GroupConfig, TriggerDecision


DEFAULT_CAMP_TERMS = ["夏令营", "报名", "住宿", "交通", "作业", "面试", "入营", "线下", "课程", "通知", "GPU", "算子"]
QUESTION_MARKS = ["?", "？"]


class TriggerEngine:
    def __init__(self, config: GroupConfig, camp_terms: list[str] | None = None):
        self.config = config
        self.camp_terms = camp_terms or DEFAULT_CAMP_TERMS

    def decide(self, event: ChatEvent) -> TriggerDecision:
        text = event.content.strip()
        if not text or event.raw_type not in {"text", 0, "0"}:
            return TriggerDecision(False, [], [])

        reasons: list[str] = []
        matched_keywords = [keyword for keyword in self.config.keywords if keyword and keyword in text]
        if any(mention and mention in text for mention in self.config.agent_mentions):
            reasons.append("mention")
        if matched_keywords:
            reasons.append("keyword")
        if any(mark in text for mark in QUESTION_MARKS) and any(term in text for term in self.camp_terms):
            reasons.append("question_mark")

        return TriggerDecision(bool(reasons), reasons, matched_keywords)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```text
python -B -m unittest tests.test_workbench_trigger
```

Expected: PASS.

- [ ] **Step 5: Commit**

```text
git add summer_camp_agent/workbench_models.py summer_camp_agent/workbench_trigger.py tests/test_workbench_trigger.py
git commit -m "feat: add workbench trigger engine"
```

## 任务 2：候选库与回复日志存储

**Files:**
- Modify: `summer_camp_agent/workbench_models.py`
- Create: `summer_camp_agent/workbench_store.py`
- Test: `tests/test_workbench_store.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.workbench_models import ReplyCandidate, ReplyLogEntry
from summer_camp_agent.workbench_store import ReplyCandidateStore, ReplyLogStore


class WorkbenchStoreTest(unittest.TestCase):
    def test_saves_reply_candidate_as_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reply_candidates.jsonl"
            store = ReplyCandidateStore(path)
            candidate = ReplyCandidate(
                candidate_id="cand-1",
                group_name="夏令营咨询群",
                original_question="营服是什么颜色？",
                agent_reply="当前资料还没有明确说明。",
                edited_reply="营服颜色以后续通知为准。",
                source="人工修改",
                confidence=0.0,
                candidate_type="faq",
                status="pending",
                created_at="2026-06-21T10:00:00+08:00",
            )

            store.append(candidate)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(rows[0]["candidate_id"], "cand-1")
        self.assertEqual(rows[0]["status"], "pending")

    def test_saves_reply_log_as_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reply_logs.jsonl"
            store = ReplyLogStore(path)
            entry = ReplyLogEntry(
                log_id="log-1",
                group_name="夏令营咨询群",
                trigger_message_hash="sha256:message",
                trigger_reasons=["keyword"],
                mode="draft",
                action="send",
                reply="同学你好，报名入口为...",
                source="FAQ / 招募文章",
                confidence=0.96,
                operator_action="sent",
                created_at="2026-06-21T10:00:00+08:00",
            )

            store.append(entry)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(rows[0]["log_id"], "log-1")
        self.assertEqual(rows[0]["trigger_reasons"], ["keyword"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```text
python -B -m unittest tests.test_workbench_store
```

Expected: FAIL with `ImportError` for `ReplyCandidate` or `workbench_store`.

- [ ] **Step 3: Write minimal implementation**

Add to `summer_camp_agent/workbench_models.py`:

```python
@dataclass(frozen=True)
class ReplyCandidate:
    candidate_id: str
    group_name: str
    original_question: str
    agent_reply: str
    edited_reply: str
    source: str
    confidence: float
    candidate_type: str
    status: str
    created_at: str


@dataclass(frozen=True)
class ReplyLogEntry:
    log_id: str
    group_name: str
    trigger_message_hash: str
    trigger_reasons: list[str]
    mode: str
    action: str
    reply: str
    source: str
    confidence: float
    operator_action: str
    created_at: str
```

Create `summer_camp_agent/workbench_store.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .workbench_models import ReplyCandidate, ReplyLogEntry


class ReplyCandidateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, candidate: ReplyCandidate) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(candidate), ensure_ascii=False) + "\n")


class ReplyLogStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, entry: ReplyLogEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```text
python -B -m unittest tests.test_workbench_store
```

Expected: PASS.

- [ ] **Step 5: Commit**

```text
git add summer_camp_agent/workbench_models.py summer_camp_agent/workbench_store.py tests/test_workbench_store.py
git commit -m "feat: add workbench local stores"
```

## 任务 3：半自动与受控全自动决策

**Files:**
- Modify: `summer_camp_agent/workbench_models.py`
- Create: `summer_camp_agent/workbench_modes.py`
- Test: `tests/test_workbench_modes.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from summer_camp_agent.review import ReviewCard
from summer_camp_agent.workbench_models import GroupConfig, TriggerDecision
from summer_camp_agent.workbench_modes import ReplyModeController


class WorkbenchModesTest(unittest.TestCase):
    def test_semi_auto_turns_auto_reply_into_draft(self):
        config = GroupConfig(group_name="咨询群", mode="semi_auto")
        card = ReviewCard("报名入口在哪里？", "send", [], "auto_reply", "报名入口为...", intent="registration.link", source="FAQ", confidence=0.96)

        decision = ReplyModeController(config).decide(TriggerDecision(True, ["keyword"], ["报名"]), card)

        self.assertEqual(decision.mode, "draft")
        self.assertTrue(decision.requires_review)

    def test_auto_mode_allows_whitelisted_high_confidence_reply(self):
        config = GroupConfig(group_name="咨询群", mode="auto", auto_reply_intents=["registration.link"])
        card = ReviewCard("报名入口在哪里？", "send", [], "auto_reply", "报名入口为...", intent="registration.link", source="FAQ", confidence=0.96)

        decision = ReplyModeController(config).decide(TriggerDecision(True, ["keyword"], ["报名"]), card)

        self.assertEqual(decision.mode, "auto_send")
        self.assertFalse(decision.requires_review)

    def test_auto_mode_downgrades_non_whitelisted_reply_to_draft(self):
        config = GroupConfig(group_name="咨询群", mode="auto", auto_reply_intents=["registration.link"])
        card = ReviewCard("住宿怎么安排？", "send", [], "auto_reply", "住宿统一安排", intent="cost.accommodation", source="FAQ", confidence=0.96)

        decision = ReplyModeController(config).decide(TriggerDecision(True, ["keyword"], ["住宿"]), card)

        self.assertEqual(decision.mode, "draft")
        self.assertTrue(decision.requires_review)

    def test_human_fallback_is_escalated(self):
        config = GroupConfig(group_name="咨询群", mode="auto", auto_reply_intents=["registration.link"])
        card = ReviewCard("我被录取了吗？", "escalate", [], "human_fallback", "请转人工", reason="personal_status")

        decision = ReplyModeController(config).decide(TriggerDecision(True, ["question_mark"], []), card)

        self.assertEqual(decision.mode, "escalate")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```text
python -B -m unittest tests.test_workbench_modes
```

Expected: FAIL with missing `ReplyModeController`.

- [ ] **Step 3: Write minimal implementation**

Add to `summer_camp_agent/workbench_models.py`:

```python
@dataclass(frozen=True)
class ReplyDecision:
    mode: str
    reply: str
    source: str = ""
    confidence: float = 0.0
    reason: str = ""
    requires_review: bool = True
```

Create `summer_camp_agent/workbench_modes.py`:

```python
from __future__ import annotations

from .review import ReviewCard
from .workbench_models import GroupConfig, ReplyDecision, TriggerDecision


AUTO_REPLY_THRESHOLD = 0.9


class ReplyModeController:
    def __init__(self, config: GroupConfig, auto_reply_threshold: float = AUTO_REPLY_THRESHOLD):
        self.config = config
        self.auto_reply_threshold = auto_reply_threshold

    def decide(self, trigger: TriggerDecision, card: ReviewCard) -> ReplyDecision:
        if not trigger.should_process:
            return ReplyDecision("ignored", "", reason="not_triggered", requires_review=False)
        if card.action == "human_fallback":
            return ReplyDecision("escalate", card.reply, card.source, card.confidence, card.reason, True)
        if card.action != "auto_reply":
            return ReplyDecision("mark_pending", card.reply, card.source, card.confidence, card.reason or "low_confidence", True)
        if self._can_auto_send(card):
            return ReplyDecision("auto_send", card.reply, card.source, card.confidence, "", False)
        return ReplyDecision("draft", card.reply, card.source, card.confidence, card.reason, True)

    def _can_auto_send(self, card: ReviewCard) -> bool:
        return (
            self.config.mode == "auto"
            and bool(card.source)
            and card.confidence >= self.auto_reply_threshold
            and card.intent in set(self.config.auto_reply_intents)
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```text
python -B -m unittest tests.test_workbench_modes
```

Expected: PASS.

- [ ] **Step 5: Commit**

```text
git add summer_camp_agent/workbench_models.py summer_camp_agent/workbench_modes.py tests/test_workbench_modes.py
git commit -m "feat: add workbench reply mode controller"
```

## 任务 4：读取已导入聊天记录的消息源

**Files:**
- Create: `summer_camp_agent/workbench_sources.py`
- Test: `tests/test_workbench_sources.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.workbench_sources import JsonlChatSource


class WorkbenchSourcesTest(unittest.TestCase):
    def test_reads_sanitized_jsonl_as_chat_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat.jsonl"
            row = {
                "group_name": "夏令营咨询群",
                "group_id_hash": "sha256:group",
                "message_time": "2026-06-21 10:00:00",
                "sender_alias": "成员001",
                "sender_role": "unknown",
                "content": "报名入口在哪里？",
                "platform_message_id_hash": "sha256:msg",
                "raw_type": 0,
                "source": "weflow_api"
            }
            path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

            events = JsonlChatSource(path).load_events()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_id, "sha256:msg")
        self.assertEqual(events[0].content, "报名入口在哪里？")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```text
python -B -m unittest tests.test_workbench_sources
```

Expected: FAIL with missing `workbench_sources`.

- [ ] **Step 3: Write minimal implementation**

Create `summer_camp_agent/workbench_sources.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from .workbench_models import ChatEvent


class ChatSourceError(RuntimeError):
    pass


class JsonlChatSource:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load_events(self) -> list[ChatEvent]:
        if not self.path.exists():
            raise ChatSourceError(f"聊天记录文件不存在：{self.path}")
        events: list[ChatEvent] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    continue
                events.append(ChatEvent(
                    event_id=str(raw.get("platform_message_id_hash") or raw.get("event_id") or ""),
                    group_id_hash=str(raw.get("group_id_hash") or ""),
                    group_name=str(raw.get("group_name") or ""),
                    sender_alias=str(raw.get("sender_alias") or ""),
                    sender_role=str(raw.get("sender_role") or "unknown"),
                    message_time=str(raw.get("message_time") or ""),
                    content=str(raw.get("content") or ""),
                    raw_type=str(raw.get("raw_type") or "text"),
                    source=str(raw.get("source") or "jsonl"),
                ))
        return events
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```text
python -B -m unittest tests.test_workbench_sources
```

Expected: PASS.

- [ ] **Step 5: Commit**

```text
git add summer_camp_agent/workbench_sources.py tests/test_workbench_sources.py
git commit -m "feat: add workbench jsonl chat source"
```

## 任务 5：工作台会话编排

**Files:**
- Create: `summer_camp_agent/workbench_session.py`
- Test: `tests/test_workbench_session.py`

- [ ] **Step 1: Write the failing test**

```python
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.workbench_models import ChatEvent, GroupConfig
from summer_camp_agent.workbench_session import WorkbenchSession


class WorkbenchSessionTest(unittest.TestCase):
    def test_process_event_creates_draft_for_triggered_question(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent("evt-1", "sha256:group", "夏令营咨询群", "成员001", "student", "2026-06-21 10:00:00", "报名入口在哪里？", "text", "manual")

            item = session.process_event(event)

        self.assertEqual(item.trigger.should_process, True)
        self.assertEqual(item.reply_decision.mode, "draft")
        self.assertIn("报名入口", item.review_card.reply)

    def test_send_edited_reply_saves_candidate_and_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = WorkbenchSession(
                group_config=GroupConfig(group_name="夏令营咨询群", mode="semi_auto", keywords=["报名"]),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
            )
            event = ChatEvent("evt-1", "sha256:group", "夏令营咨询群", "成员001", "student", "2026-06-21 10:00:00", "报名入口在哪里？", "text", "manual")
            item = session.process_event(event)

            session.confirm_reply(item, edited_reply="同学你好，报名入口请看官方链接。")

            self.assertIn("官方链接", (root / "candidates.jsonl").read_text(encoding="utf-8"))
            self.assertIn("edited_and_sent", (root / "logs.jsonl").read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```text
python -B -m unittest tests.test_workbench_session
```

Expected: FAIL with missing `WorkbenchSession`.

- [ ] **Step 3: Write minimal implementation**

Create `summer_camp_agent/workbench_session.py` with:

- `WorkbenchItem` dataclass.
- `WorkbenchSession.__init__` building `OperatorReview(AnswerEngine(KnowledgeBase.from_default(...)))`.
- `process_event(event)` calling `TriggerEngine` then `OperatorReview` then `ReplyModeController`.
- `confirm_reply(item, edited_reply)` writing `ReplyCandidate` only when edited text differs from agent reply, and always writing `ReplyLogEntry`.

Implementation must use:

```python
from datetime import datetime, timezone
from dataclasses import dataclass
from .chat_log_sanitizer import hash_identifier
```

Use deterministic IDs:

```python
candidate_id = hash_identifier(f"{event.event_id}:{edited_reply}")
log_id = hash_identifier(f"{event.event_id}:{edited_reply}:{datetime.now(timezone.utc).isoformat()}")
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```text
python -B -m unittest tests.test_workbench_session
```

Expected: PASS.

- [ ] **Step 5: Commit**

```text
git add summer_camp_agent/workbench_session.py tests/test_workbench_session.py
git commit -m "feat: add workbench session orchestration"
```

## 任务 6：Tkinter 工作台 UI 骨架

**Files:**
- Create: `summer_camp_agent/workbench_gui.py`
- Test: `tests/test_workbench_gui.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from summer_camp_agent.workbench_gui import SummerCampWorkbenchApp


class WorkbenchGuiTest(unittest.TestCase):
    def test_workbench_app_class_is_importable(self):
        self.assertEqual(SummerCampWorkbenchApp.__name__, "SummerCampWorkbenchApp")

    def test_default_group_names_are_available(self):
        self.assertIn("夏令营咨询群", SummerCampWorkbenchApp.default_group_names())
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```text
python -B -m unittest tests.test_workbench_gui
```

Expected: FAIL with missing `workbench_gui`.

- [ ] **Step 3: Write minimal implementation**

Create `summer_camp_agent/workbench_gui.py`:

- `SummerCampWorkbenchApp` class.
- `default_group_names()` returns `["夏令营咨询群", "入营通知群", "技术答疑群"]`.
- UI uses three columns:
  - left: group list and mode label.
  - center: message stream.
  - right: decision panel.
  - bottom: reply input and buttons.
- Reuse `WorkbenchSession` for processing manually typed messages in the first version.
- Include `main()` with `tk.Tk()` and `root.mainloop()`.

The UI should not perform real WeChat sending. The “发送” button logs a local action and appends a message to the stream.

- [ ] **Step 4: Run test to verify it passes**

Run:

```text
python -B -m unittest tests.test_workbench_gui
```

Expected: PASS.

- [ ] **Step 5: Commit**

```text
git add summer_camp_agent/workbench_gui.py tests/test_workbench_gui.py
git commit -m "feat: add workbench tkinter shell"
```

## 任务 7：启动脚本与文档收尾

**Files:**
- Modify: `启动夏令营Agent.cmd`
- Modify: `docs/product/pc-chat-ops-workbench-interaction.md`
- Test: `tests/test_desktop_chat.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_desktop_chat.py`:

```python
from summer_camp_agent.workbench_gui import SummerCampWorkbenchApp


def test_workbench_gui_app_class_is_importable(self):
    self.assertEqual(SummerCampWorkbenchApp.__name__, "SummerCampWorkbenchApp")
```

- [ ] **Step 2: Run test to verify it passes or fails for the right reason**

Run:

```text
python -B -m unittest tests.test_desktop_chat tests.test_workbench_gui
```

Expected: PASS after Task 6; this step protects the launcher-facing import.

- [ ] **Step 3: Update launcher**

Change `启动夏令营Agent.cmd` from:

```cmd
start "" pythonw -m summer_camp_agent.gui
```

to:

```cmd
start "" pythonw -m summer_camp_agent.workbench_gui
```

And change the fallback Python line the same way.

- [ ] **Step 4: Update product doc**

Append a short “第一版启动方式” section to `docs/product/pc-chat-ops-workbench-interaction.md`:

```markdown
## 第一版启动方式

双击 `启动夏令营Agent.cmd` 后默认进入 PC 端群聊答疑运营工作台。旧的单轮对话验证能力仍可通过 `python -m summer_camp_agent.gui` 启动。
```

- [ ] **Step 5: Run verification**

Run:

```text
python -B -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```text
git add 启动夏令营Agent.cmd docs/product/pc-chat-ops-workbench-interaction.md tests/test_desktop_chat.py
git commit -m "chore: launch pc chat ops workbench by default"
```

## 任务 8：最终验证

**Files:**
- No new files.

- [ ] **Step 1: Run full test suite**

Run:

```text
python -B -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 2: Check formatting and secrets**

Run:

```text
git diff --check
rg -n "OPENAI_API_KEY=.*|WEFLOW_API_TOKEN=.*|gh[p]_[A-Za-z0-9]|github[_]pat_|AKIA[0-9A-Z]{16}" summer_camp_agent tests docs 启动夏令营Agent.cmd
```

Expected: `git diff --check` exits 0. The `rg` command may return non-zero when no secrets are found; no real secret should be printed.

- [ ] **Step 3: Report status**

Include:

- New modules created.
- Commands run and results.
- How to start the workbench.
- Known limitations: no real微信自动发送，监听源第一版以导入 JSONL 和后续 WeFlow 轮询为主。
