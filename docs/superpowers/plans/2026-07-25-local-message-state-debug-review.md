# 本地消息状态与调试审核模式实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用 SQLite 持久化每条工作台消息的完整状态，并让调试模式下所有目标群文本消息进入待审核、展示置信度与未命中原因且禁止自动发送。

**Architecture:** 新增独立的 `WorkbenchMessageStore`，使用 `event_id` 主键保存审核状态和完整 `WorkbenchItem` 快照；`WorkbenchApiState` 只在新消息首次进入时运行回答引擎，重启直接从快照恢复。`debug_review_mode` 从微信桥接配置贯穿监听器、会话决策、API 和桌面端，调试模式保留原有触发诊断但强制所有文本进入人工审核。

**Tech Stack:** Python 3.12 标准库 `sqlite3`、`dataclasses`、`unittest`，Electron 39、React 19、TypeScript 5、Node 静态测试。

---

## 文件职责

- 新建 `summer_camp_agent/workbench_message_store.py`：SQLite 表结构、消息快照编解码、幂等插入、状态更新、查询和迁移元数据。
- 修改 `summer_camp_agent/workbench_models.py`：定义审核状态、命中状态和持久化消息记录类型。
- 修改 `summer_camp_agent/workbench_session.py`：支持调试模式下未触发消息仍生成审核卡，并强制返回人工审核决策。
- 修改 `summer_camp_agent/wechat_bridge_config.py`：增加持久化配置 `debug_review_mode`。
- 修改 `summer_camp_agent/wechat_live_listener.py`：调试模式返回其他成员的所有文本消息，正式模式保留原触发过滤。
- 修改 `summer_camp_agent/workbench_api.py`：接入 SQLite、旧 JSONL 迁移、状态动作、历史查询和调试模式禁止自动发送。
- 修改 `summer_camp_agent/workbench_presenter.py`：展示审核状态和命中状态。
- 修改 `desktop/src/shared/types.ts`：扩展设置、消息和操作结果类型。
- 修改 `desktop/src/main/main.ts`：增加查询范围、转人工和审核完成请求。
- 修改 `desktop/src/preload/preload.ts`：暴露新增窄接口。
- 修改 `desktop/src/renderer/App.tsx`：增加调试开关、调试提示、列表范围、状态诊断和处理按钮。
- 修改 `desktop/tests/static.test.mjs`：验证调试模式和状态操作界面。
- 修改 `.gitignore`：忽略 SQLite 数据库及 WAL/SHM 文件。
- 修改 `docs/technical-architecture.md`：记录消息状态机、调试模式和迁移边界。

### Task 1：实现 SQLite 消息主存储

**Files:**
- Create: `summer_camp_agent/workbench_message_store.py`
- Modify: `summer_camp_agent/workbench_models.py`
- Test: `tests/test_workbench_message_store.py`

- [ ] **Step 1：编写唯一主键、快照恢复和状态更新的失败测试**

在 `tests/test_workbench_message_store.py` 创建真实临时 SQLite 数据库，使用真实 `WorkbenchItem`：

```python
def test_message_store_upserts_by_event_id_and_restores_snapshot():
    item = workbench_item("evt-1", "普通消息")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "messages.db"
        store = WorkbenchMessageStore(path)
        first = store.insert_pending(
            item,
            match_status="unmatched",
            unmatched_reasons=[
                "missing_question_mark",
                "missing_keyword",
                "missing_agent_mention",
            ],
        )
        second = store.insert_pending(
            item,
            match_status="unmatched",
            unmatched_reasons=["missing_question_mark"],
        )
        restored = WorkbenchMessageStore(path).get("evt-1")

    self.assertTrue(first)
    self.assertFalse(second)
    self.assertEqual(restored.message_id, "evt-1")
    self.assertEqual(restored.item.event.content, "普通消息")
    self.assertEqual(restored.review_status, "pending_review")
    self.assertEqual(restored.match_status, "unmatched")
    self.assertEqual(
        restored.unmatched_reasons,
        ["missing_question_mark", "missing_keyword", "missing_agent_mention"],
    )
```

再增加：

```python
def test_completed_message_is_updated_in_place_and_not_reset_by_duplicate_insert():
    store.insert_pending(item, match_status="matched", unmatched_reasons=[])
    updated = store.complete(
        "evt-1",
        review_status="sent",
        review_action="confirm_sent",
        review_note="运营确认已发送",
    )
    store.insert_pending(item, match_status="matched", unmatched_reasons=[])

    rows = store.list_all()
    self.assertEqual(len(rows), 1)
    self.assertEqual(updated.review_status, "sent")
    self.assertEqual(rows[0].review_status, "sent")
    self.assertTrue(rows[0].completed_at)
```

以及非法状态测试：

```python
def test_message_store_rejects_invalid_status_and_empty_primary_key():
    with self.assertRaisesRegex(ValueError, "event_id"):
        store.insert_pending(workbench_item("", "消息"), "matched", [])
    with self.assertRaisesRegex(ValueError, "review_status"):
        store.complete("evt-1", "deleted", "delete", "")
```

- [ ] **Step 2：运行测试并确认存储模块不存在**

Run:

```powershell
python -m unittest tests.test_workbench_message_store -v
```

Expected: FAIL，原因是 `summer_camp_agent.workbench_message_store` 不存在。

- [ ] **Step 3：定义状态类型和 SQLite 存储接口**

在 `workbench_models.py` 增加：

```python
REVIEW_STATUSES = {
    "pending_review",
    "sent",
    "escalated",
    "candidate_saved",
    "review_completed",
}
MATCH_STATUSES = {"matched", "unmatched"}


@dataclass(frozen=True)
class StoredWorkbenchMessage:
    message_id: str
    item: "WorkbenchItem"
    review_status: str
    match_status: str
    unmatched_reasons: list[str]
    review_action: str = ""
    review_note: str = ""
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""
```

为避免运行时循环导入，只在 `TYPE_CHECKING` 分支导入 `WorkbenchItem`。

在新文件实现：

```python
class WorkbenchMessageStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = RLock()
        self._initialize()

    def insert_pending(
        self,
        item: WorkbenchItem,
        match_status: str,
        unmatched_reasons: list[str],
    ) -> bool:
        ...

    def get(self, event_id: str) -> StoredWorkbenchMessage | None:
        ...

    def list_pending(self) -> list[StoredWorkbenchMessage]:
        ...

    def list_all(
        self,
        review_status: str | None = None,
    ) -> list[StoredWorkbenchMessage]:
        ...

    def complete(
        self,
        event_id: str,
        review_status: str,
        review_action: str,
        review_note: str,
    ) -> StoredWorkbenchMessage:
        ...

    def get_metadata(self, key: str) -> str:
        ...

    def set_metadata(self, key: str, value: str) -> None:
        ...
```

表结构使用可查询状态列和完整快照 JSON：

```sql
CREATE TABLE IF NOT EXISTS workbench_messages (
    event_id TEXT PRIMARY KEY,
    review_status TEXT NOT NULL,
    match_status TEXT NOT NULL,
    unmatched_reasons_json TEXT NOT NULL,
    item_snapshot_json TEXT NOT NULL,
    review_action TEXT NOT NULL DEFAULT '',
    review_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_workbench_messages_review_status
ON workbench_messages(review_status, created_at DESC);
CREATE TABLE IF NOT EXISTS workbench_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

快照 JSON 明确分成：

```python
{
    "event": asdict(item.event),
    "trigger": asdict(item.trigger),
    "review_card": asdict(item.review_card),
    "reply_decision": asdict(item.reply_decision),
}
```

反序列化时分别构造 `ChatEvent`、`TriggerDecision`、`ReviewCard`、
`ReplyDecision` 和 `WorkbenchItem`。数据库连接使用上下文事务并设置：

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
```

- [ ] **Step 4：运行存储测试并确认通过**

Run:

```powershell
python -m unittest tests.test_workbench_message_store -v
```

Expected: 所有 SQLite 存储测试 PASS。

- [ ] **Step 5：提交存储层**

```powershell
git add summer_camp_agent/workbench_models.py summer_camp_agent/workbench_message_store.py tests/test_workbench_message_store.py
git commit -m "feat: 增加 SQLite 消息状态存储"
```

### Task 2：增加调试配置和全文本监听

**Files:**
- Modify: `summer_camp_agent/wechat_bridge_config.py`
- Modify: `summer_camp_agent/wechat_live_listener.py`
- Test: `tests/test_wechat_bridge_config.py`
- Test: `tests/test_wechat_live_listener.py`

- [ ] **Step 1：编写调试配置默认值与持久化失败测试**

在 `tests/test_wechat_bridge_config.py` 增加：

```python
def test_debug_review_mode_defaults_to_true_and_round_trips():
    self.assertTrue(WeChatBridgeConfig().debug_review_mode)
    parsed = WeChatBridgeConfig.from_dict({"debug_review_mode": False})
    self.assertFalse(parsed.debug_review_mode)
    self.assertFalse(parsed.to_dict()["debug_review_mode"])
```

存储测试保存 `debug_review_mode=True`，重新加载后断言仍为 `True`。

- [ ] **Step 2：编写监听器调试模式接收未命中文本的失败测试**

在 `tests/test_wechat_live_listener.py` 使用不含问号、关键词和 mention 的
`"今天天气不错"`：

```python
def test_debug_review_mode_returns_unmatched_text_message():
    listener = make_listener(
        messages=[raw_text("msg-debug", "今天天气不错")],
        config=WeChatBridgeConfig(
            group_name="测试群",
            keywords=["报名"],
            debug_review_mode=True,
        ),
    )

    result = listener.poll_once()

    self.assertEqual(result.status, "ok")
    self.assertEqual([event.content for event in result.events], ["今天天气不错"])
```

增加正式模式对照：

```python
def test_formal_mode_still_filters_unmatched_text_message():
    listener = make_listener(
        messages=[raw_text("msg-formal", "今天天气不错")],
        config=WeChatBridgeConfig(
            group_name="测试群",
            keywords=["报名"],
            debug_review_mode=False,
        ),
    )
    self.assertEqual(listener.poll_once().events, [])
```

保留现有自发消息和非文本过滤测试，并显式在需要正式行为的测试配置中设置
`debug_review_mode=False`。

- [ ] **Step 3：运行测试并确认字段缺失和未命中消息被过滤**

Run:

```powershell
python -m unittest tests.test_wechat_bridge_config tests.test_wechat_live_listener -v
```

Expected: FAIL，原因包含缺少 `debug_review_mode`，且调试场景未返回消息。

- [ ] **Step 4：实现配置字段和监听分支**

在 `WeChatBridgeConfig` 增加：

```python
debug_review_mode: bool = True
```

在 `from_dict` 中使用：

```python
debug_review_mode=bool(raw.get("debug_review_mode", True))
```

在 `WeFlowLiveListener._event_from_raw` 末尾使用：

```python
if self.config.debug_review_mode:
    return event
trigger = TriggerEngine(
    GroupConfig(group_name=session.name, keywords=[*self.config.keywords])
).decide(event)
return event if trigger.should_process else None
```

自发消息、回复回环、时间范围和非文本过滤继续在此前分支执行。

- [ ] **Step 5：运行配置和监听测试**

Run:

```powershell
python -m unittest tests.test_wechat_bridge_config tests.test_wechat_live_listener -v
```

Expected: 全部 PASS。

- [ ] **Step 6：提交调试监听**

```powershell
git add summer_camp_agent/wechat_bridge_config.py summer_camp_agent/wechat_live_listener.py tests/test_wechat_bridge_config.py tests/test_wechat_live_listener.py
git commit -m "feat: 调试模式监听全部文本消息"
```

### Task 3：让会话为未命中消息生成可审核诊断

**Files:**
- Modify: `summer_camp_agent/workbench_session.py`
- Modify: `summer_camp_agent/workbench_trigger.py`
- Test: `tests/test_workbench_session.py`
- Test: `tests/test_workbench_trigger.py`

- [ ] **Step 1：编写未命中原因失败测试**

在 `tests/test_workbench_trigger.py` 增加：

```python
def test_unmatched_reason_codes_explain_all_missing_trigger_signals():
    event = text_event("今天天气不错")
    config = GroupConfig(
        group_name="测试群",
        keywords=["报名"],
        agent_mentions=["@Agent"],
    )

    decision = TriggerEngine(config).decide(event)
    reasons = unmatched_reason_codes(event, config, decision)

    self.assertFalse(decision.should_process)
    self.assertEqual(
        reasons,
        [
            "missing_question_mark",
            "missing_keyword",
            "missing_agent_mention",
        ],
    )
```

- [ ] **Step 2：编写调试模式强制审核失败测试**

在 `tests/test_workbench_session.py` 使用真实 `WorkbenchSession`：

```python
def test_debug_review_mode_generates_card_for_unmatched_message_and_never_auto_sends():
    session = make_session(mode="auto", keywords=["报名"])
    item = session.process_event(
        chat_event("evt-debug", "今天天气不错"),
        debug_review_mode=True,
    )

    self.assertFalse(item.trigger.should_process)
    self.assertEqual(item.reply_decision.mode, "draft")
    self.assertTrue(item.reply_decision.requires_review)
    self.assertEqual(item.review_card.original_question, "今天天气不错")
```

再用命中高置信 FAQ：

```python
def test_debug_review_mode_turns_high_confidence_faq_into_draft():
    item = session.process_event(
        chat_event("evt-faq", "报名入口在哪里？"),
        debug_review_mode=True,
    )
    self.assertEqual(item.review_card.action, "auto_reply")
    self.assertEqual(item.reply_decision.mode, "draft")
    self.assertTrue(item.reply_decision.requires_review)
```

- [ ] **Step 3：运行测试并确认缺少接口**

Run:

```powershell
python -m unittest tests.test_workbench_trigger tests.test_workbench_session -v
```

Expected: FAIL，原因是 `unmatched_reason_codes` 不存在，且
`process_event` 不接受 `debug_review_mode`。

- [ ] **Step 4：实现诊断和强制审核决策**

在 `workbench_trigger.py` 增加：

```python
def unmatched_reason_codes(
    event: ChatEvent,
    config: GroupConfig,
    decision: TriggerDecision | None = None,
) -> list[str]:
    current = decision or TriggerEngine(config).decide(event)
    if current.should_process:
        return []
    return [
        "missing_question_mark",
        "missing_keyword",
        "missing_agent_mention",
    ]
```

在 `WorkbenchSession.process_event` 增加关键字参数：

```python
def process_event(
    self,
    event: ChatEvent,
    *,
    debug_review_mode: bool = False,
) -> WorkbenchItem:
```

调试模式下无论 `trigger.should_process` 都调用 `review.create_card`；随后强制：

```python
if debug_review_mode:
    decision = ReplyDecision(
        mode="draft",
        reply=card.reply,
        source=card.source,
        confidence=card.confidence,
        reason=card.reason,
        requires_review=True,
    )
else:
    decision = self.reply_modes.decide(trigger, card)
```

原有人工安全兜底仍生成审核卡，但不在调试模式自动升级或发送。

- [ ] **Step 5：运行会话和触发测试**

Run:

```powershell
python -m unittest tests.test_workbench_trigger tests.test_workbench_session -v
```

Expected: 全部 PASS。

- [ ] **Step 6：提交会话调试决策**

```powershell
git add summer_camp_agent/workbench_trigger.py summer_camp_agent/workbench_session.py tests/test_workbench_trigger.py tests/test_workbench_session.py
git commit -m "feat: 为未命中消息生成调试审核卡"
```

### Task 4：接入消息库、迁移旧收件箱和更新处理状态

**Files:**
- Modify: `summer_camp_agent/workbench_api.py`
- Modify: `summer_camp_agent/workbench_presenter.py`
- Modify: `.gitignore`
- Test: `tests/test_workbench_api.py`

- [ ] **Step 1：编写重启不重新分析和历史保留失败测试**

在 `tests/test_workbench_api.py` 使用计数审核器：

```python
def test_restart_restores_persisted_snapshot_without_reprocessing_ai():
    analyzer = CountingSemanticAnalyzer()
    first = make_state(root, semantic_analyzer=analyzer)
    first.wechat_listener = FakeListener([chat_event("evt-1", "报名入口在哪里？")])
    first.poll_wechat_once()
    calls_after_first_run = analyzer.calls

    restarted = make_state(root, semantic_analyzer=analyzer)
    restored = restarted.list_items()["items"]

    self.assertEqual(analyzer.calls, calls_after_first_run)
    self.assertEqual(restored[0]["message_id"], "evt-1")
    self.assertEqual(restored[0]["review_status"], "pending_review")
```

完成状态测试：

```python
def test_confirm_sent_updates_same_message_and_moves_it_to_history():
    state = make_state(root)
    item = state.ask("报名入口在哪里？")["item"]

    state.confirm_sent(item["event_id"], item["reply"])

    self.assertEqual(state.list_items()["items"], [])
    history = state.list_items(scope="all")["items"]
    self.assertEqual(len(history), 1)
    self.assertEqual(history[0]["event_id"], item["event_id"])
    self.assertEqual(history[0]["review_status"], "sent")
```

增加以下独立测试：

- `save_candidate` 成功后为 `candidate_saved`。
- `escalate` 后为 `escalated`。
- `complete_review` 后为 `review_completed`。
- `paste_reply` 后仍为 `pending_review`。
- 自动发送失败后仍为 `pending_review`。
- 重复监听相同 `event_id` 不新增且不重置完成状态。

- [ ] **Step 2：编写调试模式全量待审核和禁止发布失败测试**

```python
def test_debug_mode_persists_unmatched_message_with_confidence_and_reason():
    state = make_state(root, debug_review_mode=True)
    state.wechat_listener = FakeListener([chat_event("evt-unmatched", "今天天气不错")])

    item = state.poll_wechat_once()["items"][0]

    self.assertEqual(item["review_status"], "pending_review")
    self.assertEqual(item["match_status"], "unmatched")
    self.assertEqual(
        item["unmatched_reasons"],
        [
            "missing_question_mark",
            "missing_keyword",
            "missing_agent_mention",
        ],
    )
    self.assertIn("faq_confidence", item)
    self.assertIn("rag_confidence", item)
    self.assertIn("semantic_confidence", item)
```

高置信 FAQ 对照：

```python
def test_debug_mode_blocks_auto_publish_for_high_confidence_faq():
    state = make_auto_send_state(root, debug_review_mode=True)
    state.paste_adapter = FakePasteAdapter()
    state.wechat_listener = FakeListener([chat_event("evt-faq", "报名入口在哪里？")])

    item = state.poll_wechat_once()["items"][0]

    self.assertEqual(item["review_status"], "pending_review")
    self.assertEqual(item["mode"], "draft")
    self.assertEqual(state.paste_adapter.sent, [])
    with self.assertRaisesRegex(ValueError, "调试审核模式"):
        state.publish_reply(item["event_id"], item["reply"])
```

- [ ] **Step 3：编写旧 JSONL 迁移失败测试**

```python
def test_legacy_inbox_migrates_once_and_keeps_original_file():
    inbox_path.write_text(
        json.dumps(asdict(chat_event("evt-legacy", "旧消息")), ensure_ascii=False)
        + "\n{bad-json}\n",
        encoding="utf-8",
    )
    analyzer = CountingSemanticAnalyzer()

    first = make_state(root, inbox_path=inbox_path, semantic_analyzer=analyzer)
    first_call_count = analyzer.calls
    second = make_state(root, inbox_path=inbox_path, semantic_analyzer=analyzer)

    self.assertTrue(inbox_path.exists())
    self.assertEqual(analyzer.calls, first_call_count)
    self.assertEqual(
        [row["event_id"] for row in second.list_items()["items"]],
        ["evt-legacy"],
    )
```

- [ ] **Step 4：运行 API 测试并确认当前实现删除记录且缺少新接口**

Run:

```powershell
python -m unittest tests.test_workbench_api -v
```

Expected: FAIL，原因包括缺少消息数据库参数、历史查询、审核状态字段和新状态动作。

- [ ] **Step 5：在 API 状态中接入 SQLite**

新增默认路径：

```python
DEFAULT_MESSAGE_DB_PATH = PROJECT_ROOT / "data" / "workbench_messages.db"
```

`WorkbenchApiState.__init__` 增加：

```python
message_db_path: str | Path | None = None
```

隔离测试目录下默认使用 `candidate_path.parent / "workbench_messages.db"`。
初始化顺序：

1. 创建 `WorkbenchSession`。
2. 创建 `WorkbenchMessageStore`。
3. 执行一次旧收件箱迁移。
4. 从 `message_store.list_pending()` 恢复 `self.items`，不调用
   `session.process_event`。

新增内部方法：

```python
def _process_and_persist(self, event: ChatEvent) -> WorkbenchItem:
    existing = self.message_store.get(event.event_id)
    if existing is not None:
        return existing.item
    item = self.session.process_event(
        event,
        debug_review_mode=self.wechat_config.debug_review_mode,
    )
    unmatched = unmatched_reason_codes(event, self.group_config, item.trigger)
    self.message_store.insert_pending(
        item,
        match_status="matched" if item.trigger.should_process else "unmatched",
        unmatched_reasons=unmatched,
    )
    return item
```

所有演示、导入、手动输入和监听入口都调用该方法。

- [ ] **Step 6：实现列表范围、状态更新和序列化**

`list_items` 改为：

```python
def list_items(
    self,
    *,
    scope: str = "pending",
    review_status: str = "",
) -> dict[str, Any]:
```

- `scope="pending"` 查询 `list_pending()`。
- `scope="all"` 查询 `list_all(review_status or None)`。
- 其他值抛出 `ValueError("scope 必须是 pending 或 all")`。

处理动作统一在业务操作成功后调用：

```python
def _complete_message(
    self,
    event_id: str,
    review_status: str,
    review_action: str,
    review_note: str,
) -> StoredWorkbenchMessage:
    record = self.message_store.complete(
        event_id,
        review_status,
        review_action,
        review_note,
    )
    self.items = [
        item for item in self.items
        if item.event.event_id != event_id
    ]
    return record
```

新增：

```python
def escalate(self, event_id: str, note: str = "") -> dict[str, Any]:
    ...

def complete_review(self, event_id: str, note: str = "") -> dict[str, Any]:
    ...
```

`serialize_item` 接受 `StoredWorkbenchMessage`，新增设计文档规定的消息、审核、
命中和时间字段；`replied` 由 `review_status == "sent"` 推导。

- [ ] **Step 7：实现旧收件箱幂等迁移**

新增 `_migrate_legacy_inbox`：

```python
def _migrate_legacy_inbox(self) -> None:
    if self.message_store.get_metadata("legacy_inbox_migrated") == "true":
        return
    for event in self.inbox_store.load():
        self._process_and_persist(event)
    self.message_store.set_metadata("legacy_inbox_migrated", "true")
```

只有循环正常结束才写迁移标记。`WorkbenchInboxStore.load` 已忽略损坏行，旧文件不再由
`_mark_event_replied` 删除或重写。

- [ ] **Step 8：让调试模式阻止所有自动发布**

在 `_append_listener_events` 中，调试模式不调用 `publish_reply`。在
`publish_reply` 开头增加：

```python
if self.wechat_config.debug_review_mode:
    raise ValueError("调试审核模式已开启，禁止自动发布。")
```

正式模式自动发布成功后更新 `sent`，同时保留监听器 `mark_replied` 防回环逻辑。

- [ ] **Step 9：更新状态标签和忽略规则**

在 `.gitignore` 增加：

```text
data/workbench_messages.db
data/workbench_messages.db-wal
data/workbench_messages.db-shm
```

在 `workbench_presenter.py` 增加审核状态中文映射和未命中中文映射：

```python
REVIEW_STATUS_LABELS = {
    "pending_review": "待审核",
    "sent": "已发送",
    "escalated": "已转人工",
    "candidate_saved": "已保存候选",
    "review_completed": "审核完成",
}
UNMATCHED_REASON_LABELS = {
    "missing_question_mark": "无问号",
    "missing_keyword": "无配置关键词",
    "missing_agent_mention": "未 @Agent",
}
```

- [ ] **Step 10：运行 API、存储和会话回归**

Run:

```powershell
python -m unittest tests.test_workbench_message_store tests.test_workbench_api tests.test_workbench_session tests.test_workbench_modes -v
```

Expected: 全部 PASS。

- [ ] **Step 11：提交 API 状态机**

```powershell
git add .gitignore summer_camp_agent/workbench_api.py summer_camp_agent/workbench_presenter.py tests/test_workbench_api.py
git commit -m "feat: 持久化工作台消息处理状态"
```

### Task 5：扩展 HTTP、主进程和 preload 接口

**Files:**
- Modify: `summer_camp_agent/workbench_api.py`
- Modify: `desktop/src/shared/types.ts`
- Modify: `desktop/src/main/main.ts`
- Modify: `desktop/src/preload/preload.ts`
- Test: `tests/test_workbench_api.py`
- Test: `desktop/tests/static.test.mjs`

- [ ] **Step 1：编写 HTTP 查询和状态动作失败测试**

在 Python HTTP 测试中增加：

```python
def test_items_route_accepts_scope_and_review_status_query():
    response = request_json(
        server_url + "/api/items?scope=all&review_status=sent"
    )
    self.assertEqual(
        {item["review_status"] for item in response["items"]},
        {"sent"},
    )

def test_escalate_and_complete_review_routes_update_message():
    escalated = post_json(
        server_url + "/api/messages/escalate",
        {"event_id": "evt-1", "note": "需要老师处理"},
    )
    completed = post_json(
        server_url + "/api/messages/complete-review",
        {"event_id": "evt-2", "note": "无需回复"},
    )
    self.assertEqual(escalated["item"]["review_status"], "escalated")
    self.assertEqual(completed["item"]["review_status"], "review_completed")
```

- [ ] **Step 2：编写桌面窄接口静态失败测试**

在 `desktop/tests/static.test.mjs` 断言：

```javascript
assert.match(types, /getItems\\(scope\\?: 'pending' \\| 'all'/)
assert.match(types, /escalateMessage\\(eventId: string, note\\?: string\\)/)
assert.match(types, /completeReview\\(eventId: string, note\\?: string\\)/)
assert.match(preload, /workbench:escalateMessage/)
assert.match(preload, /workbench:completeReview/)
assert.match(main, /\\/api\\/messages\\/escalate/)
assert.match(main, /\\/api\\/messages\\/complete-review/)
```

- [ ] **Step 3：运行测试并确认路由和方法不存在**

Run:

```powershell
python -m unittest tests.test_workbench_api -v
Set-Location desktop
npm.cmd test
Set-Location ..
```

Expected: Python 和桌面静态测试均 FAIL，原因是新查询和动作接口不存在。

- [ ] **Step 4：实现 HTTP 路由**

`do_GET` 使用：

```python
parsed = urlparse(self.path)
path = parsed.path
query = parse_qs(parsed.query)
```

`/api/items` 调用：

```python
state.list_items(
    scope=str(query.get("scope", ["pending"])[0]),
    review_status=str(query.get("review_status", [""])[0]),
)
```

`do_POST` 增加：

```python
if path == "/api/messages/escalate":
    self._send_json(
        state.escalate(
            str(payload.get("event_id") or ""),
            str(payload.get("note") or ""),
        )
    )
    return
if path == "/api/messages/complete-review":
    self._send_json(
        state.complete_review(
            str(payload.get("event_id") or ""),
            str(payload.get("note") or ""),
        )
    )
    return
```

- [ ] **Step 5：扩展 TypeScript 类型和服务**

`WorkbenchItem` 增加设计字段，并定义：

```typescript
export type MessageScope = 'pending' | 'all'

export interface MessageActionResult extends ActionResult {
  item: WorkbenchItem
}
```

`DesktopApi` 使用：

```typescript
getItems(scope?: MessageScope, reviewStatus?: string): Promise<WorkbenchItemsPayload>
escalateMessage(eventId: string, note?: string): Promise<MessageActionResult>
completeReview(eventId: string, note?: string): Promise<MessageActionResult>
```

主进程请求查询参数使用 `URLSearchParams`，preload 只暴露以上窄方法，不暴露任意 URL。

- [ ] **Step 6：运行 Python 路由、桌面测试和类型检查**

Run:

```powershell
python -m unittest tests.test_workbench_api -v
Set-Location desktop
npm.cmd test
npm.cmd run typecheck
Set-Location ..
```

Expected: 全部 PASS。

- [ ] **Step 7：提交接口层**

```powershell
git add summer_camp_agent/workbench_api.py tests/test_workbench_api.py desktop/src/shared/types.ts desktop/src/main/main.ts desktop/src/preload/preload.ts desktop/tests/static.test.mjs
git commit -m "feat: 增加消息历史与审核状态接口"
```

### Task 6：实现桌面调试审核界面

**Files:**
- Modify: `desktop/src/renderer/App.tsx`
- Modify: `desktop/src/renderer/styles.css`
- Modify: `desktop/src/shared/types.ts`
- Test: `desktop/tests/static.test.mjs`

- [ ] **Step 1：编写调试开关、范围筛选和处理按钮静态失败测试**

在 `desktop/tests/static.test.mjs` 增加：

```javascript
test('workbench exposes debug review state and completion actions', () => {
  assert.match(renderer, /调试审核模式：禁止自动发送/)
  assert.match(renderer, /待审核/)
  assert.match(renderer, /全部历史/)
  assert.match(renderer, /转人工/)
  assert.match(renderer, /审核完成/)
  assert.match(renderer, /未命中原因/)
  assert.match(renderer, /消息主键/)
  assert.match(renderer, /debug_review_mode/)
})
```

- [ ] **Step 2：运行桌面测试并确认界面元素不存在**

Run:

```powershell
Set-Location desktop
npm.cmd test
Set-Location ..
```

Expected: FAIL，缺少调试提示、范围切换和新按钮。

- [ ] **Step 3：增加配置开关和调试提示**

在微信桥接设置中增加：

```tsx
<Toggle
  label="调试审核模式"
  checked={wechatForm.debug_review_mode}
  onChange={(value) => setWechatForm((current) => ({
    ...current,
    debug_review_mode: value
  }))}
/>
```

保存配置时包含 `debug_review_mode`。工作台顶部在开启时显示：

```tsx
{status.engine.debug_review_mode && (
  <div className="debug-review-banner">
    调试审核模式：所有文本消息进入待审核，禁止自动发送
  </div>
)}
```

自动发布按钮设置 `disabled={status.engine.debug_review_mode}`。

- [ ] **Step 4：增加列表范围与状态筛选**

新增状态：

```typescript
const [messageScope, setMessageScope] = useState<MessageScope>('pending')
const [reviewStatusFilter, setReviewStatusFilter] = useState('')
```

`refreshItems` 调用：

```typescript
getItems(messageScope, messageScope === 'all' ? reviewStatusFilter : '')
```

列表头增加“待审核 / 全部历史”切换；全部历史视图提供
`sent`、`escalated`、`candidate_saved`、`review_completed` 筛选。

- [ ] **Step 5：增加诊断展示和处理动作**

消息行同时显示：

```tsx
<span>{item.review_status_label}</span>
<span>{item.match_status_label}</span>
```

详情区增加：

```tsx
<DetailRow label="消息主键" value={item.message_id} />
<DetailRow label="审核状态" value={item.review_status_label} />
<DetailRow label="命中状态" value={item.match_status_label} />
<DetailRow
  label="未命中原因"
  value={item.unmatched_reason_labels.join('、') || '无'}
/>
```

新增操作：

```tsx
async function escalateMessage() {
  await runAction('正在标记转人工...', async () => {
    await getDesktopMethod('escalateMessage')(selected.event_id)
    await refreshItems()
    setMessage('已转人工')
  })
}

async function completeReview() {
  await runAction('正在完成审核...', async () => {
    await getDesktopMethod('completeReview')(selected.event_id)
    await refreshItems()
    setMessage('审核已完成')
  })
}
```

仅 `pending_review` 记录显示处理按钮，历史记录只读。

- [ ] **Step 6：增加可读样式**

在 `styles.css` 增加 `.debug-review-banner`、`.scope-tabs`、
`.message-status-pair` 和禁用按钮样式。窄窗口下范围按钮允许换行，状态标签不挤压消息正文。

- [ ] **Step 7：运行桌面测试、类型检查和生产构建**

Run:

```powershell
Set-Location desktop
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
Set-Location ..
```

Expected: 测试、类型检查和构建全部成功。

- [ ] **Step 8：提交桌面界面**

```powershell
git add desktop/src/renderer/App.tsx desktop/src/renderer/styles.css desktop/src/shared/types.ts desktop/tests/static.test.mjs
git commit -m "feat: 增加调试审核工作台界面"
```

### Task 7：端到端验证、文档和完整回归

**Files:**
- Create: `scripts/verify_debug_review_workflow.py`
- Create: `tests/test_debug_review_workflow.py`
- Modify: `docs/technical-architecture.md`

- [ ] **Step 1：编写端到端失败测试**

场景使用真实 SQLite、真实触发引擎和工作台状态，替换微信发送适配器与外部 AI：

```python
def test_debug_review_workflow_persists_diagnoses_and_completes_messages():
    result = run_verification(root)

    self.assertEqual(result["pending_before_actions"], 3)
    self.assertEqual(result["auto_sent"], [])
    self.assertEqual(
        result["unmatched"]["unmatched_reason_labels"],
        ["无问号", "无配置关键词", "未 @Agent"],
    )
    self.assertEqual(result["faq"]["review_status"], "pending_review")
    self.assertGreaterEqual(result["faq"]["faq_confidence"], 0.90)
    self.assertIn("semantic_confidence", result["rag"])

    self.assertEqual(
        result["history_statuses"],
        {
            "evt-unmatched": "review_completed",
            "evt-faq": "sent",
            "evt-rag": "escalated",
        },
    )
    self.assertEqual(result["pending_after_actions"], 0)
    self.assertEqual(result["pending_after_restart"], 0)
```

- [ ] **Step 2：运行端到端测试并确认验证脚本不存在**

Run:

```powershell
python -m unittest tests.test_debug_review_workflow -v
```

Expected: FAIL，原因是 `scripts.verify_debug_review_workflow` 不存在。

- [ ] **Step 3：实现可执行验证脚本**

脚本构造三条消息：

1. `"今天天气不错"`：未命中，最终点击审核完成。
2. `"线下夏令营在哪？"`：FAQ 高置信，调试模式不自动发送，随后确认已发送。
3. `"夏令营期间我碰到问题该找谁处理？"`：语义 RAG 场景，随后转人工。

返回每条消息的主键、审核状态、命中状态、三类置信度、未命中原因、发送记录和重启后数量。脚本入口：

```python
def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        result = run_verification(Path(directory))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
```

- [ ] **Step 4：运行端到端测试和脚本**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_debug_review_workflow -v
python -m scripts.verify_debug_review_workflow
```

Expected: 测试 PASS；脚本显示三条消息最初全部待审核、无自动发送，处理后状态正确且重启不重新进入待审核。

- [ ] **Step 5：更新中文技术架构**

在 `docs/technical-architecture.md` 记录：

- `workbench_messages.db` 与 `event_id` 主键。
- 审核状态和命中状态相互独立。
- 调试模式监听边界与自动发送禁用规则。
- 未命中原因和三类置信度定义。
- 旧 JSONL 幂等迁移和保留策略。
- 本地聊天数据不得提交或同步。

- [ ] **Step 6：运行完整 Python 回归**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: 全部 PASS。

- [ ] **Step 7：运行桌面端完整验证**

Run:

```powershell
Set-Location desktop
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
Set-Location ..
```

Expected: 全部成功。

- [ ] **Step 8：运行差异、数据库忽略和密钥检查**

Run:

```powershell
git diff --check
git check-ignore data/workbench_messages.db data/workbench_messages.db-wal data/workbench_messages.db-shm
rg -n -g '!desktop/node_modules/**' -g '!desktop/dist/**' "Bearer [A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}" summer_camp_agent tests scripts docs data desktop
git status --short
```

Expected: 无格式错误；三个数据库文件均被忽略；无真实密钥命中；状态只包含本计划文件。

- [ ] **Step 9：提交验证与文档**

```powershell
git add scripts/verify_debug_review_workflow.py tests/test_debug_review_workflow.py docs/technical-architecture.md
git commit -m "test: 验证本地消息调试审核闭环"
```

- [ ] **Step 10：输出验收报告**

报告必须包含：

- SQLite 数据库路径和唯一主键定义。
- 五种审核状态及其处理动作。
- 调试模式未命中消息的三个具体原因。
- FAQ/RAG/AI 置信度展示结果。
- 调试模式禁止自动发送的验证证据。
- 状态更新后默认待审核列表移除、历史保留和重启恢复证据。
- Python、桌面测试、类型检查和构建结果。
