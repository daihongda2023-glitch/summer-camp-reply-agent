---
source_type: gitlink_issue
trust_level: official
source_url: https://www.gitlink.org.cn/metax-maca/op_optimization/issues/4
source_updated_at: "2026-07-13 15:56"
repository: metax-maca/op_optimization
issue_index: "4"
answer_author: yyyymmm
---
# NSA 文档仅说明使用 “64K seqlen 测试”，但未明确性能榜评测时所采用的 batch、head 数、block_size、selected_blocks 等参数组合。`test_cases_nsa_fwd.json` 中包含 109 个 case，最终榜单是基于单一 case 还是整体加权计算？

最终榜单将基于 baseline 的 speedup 进行评估，整体性能结果由 OJ 提供的统一接口统计总运行时间后计算 speedup。
