# 夏令营自动回复 Agent 文档索引

本目录用于沉淀企业微信群自动回复 agent 的产品方向、回复策略、知识库结构和资料接入清单。当前资料主要来自根目录招募文章，后续正式群公告、课程说明、作业说明、面试通知和线下手册应持续补充到知识库。

## 阅读顺序

1. [夏令营自动回复 Agent](ideas/summer-camp-reply-agent.md)：说明产品定位、MVP 范围、不做什么和待验证问题。
2. [企业微信群回复策略](enterprise-wechat-reply-policy.md)：说明什么时候回复、怎么回复、什么情况必须转人工。
3. [技术架构草案](technical-architecture.md)：说明问答内核、企业微信适配层、消息流程和接入风险。
4. [实现计划](implementation-plan.md)：按阶段拆解 MVP 任务、验收标准和风险。
5. [夏令营 Agent 知识库结构](knowledge-base/README.md)：定义阶段分类、字段规范和资料优先级。
6. [种子 FAQ](knowledge-base/seed-faq.md)：当前可直接用于自动回复的基础问答。
7. [后续资料接入清单](source-intake-checklist.md)：后续拿到新资料时，用它检查哪些信息还缺。

## 决策记录

- [ADR-001: 采用问答内核与企业微信适配层分离的架构](decisions/ADR-001-enterprise-wechat-agent-architecture.md)

## 本地开发命令

当前已实现不依赖企业微信的本地问答内核，可先用于知识库校验和运营半自动演练。

| 命令 | 说明 |
| --- | --- |
| `python -m unittest discover -s tests` | 运行完整测试 |
| `python -m summer_camp_agent.cli validate` | 校验默认知识库 `data/faq.json` |
| `python scripts/validate_knowledge.py data/faq.json` | 使用脚本校验指定知识库 |
| `python -m summer_camp_agent.cli ask "报名入口在哪里？"` | 输入学生问题并生成建议回复 |
| `python -m summer_camp_agent.cli ask "报名入口在哪里？" --today 2026-07-16` | 按指定日期测试过期停答规则 |
| `python -m summer_camp_agent.cli review "报名入口在哪里？"` | 生成运营半自动审核卡，展示建议动作、候选回复和资料来源 |
| `python -m summer_camp_agent.cli review "营服是什么颜色？" --pending-log data/pending_questions.jsonl` | 对未覆盖问题生成审核卡，并写入待补充 JSONL 清单 |
| `python -m summer_camp_agent.cli import-weflow --group "沐曦开源英才夏令营咨询群" --keywords "报名,报到,住宿,交通" --start 20260601 --end 20260630` | 从已启动的 WeFlow 本地 API 导入指定微信群聊天记录，输出脱敏 JSONL |
| 双击 `启动夏令营Agent.cmd` | 打开 PC 端群聊答疑运营工作台 |
| `python -B -m summer_camp_agent.workbench_gui` | 从命令行启动 PC 端群聊答疑运营工作台 |
| `python -B -m summer_camp_agent.gui` | 启动旧版单轮桌面问答窗口 |

## WeFlow 聊天记录导入

导入前需要用户手动启动 WeFlow，在设置中开启 API 服务，并将 API Token 放入环境变量：

```powershell
$env:WEFLOW_API_TOKEN="你的 WeFlow Token"
```

本项目不会读取或解密微信数据库，只消费 WeFlow 本地 API 返回的数据。导出的聊天记录默认写入 `imports/chat_logs/`，该目录已被 `.gitignore` 忽略。聊天记录只用于说话风格蒸馏和高频问题发现，不能直接作为官方事实答案。

## PC 端工作台 MVP 演示

当前 MVP 可以直接看到完整半自动答疑闭环：

1. 双击 `启动夏令营Agent.cmd`，默认进入 PC 端群聊答疑运营工作台。
2. 工作台启动后会自动载入演示消息，覆盖“可答复”“转人工”“待补充”和“未触发”四类状态。
3. 点击中间消息流中的任意消息，右侧会展示触发原因、建议动作、意图、来源、置信度和模式决策。
4. 底部回复框会自动填入草稿；可以直接点“发送”，也可以修改后再点“发送”。
5. 修改后发送会写入 `data/reply_candidates.jsonl` 和 `data/reply_logs.jsonl`；只点“保存候选”会写入候选库，但不会记录发送动作。
6. 点击“导入 JSONL”可以选择 `examples/workbench_demo_chat.jsonl` 验证导入流程，也可以选择后续 WeFlow 导出的脱敏聊天记录。

当前 MVP 不会真实向微信发送消息。“发送”只表示在本地工作台中记录运营动作，方便验证回复质量、候选库沉淀和日志链路。

## 桌面验证修正功能

桌面版支持临时教学模式。先问一个问题，如果回答不符合预期，可以继续输入：

```text
修正上个问题的回答结果：这里写正确答案
```

系统不会把这句话当成普通问题回答，而是把“上一个普通问题”和“修正答案”写入 `data/local_overrides.json`。下一次再问同一个问题时，会优先使用这条本地修正答案。

这个功能只用于资料不完整时快速验证问答效果。真实接入企业微信后应关闭本地修正覆盖，避免群内用户通过聊天修改知识库。

## 运营半自动流程

第一版不直接接入企业微信群自动读取消息。运营可以先把学生问题复制到 `review` 命令，检查建议动作后再决定如何处理：

- `send`：资料明确、可直接发送给学生。
- `edit`：可在发送前人工微调措辞。
- `escalate`：涉及个人状态、安全医疗、投诉争议、技术作业等，转人工负责人。
- `mark_pending`：当前资料未覆盖，写入待补充清单，等组委会确认后再更新知识库。

## 维护原则

- 只把官方明确或组委会确认的信息写进可自动回复内容。
- 时间、地点、报名入口、名单、作业规则等高风险信息必须保留资料来源和更新时间。
- 如果新资料与旧资料冲突，以发布渠道更正式、更新时间更新的资料为准，并保留冲突记录。
- 涉及个人状态、录取结果、医疗安全、投诉争议和技术作业答案的问题，默认不自动回复，必须转人工。
- 若系统还没有真实记录能力，回复中不要承诺“已记录”，只能说“建议标记为待补充”。
