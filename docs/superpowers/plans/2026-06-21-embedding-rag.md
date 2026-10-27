# Embedding 向量 RAG 实施计划

> **面向 agentic workers：** 必须使用 `executing-plans` 或 `subagent-driven-development` 按任务逐项执行。步骤使用复选框（`- [ ]`）跟踪。

**目标：** 为夏令营自动回复 agent 增加基于正式资料的 Embedding 向量 RAG 兜底能力。

**架构：** 保持现有 FAQ 优先的问答路径，新增本地文档切分、Embedding provider、本地 JSONL 索引、余弦相似度检索和确定性回复模板。聊天记录目录不参与事实索引；索引不存在时不影响现有桌面应用和 CLI。

**技术栈：** Python 标准库、`unittest`、OpenAI Embeddings HTTP API、JSONL 本地索引。

---

## 文件结构

- 新建 `summer_camp_agent/rag_documents.py`：读取 `.md` / `.txt` 正式资料，按标题和段落切分 chunk。
- 新建 `summer_camp_agent/rag_embeddings.py`：定义 `EmbeddingProvider`，实现 fake provider 和 OpenAI provider。
- 新建 `summer_camp_agent/rag_index.py`：构建、读取、校验本地索引，提供余弦相似度函数。
- 新建 `summer_camp_agent/rag_retriever.py`：查询向量、top-k 检索、阈值判断和保守回复生成。
- 修改 `summer_camp_agent/engine.py`：FAQ 低置信后调用可选 RAG retriever。
- 修改 `summer_camp_agent/cli.py`：新增 `rag-index`、`rag-search`，`ask/review` 支持默认索引。
- 修改 `summer_camp_agent/desktop_chat.py`：桌面启动时尝试加载默认索引，索引不存在时保持现有行为。
- 新建 `tests/test_rag_documents.py`、`tests/test_rag_embeddings.py`、`tests/test_rag_index.py`、`tests/test_rag_retriever.py`：覆盖 RAG 基础能力。
- 修改 `tests/test_engine.py`、`tests/test_cli.py`、`tests/test_desktop_chat.py`：覆盖 RAG 接入。
- 新建 `data/rag/documents/README.md`：中文说明哪些资料可以进入索引。

## 安全约束

- `OPENAI_API_KEY` 只从环境变量读取。
- 单元测试不得调用真实 OpenAI API。
- `imports/chat_logs/` 不允许作为默认索引输入。
- `data/rag/index/` 继续不提交 Git。
- 错误提示中文化，且不打印 Key、完整 API 响应或完整敏感资料。

## 任务 1：文档读取与 chunk 切分

**文件：**
- 新建：`summer_camp_agent/rag_documents.py`
- 新建：`tests/test_rag_documents.py`

- [ ] **步骤 1：写失败测试**

测试内容：

```python
def test_loads_markdown_and_splits_by_heading(tmp_path):
    source = tmp_path / "handbook.md"
    source.write_text("# 线下手册\n\n## 住宿安排\n\n活动期间住宿由主办方统一安排。\n\n## 交通安排\n\n往返交通费用由营员自理。", encoding="utf-8")

    chunks = load_document_chunks(tmp_path, target_chars=30, overlap_chars=5)

    assert len(chunks) >= 2
    assert chunks[0].source_title == "线下手册"
    assert any("住宿安排" in chunk.heading for chunk in chunks)
    assert any("往返交通费用" in chunk.text for chunk in chunks)
```

- [ ] **步骤 2：运行失败测试**

运行：

```text
python -B -m unittest tests.test_rag_documents
```

预期：失败，提示 `rag_documents` 或 `load_document_chunks` 不存在。

- [ ] **步骤 3：实现最小代码**

实现 `DocumentChunk`、`SourceFile`、`load_document_chunks`、`split_text_into_chunks`。只支持 `.md` 和 `.txt`，跳过隐藏目录、`imports/chat_logs` 和 `data/rag/index`。

- [ ] **步骤 4：验证通过**

运行：

```text
python -B -m unittest tests.test_rag_documents
```

预期：通过。

## 任务 2：Embedding provider 与 OpenAI API 封装

**文件：**
- 新建：`summer_camp_agent/rag_embeddings.py`
- 新建：`tests/test_rag_embeddings.py`

- [ ] **步骤 1：写失败测试**

测试内容：

```python
def test_openai_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest_raises_message(RagEmbeddingError, "缺少 OPENAI_API_KEY"):
        OpenAIEmbeddingProvider.from_env()
```

`unittest` 中使用 `with self.assertRaisesRegex(...)`。

- [ ] **步骤 2：运行失败测试**

运行：

```text
python -B -m unittest tests.test_rag_embeddings
```

预期：失败，提示模块或类型不存在。

- [ ] **步骤 3：实现最小代码**

实现：

- `RagEmbeddingError`
- `EmbeddingProvider`
- `StaticEmbeddingProvider`
- `OpenAIEmbeddingProvider.from_env()`
- `OpenAIEmbeddingProvider.embed_texts(texts)`

OpenAI provider 使用 `urllib.request` 调用：

```text
POST https://api.openai.com/v1/embeddings
```

请求体包含 `model` 和 `input`。响应必须校验 `data[].embedding` 为数字数组。

- [ ] **步骤 4：验证通过**

运行：

```text
python -B -m unittest tests.test_rag_embeddings
```

预期：通过，且不访问真实网络。

## 任务 3：本地索引构建、读取和相似度计算

**文件：**
- 新建：`summer_camp_agent/rag_index.py`
- 新建：`tests/test_rag_index.py`

- [ ] **步骤 1：写失败测试**

测试内容：

```python
def test_build_index_writes_manifest_and_chunks(tmp_path):
    documents = tmp_path / "documents"
    index = tmp_path / "index"
    documents.mkdir()
    (documents / "notice.md").write_text("# 通知\n\n报名截止到 2026 年 7 月 15 日。", encoding="utf-8")
    provider = StaticEmbeddingProvider({"通知\n报名截止到 2026 年 7 月 15 日。": [1.0, 0.0]})

    summary = build_rag_index(documents, index, provider)

    assert summary.chunk_count == 1
    assert (index / "manifest.json").exists()
    assert (index / "chunks.jsonl").exists()
```

- [ ] **步骤 2：运行失败测试**

运行：

```text
python -B -m unittest tests.test_rag_index
```

预期：失败，提示 `rag_index` 不存在。

- [ ] **步骤 3：实现最小代码**

实现：

- `RagIndexError`
- `RagIndexSummary`
- `IndexedChunk`
- `build_rag_index`
- `load_rag_index`
- `cosine_similarity`

- [ ] **步骤 4：验证通过**

运行：

```text
python -B -m unittest tests.test_rag_index
```

预期：通过。

## 任务 4：RAG 检索与确定性回复

**文件：**
- 新建：`summer_camp_agent/rag_retriever.py`
- 新建：`tests/test_rag_retriever.py`

- [ ] **步骤 1：写失败测试**

测试内容：

```python
def test_retriever_returns_answer_when_similarity_is_high(tmp_path):
    # 使用 StaticEmbeddingProvider 构造查询和资料 chunk 向量，使相似度高于阈值。
    result = retriever.retrieve("住宿怎么安排？")

    assert result is not None
    assert result.confidence >= 0.72
    assert "同学你好" in result.reply
    assert "以上信息来自" in result.reply
```

- [ ] **步骤 2：运行失败测试**

运行：

```text
python -B -m unittest tests.test_rag_retriever
```

预期：失败，提示 `rag_retriever` 不存在。

- [ ] **步骤 3：实现最小代码**

实现：

- `RagSearchResult`
- `RagRetriever`
- `format_rag_reply`

默认 `top_k=4`，`min_similarity=0.72`，`strong_similarity=0.82`。

- [ ] **步骤 4：验证通过**

运行：

```text
python -B -m unittest tests.test_rag_retriever
```

预期：通过。

## 任务 5：CLI 接入

**文件：**
- 修改：`summer_camp_agent/cli.py`
- 修改：`tests/test_cli.py`

- [ ] **步骤 1：写失败测试**

新增测试：

- `rag-index` 缺少 `OPENAI_API_KEY` 时返回中文错误。
- `rag-search` 可以使用测试索引输出相似度和来源。
- `ask` 在默认索引不存在时仍保持现有 FAQ 行为。

- [ ] **步骤 2：运行失败测试**

运行：

```text
python -B -m unittest tests.test_cli
```

预期：新测试失败。

- [ ] **步骤 3：实现最小代码**

新增子命令：

```text
rag-index --documents data/rag/documents --index data/rag/index
rag-search "问题" --index data/rag/index
```

`ask/review` 构建 `AnswerEngine` 时尝试加载默认索引，失败则退回 FAQ。

- [ ] **步骤 4：验证通过**

运行：

```text
python -B -m unittest tests.test_cli
```

预期：通过。

## 任务 6：问答内核和桌面接入

**文件：**
- 修改：`summer_camp_agent/engine.py`
- 修改：`summer_camp_agent/desktop_chat.py`
- 修改：`tests/test_engine.py`
- 修改：`tests/test_desktop_chat.py`

- [ ] **步骤 1：写失败测试**

新增测试：

- FAQ 未命中且 RAG 高置信时返回 `auto_reply`。
- RAG 低置信时返回 `needs_info`。
- 桌面会话默认索引不存在时仍可启动和回答 FAQ。

- [ ] **步骤 2：运行失败测试**

运行：

```text
python -B -m unittest tests.test_engine tests.test_desktop_chat
```

预期：新测试失败。

- [ ] **步骤 3：实现最小代码**

`AnswerEngine` 新增可选参数 `rag_retriever`。FAQ 不可信时调用 `rag_retriever.retrieve(text)`。RAG 命中时返回 `AnswerResult(action="auto_reply", intent="rag.document", source=...)`。

- [ ] **步骤 4：验证通过**

运行：

```text
python -B -m unittest tests.test_engine tests.test_desktop_chat
```

预期：通过。

## 任务 7：资料目录说明和全量验证

**文件：**
- 新建：`data/rag/documents/README.md`

- [ ] **步骤 1：写中文说明**

说明：

- 哪些资料可以放入该目录。
- 哪些资料不应放入该目录。
- `imports/chat_logs/` 不作为事实资料来源。
- 建索引命令示例。

- [ ] **步骤 2：全量测试**

运行：

```text
python -B -m unittest discover -s tests
```

预期：所有测试通过。

- [ ] **步骤 3：提交代码**

运行：

```text
git status --short
git diff --check
git add ...
git commit -m "feat: add embedding rag pipeline"
```

预期：提交成功，工作区干净。
