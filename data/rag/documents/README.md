# RAG 正式资料目录

本目录用于存放可以进入事实 RAG 的夏令营正式资料。

## 可以放入的资料

- 公开招募文章、报名说明、活动通知。
- 经组委会确认后的 FAQ、课程安排、报到须知。
- 已确认可用于学生回复的住宿、交通、作业规则、线下手册。
- 用户或运营明确确认“可以作为正式回复依据”的 Markdown 或纯文本资料。

## 不应放入的资料

- 学生名单、身份证号、手机号、邮箱、住址等个人信息。
- 未公开或未确认的录取、面试、成绩、报名状态资料。
- 微信群聊天记录原文或 WeFlow 导出的聊天记录。
- API Key、Token、账号密码、内部系统地址等敏感配置。
- 尚未确认真实性、时效性或发布权限的临时讨论内容。

## 聊天记录边界

`imports/chat_logs/` 中的聊天记录只用于风格蒸馏和高频问题发现，不作为事实 RAG 来源。聊天记录中的高频问题需要人工确认后，才能整理进 FAQ 或本目录的正式资料。

## 建索引命令

默认使用 OpenAI Embedding：

```text
python -m summer_camp_agent.cli rag-index --documents data/rag/documents --index data/rag/index
```

运行前需要在环境变量中设置：

```text
OPENAI_API_KEY
```

本地测试或演示可以使用固定向量 provider：

```text
python -m summer_camp_agent.cli rag-index --documents data/rag/documents --index data/rag/index --provider static
```

`data/rag/index/` 是派生索引目录，默认不会提交到 Git。
