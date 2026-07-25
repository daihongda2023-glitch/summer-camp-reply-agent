# 本地消息状态与调试审核模式设计

## 背景

当前工作台已经把未回复消息写入 `data/workbench_inbox.jsonl`，但该文件只承担临时收件箱职责：

- 记录只有原始 `ChatEvent`，不包含审核状态、命中诊断、置信度和草稿。
- 自动发送或运营确认发送后会删除记录，无法查看完整处理历史。
- 状态主要由内存、回复日志和监听器已回复标记共同推导，缺少一条可直接更新的消息主记录。
- 未命中问号、关键词或 `@Agent` 规则的消息会在正式链路中被过滤，不便于调试规则覆盖率。

本设计将工作台消息改为本地 SQLite 持久化状态机，并新增全量调试审核模式。

## 目标

1. 每条工作台消息以稳定的 `event_id` 作为唯一主键。
2. 原始消息、审核状态、命中诊断、回答诊断和草稿保存在同一条本地主记录中。
3. 处理动作更新原记录状态，不再删除已处理消息。
4. 调试模式下，目标群其他成员的所有文本消息均进入待审核。
5. 未命中原有触发规则的消息标记为 `unmatched`，并给出明确原因。
6. 调试模式禁止自动发送，便于人工检查 FAQ、RAG、AI 和触发规则。
7. 工作台重启后直接恢复持久化结果，不重新调用 AI。
8. 安全迁移现有 `workbench_inbox.jsonl` 中的未处理消息。

## 非目标

- 不把自己的消息、系统消息、图片、文件或其他非文本消息加入审核队列。
- 不修改 FAQ 和 RAG 资料本身。
- 不在本阶段增加远程数据库、云同步或多用户权限。
- 不自动清理历史消息；调试阶段长期保留本地记录。
- 不把“填入微信”视为处理完成。

## 方案选择

采用 SQLite 本地消息库，数据库文件为：

```text
data/workbench_messages.db
```

选择理由：

- SQLite 原生支持唯一主键、事务、条件更新和状态查询。
- Python 标准库自带 `sqlite3`，无需新增第三方依赖。
- 状态更新无需重写整个 JSONL 文件。
- 可以直接查询待审核和历史记录。
- 比追加式事件日志更符合当前单机工作台的复杂度。

未采用的方案：

- JSONL 快照：实现简单，但状态更新需要重写文件，并发和数据增长后的可靠性较差。
- 追加式状态事件日志：审计能力强，但需要额外计算每条消息的当前状态，超出当前需要。

## 数据模型

新增表 `workbench_messages`。

同时新增 `workbench_metadata` 键值表，保存数据库结构版本和
`legacy_inbox_migrated` 迁移标记。应用启动时先以事务创建或升级表结构，
再读取业务消息。

### 主键

`event_id TEXT PRIMARY KEY`

监听器产生的微信消息沿用稳定的上游事件 ID。手动输入消息继续使用当前生成的事件 ID。接口和桌面端同时将该值展示为消息唯一主键。

### 原始消息字段

- `group_id_hash`
- `group_name`
- `sender_alias`
- `sender_role`
- `message_time`
- `content`
- `raw_type`
- `source`

### 审核状态字段

`review_status` 允许以下值：

- `pending_review`：等待人工审核。
- `sent`：自动发送成功或运营确认已发送。
- `escalated`：已转人工。
- `candidate_saved`：已保存为候选。
- `review_completed`：无需发送，审核已完成。

同时保存：

- `review_action`：最后一次明确处理动作。
- `review_note`：处理说明或失败原因。
- `created_at`
- `updated_at`
- `completed_at`

新消息一律创建为 `pending_review`。只有明确处理动作才能迁移到完成状态。

### 命中诊断字段

`match_status` 允许：

- `matched`：满足原有触发规则。
- `unmatched`：未满足原有触发规则。

同时保存：

- `trigger_reasons`
- `matched_keywords`
- `unmatched_reasons`

未命中原因按实际判断生成，例如：

- `missing_question_mark`：无问号。
- `missing_keyword`：无配置关键词。
- `missing_agent_mention`：未 `@Agent` 或夏令营助手。

界面显示中文说明，不只显示内部代码。

### 回答诊断字段

保存生成审核卡时的结果：

- `engine_action`
- `recommendation`
- `intent`
- `answer_source`
- `reply`
- `confidence`
- `reason`
- `generation_mode`
- `generation_model`
- `generation_error`
- `semantic_status`
- `semantic_intent`
- `semantic_question`
- `semantic_confidence`
- `semantic_model`
- `semantic_error`
- `faq_confidence`
- `rag_confidence`
- `rag_query`

数组字段使用 JSON 文本保存。布尔值使用 SQLite 整数保存。

## 调试审核模式

新增独立配置：

```text
debug_review_mode=true
```

当前默认开启，并在桌面配置页提供开关。

### 监听边界

开启时，监听目标群内其他成员的所有文本消息：

- 不要求包含问号。
- 不要求命中配置关键词。
- 不要求 `@Agent`。

继续排除：

- 当前登录账号自己发送的消息。
- 已识别为系统消息的内容。
- 图片、语音、文件等非文本消息。
- 已由本系统回复并记录为回环的消息。

### 处理规则

每条进入调试模式的消息都执行：

1. 持久化原始消息。
2. 执行原有触发规则，产生 `matched` 或 `unmatched` 诊断。
3. 执行 FAQ、RAG 和 AI 语义分析，生成草稿与置信度。
4. 将 `review_status` 固定为 `pending_review`。
5. 禁止自动发布，即使原配置为 `auto_send` 且答案为高置信 FAQ 或官方 RAG。

调试模式只改变队列准入和发送决策，不改变 FAQ/RAG 取证安全边界。

### 正式模式

关闭 `debug_review_mode` 后恢复现有行为：

- 只处理命中原有触发规则的消息。
- 根据半自动或自动发送配置决定草稿和发布。
- 处理结果仍写入 SQLite 消息库并保留历史。

## 状态迁移

### 新消息

```text
不存在 -> pending_review
```

### 发送成功

```text
pending_review -> sent
```

触发动作：

- 自动发布返回 `sent_verified` 或 `sent_unverified`。
- 运营点击“我已发送”。

### 保存候选

```text
pending_review -> candidate_saved
```

只有候选回复成功写入候选库后才更新消息状态。

### 转人工

```text
pending_review -> escalated
```

由新增“转人工”操作触发。

### 审核完成

```text
pending_review -> review_completed
```

用于无需回复但已完成判断的消息。

### 不改变状态的动作

- 选择消息。
- 编辑草稿但未执行处理动作。
- “填入微信”。
- 发送、候选保存或数据库操作失败。

## 幂等与一致性

1. 同一 `event_id` 重复拉取时不得新增记录。
2. 重复拉取可以补齐缺失的原始字段，但不能把完成状态重置为 `pending_review`。
3. 新建消息、保存诊断和更新审核状态均使用 SQLite 事务。
4. 数据库写入成功后才更新工作台内存视图。
5. 状态更新使用主键和预期当前状态约束，避免重复操作覆盖已完成结果。
6. 重启后从数据库读取已经保存的审核卡快照，不重新调用 AI。
7. 数据库文件加入 `.gitignore`，不进入版本库。

## 旧收件箱迁移

启动时检查现有 `data/workbench_inbox.jsonl`：

1. 读取可解析的 `ChatEvent`。
2. 以 `event_id` 执行幂等插入。
3. 迁移记录统一标记为 `pending_review`。
4. 命中和回答诊断通过当前引擎补齐一次并写入数据库。
5. 全部有效记录迁移成功后，在 `workbench_metadata` 写入
   `legacy_inbox_migrated=true`。
6. 原 JSONL 文件保留为备份，不删除、不清空。
7. 再次启动时跳过已完成迁移，不重复调用 AI。

单条损坏 JSONL 不阻断其他有效记录迁移，并记录安全化错误信息。

## API 与桌面端

### 列表查询

消息接口支持：

- 默认查询 `pending_review`。
- 查询全部历史。
- 按 `review_status` 过滤。

序列化结果新增：

- `message_id`，值等于 `event_id`。
- `review_status`
- `review_status_label`
- `match_status`
- `match_status_label`
- `unmatched_reasons`
- `unmatched_reason_labels`
- `created_at`
- `updated_at`
- `completed_at`

保留现有 `event_id`、`status` 和 `replied` 字段作为兼容字段。

### 操作接口

现有操作扩展：

- 自动发布成功和“我已发送”更新为 `sent`。
- 保存候选成功更新为 `candidate_saved`。

新增操作：

- 标记转人工。
- 标记审核完成。

所有状态接口返回更新后的消息，便于桌面端立即刷新。

### 界面

主列表默认显示待审核消息，并提供：

- “待审核”视图。
- “全部历史”视图。
- 按审核状态筛选。

消息行显示审核状态和命中状态。详情区显示：

- 消息唯一主键。
- 命中原因或未命中原因。
- AI 语义置信度。
- FAQ 匹配分。
- RAG 匹配分。
- 生成和语义降级原因。

回复操作区新增：

- “转人工”。
- “审核完成”。

调试模式开启时显示明确提示“调试审核模式：禁止自动发送”，并禁用自动发布按钮。

## 错误处理

- SQLite 无法打开或写入时，接口返回明确错误，不把内存状态标记为成功。
- 状态已完成时重复处理返回可理解的冲突信息，不覆盖第一次处理结果。
- AI 不可用时仍保存消息、语义错误和本地 FAQ/RAG 分数。
- 未命中触发规则不视为异常，而是正常诊断结果。
- 操作失败保留 `pending_review`，并把失败原因写入运行日志；不把失败动作写成完成状态。

## 测试与验收

### 存储测试

1. `event_id` 唯一主键阻止重复记录。
2. 状态更新修改同一条记录。
3. 完成状态不会被重复拉取重置。
4. 待审核与历史查询正确。
5. 数据库重启后恢复全部字段。
6. 非法状态和缺失主键被拒绝。

### 调试模式测试

1. 无问号、无关键词、未 `@Agent` 的普通文本进入 `pending_review`。
2. 该消息标记为 `unmatched`，包含三个未命中原因。
3. 高置信 FAQ 在调试模式下仍为 `pending_review`，不会调用发布适配器。
4. 自己的消息和非文本消息仍被过滤。
5. 关闭调试模式后恢复原有触发和发送行为。

### 状态动作测试

1. 自动发送成功和运营确认发送更新为 `sent`。
2. 保存候选更新为 `candidate_saved`。
3. 转人工更新为 `escalated`。
4. 审核完成更新为 `review_completed`。
5. 填入微信不改变状态。
6. 失败操作不改变状态。

### 迁移测试

1. 有效旧消息迁移为待审核。
2. 损坏行被忽略且不阻断其他消息。
3. 重复启动不重复记录、不重复分析。
4. 旧文件在迁移后仍保留。

### 完成前验证

- 运行完整 Python 测试。
- 运行桌面端静态测试、类型检查和生产构建。
- 执行调试模式端到端模拟：未命中、FAQ 命中、RAG 命中、状态迁移和重启恢复。
- 检查数据库文件和临时运行数据未进入 Git。
- 检查差异格式和密钥泄漏。

## 风险与边界

- 调试模式会保存更多群消息，数据库包含聊天内容，只能保存在当前受控本机，不应提交或同步。
- 长期保留会增加磁盘占用；当前不自动清理，后续可在用户明确提出后增加归档策略。
- `event_id` 的稳定性依赖上游监听器；手动输入使用本地生成的唯一 ID。
- 现有 `listener_state.json` 继续用于防回复回环，但不再承担工作台消息主状态职责。
