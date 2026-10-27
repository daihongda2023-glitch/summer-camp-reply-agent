# 参与活动值守

活动值守欢迎活动组织者、值班志愿者和学生贡献者。第一项贡献通常是一场活动包，而不是修改问答内核。

## 适合提交什么

- 一场真实活动的 `activity.json` 和 `faq.json`：高校分享、社团招新、开源社区 Office Hour、线下签到或线上直播。
- 已有活动包的资料修正：时间、地点、入口和过期日期。
- 回复边界的测试：个人状态、作业代答、安全和投诉必须继续转人工。

提交前请确认这些内容没有写进自动回复：

- 个人录取、报名状态和名额。
- 作业答案、代写和未确认的评分结论。
- 未公开的联系方式、证件号和聊天记录。

## 添加一场活动

```powershell
python -m summer_camp_agent.cli init-activity city-reading --name "城市阅读会" --formats offline --serves "读书会组织者,现场志愿者"
```

`--formats` 可以是 `online`、`offline` 或 `online,offline`。`--serves` 写清这包资料给谁值班用。

接着修改 `faq.json` 中的模板答案，只保留已经确认的信息，然后运行：

```powershell
python -m summer_camp_agent.cli validate --activity city-reading
python -m summer_camp_agent.cli ask "这场活动是做什么的？" --activity city-reading
python -m summer_camp_agent.cli check
python -m unittest discover -s tests -p "test_*.py"
```

## 评审时怎么看社区潜力

组织者用它值守自己的活动。新贡献者用 `init-activity` 完成入门。值班志愿者用 `review` 决定发送、修改或转人工。项目因此不依赖某一个夏令营档期，后续活动可以继续往活动包里加。
