---
source_type: gitlink_issue
trust_level: official
source_url: https://www.gitlink.org.cn/metax-maca/op_optimization/issues/4
source_updated_at: "2026-07-13 15:56"
repository: metax-maca/op_optimization
issue_index: "4"
answer_author: yyyymmm
---
# MLA 文档中提到 “QK dim = 576 + VO dim = 512（DeepSeek V3 配置）”，但 `race_tests` 中使用的是 `dim=512, pe_dim=64`。比赛方案未明确选手应以哪种参数配置实现。

`race_tests` 中的 `dim=512, pe_dim=64` 对应的即是 `QK dim = 576, V dim = 512` 的实现配置，两者本质一致。
