# 活动值守 Activity Desk

给活动值班的人用的咨询回复助手。线上分享、线下聚会、夏令营和同时有两种会场的活动，都用同一个问答内核。它只回答活动包里已经确认的内容；报名结果、作业代答、安全和投诉转给对应的人。

仓库目录和 Python 模块仍沿用 `summer_camp_agent`。对外名称是活动值守。

## 给谁用

| 谁 | 用来做什么 |
| --- | --- |
| 开源社区运营 | 把公告、日程和公开 Issue 收成可审核的回复，减少答疑群里的重复提问。夏令营包已经带有 MXMACA 算子社区的公开资料。 |
| 高校活动组委会 | 回答招新、工作坊、夏令营、入营和报到问题。线上课程和线下报到放在同一个活动包。 |
| 社团和 meetup 组织者 | 回答已经确认的时间、地点和直播入口。个人报名状态不自动判断。 |
| 值班志愿者 | 先看建议回复，再选择发送、修改或转给负责人。 |
| 新贡献者 | 不改内核，用 `init-activity` 交一场自己学校或社区的活动。这是进入项目的第一项任务。 |

## 活动包

| 活动包 | 形式 | 适用对象 |
| --- | --- | --- |
| `summer-camp` | 线上、线下 | 夏令营组委会、课程助教、咨询群值班同学 |
| `online-workshop` | 线上 | 线上分享主讲人、活动群值班志愿者 |
| `offline-meetup` | 线下 | 线下活动组织者、现场签到志愿者 |
| `hybrid-summit` | 线上、线下 | 开放日主办方、线上会务、现场会务 |

生成一场新活动：

```powershell
python -m summer_camp_agent.cli init-activity city-reading --name "城市阅读会" --formats offline --serves "读书会组织者,现场志愿者"
```

然后改 `activities/city-reading/faq.json` 里的模板答案，再运行 `validate` 和 `ask`。

## 本地运行

需要 Python 3.10 或更高版本，不需要安装第三方包。

```powershell
python -m summer_camp_agent.cli activities
python -m summer_camp_agent.cli check
python -m summer_camp_agent.cli demo
python -m summer_camp_agent.cli ask "直播链接在哪里？" --activity online-workshop
python -m summer_camp_agent.cli ask "活动地点在哪里？" --activity offline-meetup
python -m unittest discover -s tests -p "test_*.py"
```

`demo` 不访问网络，也不调用大模型。夏令营样例固定在 2026-07-10 回放。真实消息按消息日期判断资料是否仍有效。

## 用什么模型

日常回复不调用大模型。`ask`、`demo`、`check` 命中活动包时，输出里的 `model` 是 `未调用`。匹配依据是问题原文、别名和关键词。

只有设置了 `OPENAI_API_KEY`，工作台里的语义判断和资料生成才会请求模型。

| 用途 | 默认模型 | 接口 | 什么时候用 |
| --- | --- | --- | --- |
| 语义判断、按资料生成回复 | `deepseek-v4-pro` | `https://api.deepseek.com` | 已设置密钥，且 FAQ 没有直接命中 |
| 向量检索 | `text-embedding-3-small` | `https://api.openai.com/v1/embeddings` | 显式建立或查询 RAG 索引时 |

查看当前配置：

```powershell
python -m summer_camp_agent.cli models
```

更换聊天模型：

```powershell
$env:OPENAI_API_KEY="你的密钥"
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:OPENAI_CHAT_MODEL="deepseek-v4-pro"
```

`OPENAI_BASE_URL` 可以改成其他 OpenAI 兼容接口。密钥不会写入仓库。没有密钥时，FAQ、活动包检查和演示仍然可以运行。

## 回复边界

- 只回复活动包里写明、且未过期的内容。
- 录取、报名状态、名额查询转给活动里的主办方或组委会。
- 作业答案、代写和调试请求转给活动配置的对接人。
- 医疗、安全、突发和投诉立即转人工。
- 示例活动包中的 `example.com` 和 `init-activity` 生成的模板答案要换成真实信息后才能对外发送。

## 许可证

Apache License 2.0。详见 `LICENSE`。参与方式见 `CONTRIBUTING.md`。
