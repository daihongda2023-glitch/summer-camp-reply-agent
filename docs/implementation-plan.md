# 实现计划：夏令营自动回复 Agent MVP

## Overview

MVP 先做一个可本地验证、可运营半自动使用的夏令营答疑 agent。它基于官方资料和结构化 FAQ 回答学生高频问题，对不确定、过期、个人状态、投诉安全和技术作业问题转人工。企业微信接入采用适配器模式，先支持人工确认后的群内推送，再在官方接收消息方案确认后实现自动互动。

## Architecture Decisions

- 问答内核与企业微信适配层分离，避免被具体接入方式锁死。
- 第一版以结构化 FAQ 为主，不急着上复杂 RAG 或向量库。
- 默认保守回复：低置信、资料过期、资料冲突时不自动回答。
- 未命中记录必须由系统确认写入后才能在回复中说“已记录”；否则只说“建议标记为待补充”。

## Phase 0: 接入方式确认

### Task 1: 确认企业微信能力边界

**Description:** 确认当前企业微信环境支持哪种接入方式：群机器人 webhook、自建应用消息回调、会话内容存档、第三方平台，或只能先半自动运营。

**Acceptance criteria:**

- [ ] 明确是否能自动接收群内学生消息。
- [ ] 明确是否能在群内以 agent 身份回复。
- [ ] 明确频率限制、权限申请、合规要求和负责人。

**Verification:**

- [ ] 用官方文档或企业微信后台配置截图确认能力。
- [ ] 形成接入结论，更新 `docs/technical-architecture.md`。

**Dependencies:** None

**Files likely touched:**

- `docs/technical-architecture.md`
- `docs/decisions/ADR-001-enterprise-wechat-agent-architecture.md`

**Estimated scope:** Small

## Phase 1: 知识库结构化

### Task 2: 将种子 FAQ 转为结构化数据

**Description:** 将当前 Markdown FAQ 拆成可程序读取的知识条目，保留阶段、意图、同义问法、答案、来源、有效期和自动回复标记。

**Acceptance criteria:**

- [ ] 每条 FAQ 都有稳定 `id` 和 `intent`。
- [ ] 高风险信息包含 `source`、`source_date`、`last_updated`、`valid_until`。
- [ ] `auto_reply=false` 的条目必须有人工兜底原因。

**Verification:**

- [ ] 运行结构校验脚本，缺字段时失败。
- [ ] 抽查 10 条 FAQ，确认答案可直接发给学生。

**Dependencies:** None

**Files likely touched:**

- `knowledge/*.yaml` 或 `data/faq/*.yaml`
- `docs/knowledge-base/seed-faq.md`

**Estimated scope:** Medium

### Task 3: 建立资料接入校验规则

**Description:** 把 `source-intake-checklist.md` 中的维护原则落成检查规则，防止过期、无来源、冲突资料进入自动回复。

**Acceptance criteria:**

- [ ] 无来源条目不能标记为自动回复。
- [ ] 过期条目默认不能自动回复。
- [ ] 资料冲突条目必须进入待确认状态。

**Verification:**

- [ ] 构造缺来源、已过期、资料冲突样例，校验结果符合预期。

**Dependencies:** Task 2

**Files likely touched:**

- `scripts/validate-knowledge.*`
- `docs/source-intake-checklist.md`

**Estimated scope:** Medium

## Phase 2: 本地问答内核

### Task 4: 实现意图匹配与 FAQ 检索

**Description:** 实现最小问答内核：输入学生问题，输出命中的 FAQ、置信度、是否可自动回复和候选来源。

**Acceptance criteria:**

- [ ] 支持关键词和同义问法匹配。
- [ ] 低置信问题不强答，返回未命中。
- [ ] 返回结果包含资料来源和更新时间。

**Verification:**

- [ ] 用报名、费用、时间、地点、作业、个人状态等样例问题跑测试。

**Dependencies:** Task 2

**Files likely touched:**

- `src/core/retrieve.*`
- `tests/retrieve.*`

**Estimated scope:** Medium

### Task 5: 实现回复策略与人工升级判断

**Description:** 在检索前后执行回复策略，拦截个人状态、录取结果、安全医疗、投诉争议、技术作业代答和资料冲突问题。

**Acceptance criteria:**

- [ ] 命中必须转人工规则时不生成自动答案。
- [ ] 资料未明确时生成保守回复。
- [ ] 没有日志写入能力时不说“已记录”。

**Verification:**

- [ ] 覆盖每类人工升级样例。
- [ ] 覆盖资料未明确和低置信样例。

**Dependencies:** Task 4

**Files likely touched:**

- `src/core/policy.*`
- `src/core/compose-reply.*`
- `tests/policy.*`

**Estimated scope:** Medium

## Checkpoint: 本地内核可用

- [ ] 20-30 个常见学生问题可稳定分类。
- [ ] 可回答问题给出简洁回复。
- [ ] 不该回答的问题全部转人工或待确认。
- [ ] 无来源、过期、冲突资料不会自动回复。

## Phase 3: 运营半自动模式

### Task 6: 建立人工确认工作流

**Description:** 提供一个简单入口，让运营粘贴学生问题，agent 生成建议回复和转人工理由，运营确认后再发送。

**Acceptance criteria:**

- [ ] 运营能看到建议回复、资料来源、是否自动回复建议。
- [ ] 运营能选择发送、修改、转人工或标记待补充。
- [ ] 未命中问题能进入待补充清单。

**Verification:**

- [ ] 用真实群问题演练一次完整流程。

**Dependencies:** Task 5

**Files likely touched:**

- `src/app/*` 或 `src/cli/*`
- `docs/enterprise-wechat-reply-policy.md`

**Estimated scope:** Medium

### Task 7: 接入企业微信群出站推送

**Description:** 在官方能力确认后，实现企业微信群出站消息发送，用于主动提醒或运营确认后的回复。

**Acceptance criteria:**

- [ ] 支持发送文本或 markdown 消息。
- [ ] 支持失败重试和错误记录。
- [ ] 支持事件去重，避免重复提醒。

**Verification:**

- [ ] 在测试群发送一条人工确认后的 FAQ 回复。
- [ ] 模拟失败响应，确认不会重复刷屏。

**Dependencies:** Task 1, Task 6

**Files likely touched:**

- `src/adapters/wecom-outbound.*`
- `tests/wecom-outbound.*`

**Estimated scope:** Medium

## Phase 4: 企业微信互动模式

### Task 8: 实现企业微信入站适配器

**Description:** 在确认官方接收消息方案后，将企业微信消息转换成内部标准消息格式，并复用本地问答内核。

**Acceptance criteria:**

- [ ] 能识别群、发送者、消息文本、是否被 @。
- [ ] 能带入最近上下文，但不存储不必要的个人隐私。
- [ ] 能处理验签、解密、重试或去重等官方要求。

**Verification:**

- [ ] 在测试群完成被 @ 问答流程。
- [ ] 模拟重复回调，确认不会重复回复。

**Dependencies:** Task 1, Task 5

**Files likely touched:**

- `src/adapters/wecom-inbound.*`
- `src/server/*`
- `tests/wecom-inbound.*`

**Estimated scope:** Medium

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| 企业微信群 webhook 只能出站，不能接收学生问题 | High | 第一版先做本地内核和运营半自动模式；接收能力确认后再做互动适配器 |
| 资料更新不及时导致错答 | High | 所有高风险信息必须有来源、更新时间、有效期；过期自动停答 |
| 自动回复打扰群讨论 | Medium | 默认只在被 @ 或高置信关键词时回复；同群同意图冷却 |
| 学生问个人状态或录取结果 | High | 策略层强制转人工，不在群内暴露个人信息 |
| 技术问题越界成作业代答 | Medium | 技术类只做资料导航和概念解释，具体作业答案转助教 |

## Open Questions

- 企业微信最终采用哪种接入方式？
- 是否先做运营半自动版本供组委会试用？
- 知识库第一版使用 YAML、JSON 还是 Markdown front matter？
- 未命中问题由谁负责每日审核？
- 主动提醒是否必须人工确认后发送？

