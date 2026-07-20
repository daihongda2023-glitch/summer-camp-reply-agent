# GitLink Issue RAG 与夏令营回复逻辑实施计划

> **面向智能体执行者：** REQUIRED SUB-SKILL：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项实施本计划。所有步骤均使用复选框跟踪。

**目标：** 更新官方海报知识，增加可重复运行的 GitLink Issue 同步器，并让 RAG 根据官方或社区来源决定自动回复还是建议回复。

**架构：** 结构化 FAQ 继续承担报名、课程和时间节点等确定性回答；GitLink 同步器通过公开 API 抓取两个仓库，经过任务过滤、内容清理和可信度分层后生成独立 Markdown。RAG 文档加载器把可信等级与来源 URL 写入 chunk 元数据，检索器和回复引擎据此限制社区内容只能进入人工确认流程。

**技术栈：** Python 3 标准库、`unittest`、现有 JSON FAQ、Markdown/YAML front matter、GitLink JSON API、现有 Embedding RAG。

---

## 文件结构

### 新建文件

- `data/gitlink_rag_sources.json`：两个 GitLink 仓库的同步、过滤和可信账号配置。
- `summer_camp_agent/gitlink_issue_transform.py`：纯函数形式的 Issue 过滤、FAQ 表格拆分、评论清理、可信等级判定和 Markdown 渲染。
- `summer_camp_agent/gitlink_issue_sync.py`：GitLink API 客户端、分页、同步编排、快照替换和报告生成。
- `scripts/sync_gitlink_issues.py`：面向运营的同步命令入口。
- `tests/test_gitlink_issue_transform.py`：内容过滤与问答转换单元测试。
- `tests/test_gitlink_issue_sync.py`：分页、失败保护、快照替换和报告单元测试。
- `data/rag/documents/gitlink-issues/`：同步器生成并提交的问答快照。
- `data/rag/gitlink-sync-report.json`：最近一次成功同步的无敏感信息统计报告。

### 修改文件

- `data/faq.json`：替换旧报名链接，更新学习时间并补充课程、作业、直播、提交账号和群提醒。
- `docs/knowledge-base/seed-faq.md`：保持人工维护文档与运行时 FAQ 一致。
- `data/rag/documents/README.md`：记录 GitLink 同步、可信等级和建索引流程。
- `summer_camp_agent/rag_documents.py`：解析 YAML front matter 并校验 GitLink 文档可信等级。
- `summer_camp_agent/rag_retriever.py`：把可信等级和来源 URL 带入检索结果及回复文本。
- `summer_camp_agent/engine.py`：沿用 `is_strong` 决定自动回复，并对来源元数据异常保持不回答。
- `summer_camp_agent/cli.py`：增加 `sync-gitlink` 子命令及同步异常处理。
- `tests/test_engine.py`：更新海报知识断言并覆盖社区建议回复。
- `tests/test_cli.py`：更新报名入口断言并覆盖同步命令入口。
- `tests/test_rag_documents.py`：覆盖 front matter 解析与非法可信等级。
- `tests/test_rag_retriever.py`：覆盖官方和社区来源的动作边界及来源 URL。

## 实施顺序

### 任务 1：更新官方海报结构化 FAQ

**文件：**

- 修改：`tests/test_engine.py`
- 修改：`tests/test_cli.py`
- 修改：`data/faq.json`
- 修改：`docs/knowledge-base/seed-faq.md`

- [ ] **步骤 1：先写海报知识失败测试**

在 `tests/test_engine.py` 中替换旧报名链接测试，并增加完整海报信息的表驱动测试：

```python
def test_answers_registration_link_from_latest_official_poster(self):
    result = make_engine(today=date(2026, 7, 15)).answer("报名入口在哪里？")

    self.assertEqual(result.action, "auto_reply")
    self.assertEqual(result.intent, "registration.link")
    self.assertIn("https://developer.metax-tech.com/activities/18", result.reply)
    self.assertNotIn("v.wjx.cn", result.reply)
    self.assertIn("官方咨询群海报", result.source)

def test_answers_latest_course_and_camp_schedule(self):
    cases = [
        ("线上学习和作业什么时候截止？", "2026 年 7 月 20 日"),
        ("课程1在哪里学习？", "https://www.gitlink.org.cn/ccf-ai-infra/Intro-ops"),
        ("作业1在哪里提交？", "https://www.gitlink.org.cn/ccf-ai-infra/Intro-ops/issues/16"),
        ("课程2的作业入口是什么？", "https://www.gitlink.org.cn/metax-maca/op_optimization/issues/12"),
        ("课程直播是什么时间？", "7 月 13 日至 7 月 15 日，每晚 19:00—21:00"),
        ("作业提交账号怎么获得？", "报名时使用的邮箱"),
        ("线下夏令营什么时候在哪里？", "2026 年 8 月 3 日至 8 月 7 日"),
        ("群昵称建议改成什么？", "姓名-学校-年级"),
    ]
    for question, expected in cases:
        with self.subTest(question=question):
            result = make_engine(today=date(2026, 7, 15)).answer(question)
            self.assertEqual(result.action, "auto_reply")
            self.assertIn(expected, result.reply)
```

在 `tests/test_cli.py` 中给依赖报名有效期的命令明确传入日期，并更新链接：

```python
def test_ask_command_returns_answer_payload(self):
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "summer_camp_agent.cli",
            "ask",
            "报名入口在哪里？",
            "--today",
            "2026-07-15",
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )

    self.assertIn("action: auto_reply", completed.stdout)
    self.assertIn("intent: registration.link", completed.stdout)
    self.assertIn("https://developer.metax-tech.com/activities/18", completed.stdout)
    self.assertNotIn("v.wjx.cn", completed.stdout)
    self.assertIn("source: 官方咨询群海报", completed.stdout)
```

- [ ] **步骤 2：运行测试并确认因旧知识失败**

运行：

```powershell
python -m unittest tests.test_engine.AnswerEngineTest.test_answers_registration_link_from_latest_official_poster tests.test_engine.AnswerEngineTest.test_answers_latest_course_and_camp_schedule tests.test_cli.CLITest.test_ask_command_returns_answer_payload -v
```

预期：报名入口仍返回 `v.wjx.cn`，新增课程、直播和群昵称问题未全部命中，测试失败。

- [ ] **步骤 3：最小更新运行时 FAQ**

在 `data/faq.json` 中更新 `faq.registration.link` 与 `faq.learning.schedule`，并加入以下条目。所有条目的 `source` 使用“官方咨询群海报”，`source_date` 和 `last_updated` 使用 `2026-07-20`：

```json
{
  "id": "faq.registration.link",
  "stage": "报名申请期",
  "intent": "registration.link",
  "question": "报名入口在哪里？",
  "question_aliases": ["报名链接", "怎么报名", "报名通道"],
  "keywords": ["报名", "入口"],
  "answer": "报名通道为：https://developer.metax-tech.com/activities/18。为方便接收报名通知，请填写真实姓名。报名截止时间为 2026 年 7 月 15 日。",
  "source": "官方咨询群海报",
  "source_date": "2026-07-20",
  "last_updated": "2026-07-20",
  "valid_until": "2026-07-15",
  "auto_reply": true,
  "needs_human_fallback": false,
  "human_fallback_reason": "",
  "owner": "运营"
},
{
  "id": "faq.learning.schedule",
  "stage": "线上学习期",
  "intent": "learning.schedule",
  "question": "线上学习和作业什么时候进行？",
  "question_aliases": ["线上学习和作业什么时候截止？", "课程作业截止时间", "学习阶段到什么时候"],
  "keywords": ["学习", "作业", "截止"],
  "answer": "线上学习与作业时间为即日起至 2026 年 7 月 20 日，请自行安排学习时间并特别注意作业提交截止时间。",
  "source": "官方咨询群海报",
  "source_date": "2026-07-20",
  "last_updated": "2026-07-20",
  "valid_until": "2026-07-20",
  "auto_reply": true,
  "needs_human_fallback": false,
  "human_fallback_reason": "",
  "owner": "运营"
},
{
  "id": "faq.learning.course1",
  "stage": "线上学习期",
  "intent": "learning.course1",
  "question": "课程1在哪里学习？",
  "question_aliases": ["TileLang 入门课程入口", "课程1链接", "作业1在哪里提交？"],
  "keywords": ["课程1", "TileLang"],
  "answer": "课程 1 为 TileLang 入门学习，课程仓库：https://www.gitlink.org.cn/ccf-ai-infra/Intro-ops；作业 1 提交入口：https://www.gitlink.org.cn/ccf-ai-infra/Intro-ops/issues/16。",
  "source": "官方咨询群海报",
  "source_date": "2026-07-20",
  "last_updated": "2026-07-20",
  "valid_until": "2026-07-20",
  "auto_reply": true,
  "needs_human_fallback": false,
  "human_fallback_reason": "",
  "owner": "课程助教"
},
{
  "id": "faq.learning.course2",
  "stage": "实践作业期",
  "intent": "learning.course2",
  "question": "课程2的作业入口是什么？",
  "question_aliases": ["真实算子优化课程入口", "课程2链接", "作业2在哪里提交？"],
  "keywords": ["课程2", "算子优化"],
  "answer": "课程 2 为真实算子优化实战，课程仓库：https://www.gitlink.org.cn/metax-maca/op_optimization；作业 2 提交入口：https://www.gitlink.org.cn/metax-maca/op_optimization/issues/12。",
  "source": "官方咨询群海报",
  "source_date": "2026-07-20",
  "last_updated": "2026-07-20",
  "valid_until": "2026-07-20",
  "auto_reply": true,
  "needs_human_fallback": false,
  "human_fallback_reason": "",
  "owner": "课程助教"
},
{
  "id": "faq.learning.account",
  "stage": "实践作业期",
  "intent": "learning.account",
  "question": "作业提交账号怎么获得？",
  "question_aliases": ["提交账号在哪里", "作业账号没收到", "课程账号怎么发"],
  "keywords": ["提交", "账号", "邮箱"],
  "answer": "作业提交账号会以邮件形式发送到报名时使用的邮箱，请留意收件箱和垃圾邮件。若仍未收到，请在群内联系工作人员核对。",
  "source": "官方咨询群海报",
  "source_date": "2026-07-20",
  "last_updated": "2026-07-20",
  "valid_until": "2026-07-20",
  "auto_reply": true,
  "needs_human_fallback": false,
  "human_fallback_reason": "",
  "owner": "课程助教"
},
{
  "id": "faq.learning.live",
  "stage": "线上学习期",
  "intent": "learning.live",
  "question": "课程直播是什么时间？",
  "question_aliases": ["直播时间", "线上课几点开始", "7月课程安排"],
  "keywords": ["直播", "课程", "时间"],
  "answer": "线上课程直播安排在 2026 年 7 月 13 日至 7 月 15 日，每晚 19:00—21:00。建议完整参与，并抓紧完成课程作业。",
  "source": "官方咨询群海报",
  "source_date": "2026-07-20",
  "last_updated": "2026-07-20",
  "valid_until": "2026-07-15",
  "auto_reply": true,
  "needs_human_fallback": false,
  "human_fallback_reason": "",
  "owner": "课程助教"
},
{
  "id": "faq.notice.nickname",
  "stage": "线上学习期",
  "intent": "notice.nickname",
  "question": "群昵称建议改成什么？",
  "question_aliases": ["群昵称格式", "怎么改群名", "群里备注写什么"],
  "keywords": ["群昵称", "姓名", "学校", "年级"],
  "answer": "建议将群昵称修改为“姓名-学校-年级”，方便后续通知和沟通。请同时及时关注群公告和群内通知。",
  "source": "官方咨询群海报",
  "source_date": "2026-07-20",
  "last_updated": "2026-07-20",
  "valid_until": "2026-08-07",
  "auto_reply": true,
  "needs_human_fallback": false,
  "human_fallback_reason": "",
  "owner": "运营"
}
```

更新现有 `faq.interview.schedule`、`faq.offline.time` 和 `faq.offline.location` 的来源及回答，使其与海报一致。`faq.offline.location` 的回答必须同时包含“上海交通大学、沐曦股份”。

- [ ] **步骤 4：同步更新中文知识库文档**

在 `docs/knowledge-base/seed-faq.md` 中替换旧报名入口和学习时间，并增加“课程与作业”“线上直播”“群内提醒”三节。内容逐字采用 `data/faq.json` 的最新事实，不保留旧链接或“7 月中旬”旧口径。

- [ ] **步骤 5：运行知识测试和校验并确认通过**

运行：

```powershell
python -m unittest tests.test_engine tests.test_cli -v
python scripts/validate_knowledge.py data/faq.json
rg -n "v\.wjx\.cn|7 月中旬" data/faq.json docs/knowledge-base/seed-faq.md
```

预期：单元测试通过；知识库校验退出码为 0；最后一条搜索无输出且退出码为 1。

- [ ] **步骤 6：提交海报知识更新**

```powershell
git add data/faq.json docs/knowledge-base/seed-faq.md tests/test_engine.py tests/test_cli.py
git commit -m "feat: 更新夏令营官方海报知识"
```

### 任务 2：让 RAG 文档读取可信等级与来源 URL

**文件：**

- 修改：`tests/test_rag_documents.py`
- 修改：`summer_camp_agent/rag_documents.py`

- [ ] **步骤 1：先写 front matter 失败测试**

在 `tests/test_rag_documents.py` 中加入：

```python
from summer_camp_agent.rag_documents import RagDocumentError, load_document_chunks, split_text_into_chunks

def test_loads_front_matter_as_metadata_without_embedding_it(self):
    with self._temp_documents() as root:
        source = root / "issue-5.md"
        source.write_text(
            "---\n"
            "source_type: gitlink_issue\n"
            "trust_level: community\n"
            "source_url: https://www.gitlink.org.cn/example/repo/issues/5\n"
            "issue_index: \"5\"\n"
            "---\n"
            "# 构建问题\n\n"
            "重新安装 cmake 后构建通过。\n",
            encoding="utf-8",
        )

        chunks = load_document_chunks(root)

    self.assertEqual(len(chunks), 1)
    self.assertEqual(chunks[0].metadata["trust_level"], "community")
    self.assertEqual(chunks[0].metadata["issue_index"], "5")
    self.assertNotIn("trust_level", chunks[0].text)
    self.assertNotIn("source_url", chunks[0].text)
    self.assertIn("重新安装 cmake", chunks[0].text)

def test_rejects_unknown_gitlink_trust_level(self):
    with self._temp_documents() as root:
        (root / "invalid.md").write_text(
            "---\n"
            "source_type: gitlink_issue\n"
            "trust_level: guessed\n"
            "source_url: https://www.gitlink.org.cn/example/repo/issues/1\n"
            "---\n"
            "# 问题\n\n答复。\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RagDocumentError, "trust_level"):
            load_document_chunks(root)
```

- [ ] **步骤 2：运行测试并确认解析能力缺失**

运行：

```powershell
python -m unittest tests.test_rag_documents.RagDocumentsTest.test_loads_front_matter_as_metadata_without_embedding_it tests.test_rag_documents.RagDocumentsTest.test_rejects_unknown_gitlink_trust_level -v
```

预期：因 `RagDocumentError` 不存在或 metadata 为空而失败。

- [ ] **步骤 3：实现最小 front matter 解析与校验**

在 `summer_camp_agent/rag_documents.py` 中加入以下类型和函数，并在 `load_document_chunks` 读取每个 Markdown 后调用 `_extract_front_matter`：

```python
ALLOWED_GITLINK_TRUST_LEVELS = {"official", "community"}


class RagDocumentError(ValueError):
    """RAG 正式资料的元数据不满足安全约束。"""


def _extract_front_matter(raw_text: str) -> tuple[dict[str, str], str]:
    normalized = raw_text.lstrip("\ufeff")
    if not normalized.startswith("---\n"):
        return {}, normalized

    closing = normalized.find("\n---\n", 4)
    if closing < 0:
        raise RagDocumentError("Markdown front matter 缺少结束分隔符。")

    header = normalized[4:closing]
    body = normalized[closing + 5 :].strip()
    metadata: dict[str, str] = {}
    for line in header.splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator or not key.strip():
            raise RagDocumentError(f"front matter 行格式异常：{line}")
        metadata[key.strip()] = value.strip().strip('"').strip("'")

    if metadata.get("source_type") == "gitlink_issue":
        trust_level = metadata.get("trust_level", "")
        if trust_level not in ALLOWED_GITLINK_TRUST_LEVELS:
            raise RagDocumentError("GitLink 文档 trust_level 必须是 official 或 community。")
        source_url = metadata.get("source_url", "")
        if not source_url.startswith("https://www.gitlink.org.cn/"):
            raise RagDocumentError("GitLink 文档 source_url 必须使用 gitlink.org.cn HTTPS 地址。")
    return metadata, body
```

把 `load_document_chunks` 中的正文处理改为：

```python
raw_text = path.read_text(encoding="utf-8").strip()
if not raw_text:
    continue
metadata, document_text = _extract_front_matter(raw_text) if path.suffix.lower() == ".md" else ({}, raw_text)
if not document_text:
    continue
source_sha256 = _sha256_text(raw_text)
source_title = _source_title(path, document_text)
relative_path = path.relative_to(root).as_posix()
sections = (
    _markdown_sections(document_text, source_title)
    if path.suffix.lower() == ".md"
    else [(source_title, document_text)]
)
```

构造 `DocumentChunk` 时使用：

```python
metadata=dict(metadata),
```

- [ ] **步骤 4：运行文档测试并确认通过**

运行：

```powershell
python -m unittest tests.test_rag_documents -v
```

预期：全部通过，旧 Markdown 和纯文本行为保持不变。

- [ ] **步骤 5：提交文档元数据支持**

```powershell
git add summer_camp_agent/rag_documents.py tests/test_rag_documents.py
git commit -m "feat: 读取 RAG 来源可信元数据"
```

### 任务 3：按可信等级限制 RAG 自动回复

**文件：**

- 修改：`tests/test_rag_retriever.py`
- 修改：`tests/test_engine.py`
- 修改：`summer_camp_agent/rag_retriever.py`
- 修改：`summer_camp_agent/engine.py`

- [ ] **步骤 1：先写官方与社区动作边界失败测试**

在 `tests/test_rag_retriever.py` 中增加一个构造带元数据索引的辅助方法，并增加两项测试：

```python
def _build_retriever_for_document(self, root: Path, trust_level: str) -> RagRetriever:
    documents = root / "documents"
    index = root / "index"
    documents.mkdir()
    (documents / "answer.md").write_text(
        "---\n"
        "source_type: gitlink_issue\n"
        f"trust_level: {trust_level}\n"
        "source_url: https://www.gitlink.org.cn/example/repo/issues/5\n"
        "---\n"
        "# 构建问题\n\n重新安装 cmake 后构建通过。\n",
        encoding="utf-8",
    )
    provider = StaticEmbeddingProvider(default_embedding=[1.0, 0.0], model="static-model")
    build_rag_index(documents, index, provider)
    return RagRetriever(load_rag_index(index, expected_model="static-model"), provider)

def test_official_high_similarity_is_strong_and_includes_url(self):
    with tempfile.TemporaryDirectory() as directory:
        result = self._build_retriever_for_document(Path(directory), "official").retrieve("怎么解决构建问题？")

    assert result is not None
    self.assertTrue(result.is_strong)
    self.assertEqual(result.trust_level, "official")
    self.assertIn("https://www.gitlink.org.cn/example/repo/issues/5", result.source)

def test_community_high_similarity_is_never_strong(self):
    with tempfile.TemporaryDirectory() as directory:
        result = self._build_retriever_for_document(Path(directory), "community").retrieve("怎么解决构建问题？")

    assert result is not None
    self.assertFalse(result.is_strong)
    self.assertEqual(result.trust_level, "community")
    self.assertIn("社区经验", result.reply)
    self.assertIn("以后续官方答复为准", result.reply)
```

在 `tests/test_engine.py` 中增加：

```python
def test_community_rag_result_only_creates_suggested_reply(self):
    rag_result = RagSearchResult(
        reply="同学你好，以下是社区经验：重新安装 cmake 后构建通过。",
        source="Intro-ops Issue #15（https://www.gitlink.org.cn/ccf-ai-infra/Intro-ops/issues/15）",
        confidence=0.99,
        chunks=[],
        is_strong=False,
        trust_level="community",
        source_url="https://www.gitlink.org.cn/ccf-ai-infra/Intro-ops/issues/15",
    )

    result = make_engine(rag_retriever=FakeRagRetriever(rag_result)).answer("cmake 构建失败怎么办？")

    self.assertEqual(result.action, "suggested_reply")
    self.assertEqual(result.intent, "rag.document")
    self.assertEqual(result.source, rag_result.source)
```

- [ ] **步骤 2：运行测试并确认社区内容仍被视为强命中**

运行：

```powershell
python -m unittest tests.test_rag_retriever.RagRetrieverTest.test_official_high_similarity_is_strong_and_includes_url tests.test_rag_retriever.RagRetrieverTest.test_community_high_similarity_is_never_strong tests.test_engine.AnswerEngineTest.test_community_rag_result_only_creates_suggested_reply -v
```

预期：`RagSearchResult` 缺少可信字段，或社区结果的 `is_strong` 仍为真，测试失败。

- [ ] **步骤 3：实现可信感知的检索结果**

将 `summer_camp_agent/rag_retriever.py` 中的结果类型扩展为：

```python
@dataclass(frozen=True)
class RagSearchResult:
    reply: str
    source: str
    confidence: float
    chunks: list[ScoredChunk]
    is_strong: bool
    trust_level: str = "official"
    source_url: str = ""
```

在 `retrieve` 中使用最佳 chunk 的元数据：

```python
best = top_chunks[0]
trust_level = best.chunk.metadata.get("trust_level", "official")
source_url = best.chunk.metadata.get("source_url", "")
return RagSearchResult(
    reply=format_rag_reply(best.chunk, trust_level=trust_level),
    source=format_rag_source(best.chunk),
    confidence=best.score,
    chunks=top_chunks,
    is_strong=trust_level == "official" and best.score >= self.strong_similarity,
    trust_level=trust_level,
    source_url=source_url,
)
```

把回复和来源格式函数改为：

```python
def format_rag_reply(chunk: IndexedChunk, trust_level: str = "official") -> str:
    body = _body_without_heading(chunk)
    if trust_level == "community":
        return (
            f"同学你好，以下是 GitLink Issue 中的社区经验，仅供排查参考：{body}\n\n"
            f"来源：{format_rag_source(chunk)}。该内容不是官方结论，请以课程助教或后续官方答复为准。"
        )
    return (
        f"同学你好，{body}\n\n"
        f"以上信息来自：{format_rag_source(chunk)}。如果后续官方通知更新，请以后续通知为准。"
    )


def format_rag_source(chunk: IndexedChunk) -> str:
    if chunk.heading and chunk.heading != chunk.source_title:
        label = f"{chunk.source_title} / {chunk.heading}"
    else:
        label = chunk.source_title
    source_url = chunk.metadata.get("source_url", "")
    return f"{label}（{source_url}）" if source_url else label
```

`summer_camp_agent/engine.py` 保持现有 `auto_reply if rag_result.is_strong else suggested_reply` 判断，不增加绕过 `is_strong` 的其他分支。仅在类型检查或格式化需要时更新引用。

- [ ] **步骤 4：运行 RAG 与引擎测试并确认通过**

运行：

```powershell
python -m unittest tests.test_rag_documents tests.test_rag_index tests.test_rag_retriever tests.test_engine -v
```

预期：全部通过，未声明可信等级的既有正式资料仍按 `official` 处理。

- [ ] **步骤 5：提交可信回复边界**

```powershell
git add summer_camp_agent/rag_retriever.py summer_camp_agent/engine.py tests/test_rag_retriever.py tests/test_engine.py
git commit -m "feat: 按 RAG 可信等级限制自动回复"
```

### 任务 4：实现 Issue 过滤与问答转换纯函数

**文件：**

- 新建：`data/gitlink_rag_sources.json`
- 新建：`tests/test_gitlink_issue_transform.py`
- 新建：`summer_camp_agent/gitlink_issue_transform.py`

- [ ] **步骤 1：写配置与领域对象失败测试**

创建 `tests/test_gitlink_issue_transform.py`，测试任务排除、官方答复、社区经验、无结论问题和附件清理：

```python
import unittest

from summer_camp_agent.gitlink_issue_transform import (
    GitLinkSource,
    extract_generated_qas,
    render_generated_qa,
    should_exclude_issue,
)


class GitLinkIssueTransformTest(unittest.TestCase):
    def setUp(self):
        self.source = GitLinkSource(
            owner="metax-maca",
            repository="op_optimization",
            excluded_labels=("任务",),
            excluded_title_patterns=(r"任务", r"打卡", r"作业提交", r"^赛题[:：]", r"指导手册"),
            trusted_authors=("yyyymmm", "yuting2003", "topshare"),
        )

    def test_excludes_task_label_and_checkin_title(self):
        tagged = {"project_issues_index": 12, "subject": "课程任务", "tags": [{"name": "任务"}]}
        checkin = {"project_issues_index": 2, "subject": "五月打卡任务", "tags": []}

        self.assertEqual(should_exclude_issue(tagged, self.source), "excluded_label:任务")
        self.assertEqual(should_exclude_issue(checkin, self.source), "excluded_title:任务")

    def test_keeps_question_with_trusted_answer_as_official(self):
        issue = {
            "project_issues_index": 13,
            "subject": "不同语言是否一起比较？",
            "description": "请问三种语言是否分榜？",
            "updated_at": "2026-07-06 16:00",
            "tags": [],
        }
        comments = [{"user": {"login": "yyyymmm"}, "notes": "同一 Track 不按语言分别设榜。"}]

        qas = extract_generated_qas(issue, comments, self.source)

        self.assertEqual(len(qas), 1)
        self.assertEqual(qas[0].trust_level, "official")
        self.assertEqual(qas[0].answer_author, "yyyymmm")
        self.assertIn("不按语言分别设榜", qas[0].answer)

    def test_keeps_explicitly_solved_user_comment_as_community(self):
        issue = {
            "project_issues_index": 15,
            "subject": "TileLang 学习 Q&A",
            "description": "欢迎提交问题。",
            "updated_at": "2026-05-21 13:09",
            "tags": [],
        }
        comments = [{
            "user": {"login": "student"},
            "notes": "## 遇到的 cmake 构建问题（已解决）\n用户名：student\n![](/api/attachments/a.png)\n执行 `pip install cmake` 后构建通过。",
        }]

        qas = extract_generated_qas(issue, comments, self.source)

        self.assertEqual(len(qas), 1)
        self.assertEqual(qas[0].trust_level, "community")
        self.assertEqual(qas[0].question, "遇到的 cmake 构建问题（已解决）")
        self.assertNotIn("用户名", qas[0].answer)
        self.assertNotIn("attachments", qas[0].answer)

    def test_skips_unconfirmed_investigation(self):
        issue = {
            "project_issues_index": 26,
            "subject": "baseline 不稳定",
            "description": "多次运行性能不同。",
            "updated_at": "2026-07-20 18:07",
            "tags": [],
        }
        comments = [{"user": {"login": "yuting2003"}, "notes": "我们会认真排查，有结果后同步。"}]

        self.assertEqual(extract_generated_qas(issue, comments, self.source), [])

    def test_rendered_markdown_contains_traceable_metadata(self):
        issue = {
            "project_issues_index": 13,
            "subject": "不同语言是否一起比较？",
            "description": "",
            "updated_at": "2026-07-06 16:00",
            "tags": [],
        }
        qa = extract_generated_qas(
            issue,
            [{"user": {"login": "yyyymmm"}, "notes": "同一 Track 不按语言分别设榜。"}],
            self.source,
        )[0]

        rendered = render_generated_qa(qa)

        self.assertIn("trust_level: official", rendered)
        self.assertIn("source_url: https://www.gitlink.org.cn/metax-maca/op_optimization/issues/13", rendered)
        self.assertIn("# 不同语言是否一起比较？", rendered)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 2：运行测试并确认模块不存在**

运行：

```powershell
python -m unittest tests.test_gitlink_issue_transform -v
```

预期：因 `summer_camp_agent.gitlink_issue_transform` 不存在而失败。

- [ ] **步骤 3：实现领域对象、过滤和清理函数**

创建 `summer_camp_agent/gitlink_issue_transform.py`，包含以下公开接口：

```python
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GitLinkSource:
    owner: str
    repository: str
    excluded_labels: tuple[str, ...]
    excluded_title_patterns: tuple[str, ...]
    trusted_authors: tuple[str, ...]

    @property
    def repository_name(self) -> str:
        return f"{self.owner}/{self.repository}"


@dataclass(frozen=True)
class GeneratedQA:
    question: str
    answer: str
    trust_level: str
    source_url: str
    source_updated_at: str
    repository: str
    issue_index: str
    answer_author: str
    filename: str


def should_exclude_issue(issue: dict, source: GitLinkSource) -> str | None:
    labels = {str(tag.get("name", "")).strip() for tag in issue.get("tags", [])}
    for label in source.excluded_labels:
        if label in labels:
            return f"excluded_label:{label}"
    subject = str(issue.get("subject", "")).strip()
    for pattern in source.excluded_title_patterns:
        if re.search(pattern, subject, flags=re.IGNORECASE):
            return f"excluded_title:{_pattern_reason(pattern, subject)}"
    return None


def sanitize_answer(text: str) -> str:
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    cleaned = re.sub(r"<img\b[^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*用户名\s*[:：].*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*issue区打卡提交记录截图\s*[:：]?.*$", "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _pattern_reason(pattern: str, subject: str) -> str:
    match = re.search(pattern, subject, flags=re.IGNORECASE)
    return match.group(0) if match else pattern
```

- [ ] **步骤 4：实现官方 FAQ 拆分和问答提取**

继续在同一文件中加入完整的提取与渲染函数：

```python
def extract_generated_qas(issue: dict, comments: list[dict], source: GitLinkSource) -> list[GeneratedQA]:
    if should_exclude_issue(issue, source):
        return []
    subject = str(issue.get("subject", "")).strip()
    description = str(issue.get("description", "")).strip()
    if "FAQ" in subject.upper():
        return _extract_faq_table(issue, description, source)

    official_comments = [
        comment
        for comment in comments
        if _comment_author(comment) in source.trusted_authors and _is_conclusive(str(comment.get("notes", "")))
    ]
    if official_comments:
        answer = sanitize_answer("\n\n".join(str(comment["notes"]) for comment in official_comments))
        if not answer:
            return []
        return [_make_qa(issue, source, subject, answer, "official", _comment_author(official_comments[-1]), "")]

    community_qas: list[GeneratedQA] = []
    for sequence, comment in enumerate(comments, start=1):
        notes = str(comment.get("notes", ""))
        if "已解决" not in notes or _looks_like_submission(notes):
            continue
        question = _first_markdown_heading(notes) or subject
        answer = sanitize_answer(_without_first_heading(notes))
        if answer:
            community_qas.append(
                _make_qa(issue, source, question, answer, "community", _comment_author(comment), f"-community-{sequence:02d}")
            )
    return community_qas


def render_generated_qa(qa: GeneratedQA) -> str:
    return (
        "---\n"
        "source_type: gitlink_issue\n"
        f"trust_level: {qa.trust_level}\n"
        f"source_url: {qa.source_url}\n"
        f"source_updated_at: \"{qa.source_updated_at}\"\n"
        f"repository: {qa.repository}\n"
        f"issue_index: \"{qa.issue_index}\"\n"
        f"answer_author: {qa.answer_author}\n"
        "---\n"
        f"# {qa.question}\n\n"
        f"{qa.answer.strip()}\n"
    )


def _extract_faq_table(issue: dict, description: str, source: GitLinkSource) -> list[GeneratedQA]:
    rows = [_split_markdown_row(line) for line in description.splitlines() if line.strip().startswith("|")]
    data_rows = [row for row in rows if len(row) >= 3 and row[0] != "问题" and not _is_separator_row(row)]
    qas: list[GeneratedQA] = []
    for sequence, row in enumerate(data_rows, start=1):
        question = sanitize_answer(row[0])
        answer = sanitize_answer(row[2].replace("<br>", "\n").replace("<br/>", "\n"))
        if question and answer:
            qas.append(_make_qa(issue, source, question, answer, "official", str(issue.get("author", {}).get("login", "")), f"-faq-{sequence:02d}"))
    return qas


def _make_qa(
    issue: dict,
    source: GitLinkSource,
    question: str,
    answer: str,
    trust_level: str,
    answer_author: str,
    filename_suffix: str,
) -> GeneratedQA:
    index = str(issue["project_issues_index"])
    return GeneratedQA(
        question=question.strip(),
        answer=answer.strip(),
        trust_level=trust_level,
        source_url=f"https://www.gitlink.org.cn/{source.owner}/{source.repository}/issues/{index}",
        source_updated_at=str(issue.get("updated_at", "")),
        repository=source.repository_name,
        issue_index=index,
        answer_author=answer_author,
        filename=f"issue-{index}{filename_suffix}.md",
    )


def _comment_author(comment: dict) -> str:
    return str(comment.get("user", {}).get("login", "")).strip()


def _is_conclusive(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    pending_phrases = ("会认真排查", "有结果后", "后续同步", "正在整理", "待确认", "尽快修复")
    return not any(phrase in normalized for phrase in pending_phrases)


def _looks_like_submission(text: str) -> bool:
    markers = ("作业提交", "打卡提交", "用户名：", "issue区打卡提交记录截图")
    return any(marker in text for marker in markers)


def _first_markdown_heading(text: str) -> str:
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+)$", line.strip())
        if match:
            return match.group(1).strip()
    return ""


def _without_first_heading(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#{1,6}\s+", line.strip()):
            return "\n".join(lines[index + 1 :]).strip()
    return text.strip()


def _split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def _is_separator_row(row: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in row)
```

- [ ] **步骤 5：添加实际仓库同步配置**

创建 `data/gitlink_rag_sources.json`：

```json
{
  "schema_version": 1,
  "repositories": [
    {
      "owner": "metax-maca",
      "repository": "op_optimization",
      "excluded_labels": ["任务"],
      "excluded_title_patterns": ["任务", "打卡", "作业提交", "^赛题[:：]", "指导手册"],
      "trusted_authors": ["yyyymmm", "yuting2003", "topshare", "Beckylu", "Dayuxiaoshui", "L1ngYi", "cory", "p295ilteb"]
    },
    {
      "owner": "ccf-ai-infra",
      "repository": "Intro-ops",
      "excluded_labels": ["任务"],
      "excluded_title_patterns": ["任务", "打卡", "作业提交"],
      "trusted_authors": ["ccfzj", "p295ilteb", "wawahejun"]
    }
  ]
}
```

- [ ] **步骤 6：运行转换测试并确认通过**

运行：

```powershell
python -m unittest tests.test_gitlink_issue_transform -v
```

预期：全部通过。

- [ ] **步骤 7：提交转换核心**

```powershell
git add data/gitlink_rag_sources.json summer_camp_agent/gitlink_issue_transform.py tests/test_gitlink_issue_transform.py
git commit -m "feat: 过滤并转换 GitLink Issue 问答"
```

### 任务 5：实现分页同步、失败保护和原子快照

**文件：**

- 新建：`tests/test_gitlink_issue_sync.py`
- 新建：`summer_camp_agent/gitlink_issue_sync.py`

- [ ] **步骤 1：先写同步失败与成功快照测试**

创建 `tests/test_gitlink_issue_sync.py`：

```python
import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.gitlink_issue_sync import GitLinkSyncError, sync_gitlink_issues


class GitLinkIssueSyncTest(unittest.TestCase):
    def _write_config(self, root: Path) -> Path:
        path = root / "sources.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "repositories": [{
                "owner": "example",
                "repository": "course",
                "excluded_labels": ["任务"],
                "excluded_title_patterns": ["任务", "打卡"],
                "trusted_authors": ["organizer"],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        return path

    def test_successful_sync_filters_task_and_writes_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            output = root / "documents"
            report = root / "report.json"

            def fetch_json(url: str):
                if url.endswith("/issues?page=1&limit=100"):
                    return {
                        "total_count": 2,
                        "issues": [
                            {"project_issues_index": 12, "subject": "课程任务", "tags": [{"name": "任务"}]},
                            {"project_issues_index": 13, "subject": "不同语言是否一起比较？", "tags": []},
                        ],
                    }
                if url.endswith("/issues/13"):
                    return {
                        "project_issues_index": 13,
                        "subject": "不同语言是否一起比较？",
                        "description": "是否分榜？",
                        "updated_at": "2026-07-06 16:00",
                        "tags": [],
                    }
                if url.endswith("/issues/13/journals?page=1&limit=100"):
                    return {
                        "total_count": 1,
                        "journals": [{"user": {"login": "organizer"}, "notes": "同一 Track 不按语言分别设榜。"}],
                    }
                raise AssertionError(url)

            summary = sync_gitlink_issues(config, output, report, fetch_json=fetch_json)

            generated = list(output.rglob("*.md"))
            saved_report = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(summary.generated_official, 1)
        self.assertEqual(len(generated), 1)
        self.assertNotIn("issue-12", generated[0].name)
        self.assertEqual(saved_report["generated_official"], 1)
        self.assertEqual(saved_report["repositories"][0]["fetched_issues"], 2)
        self.assertEqual(saved_report["skipped_by_reason"]["excluded_label:任务"], 1)

    def test_fetch_failure_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            output = root / "documents"
            output.mkdir()
            previous = output / "previous.md"
            previous.write_text("# 上次成功快照\n", encoding="utf-8")

            def failing_fetch_json(url: str):
                raise OSError("network down")

            with self.assertRaisesRegex(GitLinkSyncError, "example/course"):
                sync_gitlink_issues(config, output, root / "report.json", fetch_json=failing_fetch_json)

            self.assertTrue(previous.exists())
            self.assertEqual(previous.read_text(encoding="utf-8"), "# 上次成功快照\n")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 2：运行测试并确认同步模块不存在**

运行：

```powershell
python -m unittest tests.test_gitlink_issue_sync -v
```

预期：因 `summer_camp_agent.gitlink_issue_sync` 不存在而失败。

- [ ] **步骤 3：实现配置读取和 GitLink 分页客户端**

创建 `summer_camp_agent/gitlink_issue_sync.py`，先加入类型、配置和 HTTP 函数：

```python
from __future__ import annotations

import json
import shutil
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .gitlink_issue_transform import GitLinkSource, extract_generated_qas, render_generated_qa, should_exclude_issue


FetchJson = Callable[[str], dict]


class GitLinkSyncError(RuntimeError):
    """GitLink Issue 同步未能生成完整安全快照。"""


@dataclass(frozen=True)
class GitLinkSyncSummary:
    fetched_issues: int
    generated_official: int
    generated_community: int
    skipped_by_reason: dict[str, int]
    errors: list[dict[str, str]]
    repositories: list[dict[str, object]]


def _fetch_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "summer-camp-reply-agent/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise GitLinkSyncError(f"GitLink API 请求失败：{url}：{exc}") from exc
    if not isinstance(payload, dict):
        raise GitLinkSyncError(f"GitLink API 返回格式异常：{url}")
    return payload


def _load_sources(config_path: Path) -> list[GitLinkSource]:
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GitLinkSyncError(f"无法读取 GitLink 同步配置：{config_path}：{exc}") from exc
    if raw.get("schema_version") != 1 or not isinstance(raw.get("repositories"), list):
        raise GitLinkSyncError("GitLink 同步配置版本或 repositories 格式异常。")
    try:
        return [
            GitLinkSource(
                owner=str(item["owner"]),
                repository=str(item["repository"]),
                excluded_labels=tuple(str(value) for value in item.get("excluded_labels", [])),
                excluded_title_patterns=tuple(str(value) for value in item.get("excluded_title_patterns", [])),
                trusted_authors=tuple(str(value) for value in item.get("trusted_authors", [])),
            )
            for item in raw["repositories"]
        ]
    except (KeyError, TypeError) as exc:
        raise GitLinkSyncError("GitLink 同步配置缺少 owner 或 repository。") from exc


def _paged_items(base_url: str, collection_key: str, fetch_json: FetchJson) -> list[dict]:
    page = 1
    limit = 100
    items: list[dict] = []
    while True:
        payload = fetch_json(f"{base_url}?page={page}&limit={limit}")
        page_items = payload.get(collection_key)
        if not isinstance(page_items, list):
            raise GitLinkSyncError(f"GitLink API 缺少数组字段 {collection_key}：{base_url}")
        items.extend(item for item in page_items if isinstance(item, dict))
        total_count = int(payload.get("total_count", len(items)))
        if len(items) >= total_count or not page_items:
            return items
        page += 1
```

- [ ] **步骤 4：实现完整同步与快照替换**

继续加入同步函数和安全替换函数：

```python
def sync_gitlink_issues(
    config_path: str | Path,
    output_dir: str | Path,
    report_path: str | Path,
    fetch_json: FetchJson = _fetch_json,
) -> GitLinkSyncSummary:
    sources = _load_sources(Path(config_path))
    target = Path(output_dir).resolve()
    report_target = Path(report_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    skipped: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    fetched_issues = 0
    generated_official = 0
    generated_community = 0
    repository_stats: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="gitlink-rag-", dir=target.parent) as directory:
        staging = Path(directory) / target.name
        staging.mkdir()
        for source in sources:
            source_skipped: Counter[str] = Counter()
            source_official = 0
            source_community = 0
            api_base = f"https://www.gitlink.org.cn/api/v1/{source.owner}/{source.repository}"
            try:
                summaries = _paged_items(f"{api_base}/issues", "issues", fetch_json)
            except Exception as exc:
                raise GitLinkSyncError(f"同步 {source.repository_name} 失败：{exc}") from exc
            fetched_issues += len(summaries)
            repository_dir = staging / source.owner / source.repository
            repository_dir.mkdir(parents=True, exist_ok=True)
            for summary in summaries:
                exclusion = should_exclude_issue(summary, source)
                if exclusion:
                    skipped[exclusion] += 1
                    source_skipped[exclusion] += 1
                    continue
                index = str(summary.get("project_issues_index", ""))
                issue_url = f"{api_base}/issues/{index}"
                try:
                    issue = fetch_json(issue_url)
                    comments = _paged_items(f"{issue_url}/journals", "journals", fetch_json)
                    qas = extract_generated_qas(issue, comments, source)
                except GitLinkSyncError:
                    raise
                except (KeyError, TypeError, ValueError) as exc:
                    errors.append({
                        "issue_url": f"https://www.gitlink.org.cn/{source.owner}/{source.repository}/issues/{index}",
                        "reason": str(exc),
                    })
                    continue
                if not qas:
                    skipped["no_usable_answer"] += 1
                    source_skipped["no_usable_answer"] += 1
                    continue
                for qa in qas:
                    (repository_dir / qa.filename).write_text(render_generated_qa(qa), encoding="utf-8")
                    if qa.trust_level == "official":
                        generated_official += 1
                        source_official += 1
                    else:
                        generated_community += 1
                        source_community += 1
            repository_stats.append({
                "repository": source.repository_name,
                "fetched_issues": len(summaries),
                "generated_official": source_official,
                "generated_community": source_community,
                "skipped_by_reason": dict(sorted(source_skipped.items())),
            })

        if generated_official + generated_community == 0:
            raise GitLinkSyncError("同步结果没有可用问答，已保留上一次成功快照。")

        summary = GitLinkSyncSummary(
            fetched_issues=fetched_issues,
            generated_official=generated_official,
            generated_community=generated_community,
            skipped_by_reason=dict(sorted(skipped.items())),
            errors=errors,
            repositories=repository_stats,
        )
        _replace_directory(staging, target)

    report_target.parent.mkdir(parents=True, exist_ok=True)
    report_payload = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        **asdict(summary),
    }
    _write_json_atomically(report_target, report_payload)
    return summary


def _replace_directory(staging: Path, target: Path) -> None:
    backup = target.with_name(f"{target.name}.previous")
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        target.rename(backup)
    try:
        staging.rename(target)
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        if backup.exists():
            backup.rename(target)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


def _write_json_atomically(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
```

- [ ] **步骤 5：运行同步测试并确认通过**

运行：

```powershell
python -m unittest tests.test_gitlink_issue_transform tests.test_gitlink_issue_sync -v
```

预期：全部通过；失败测试确认旧快照内容原样保留。

- [ ] **步骤 6：提交同步编排**

```powershell
git add summer_camp_agent/gitlink_issue_sync.py tests/test_gitlink_issue_sync.py
git commit -m "feat: 增加 GitLink Issue 原子同步"
```

### 任务 6：增加同步命令和运营文档

**文件：**

- 修改：`tests/test_cli.py`
- 修改：`summer_camp_agent/cli.py`
- 新建：`scripts/sync_gitlink_issues.py`
- 修改：`data/rag/documents/README.md`

- [ ] **步骤 1：先写 CLI 失败测试**

在 `tests/test_cli.py` 中加入使用本地 `file://` 不方便模拟的参数解析测试，直接调用 `main` 并 mock 同步函数：

```python
from unittest.mock import patch

from summer_camp_agent.cli import main
from summer_camp_agent.gitlink_issue_sync import GitLinkSyncSummary

def test_sync_gitlink_command_prints_safe_summary(self):
    summary = GitLinkSyncSummary(
        fetched_issues=36,
        generated_official=18,
        generated_community=1,
        skipped_by_reason={"excluded_label:任务": 2, "no_usable_answer": 15},
        errors=[],
        repositories=[{
            "repository": "metax-maca/op_optimization",
            "fetched_issues": 26,
            "generated_official": 18,
            "generated_community": 0,
            "skipped_by_reason": {"excluded_label:任务": 1, "no_usable_answer": 7},
        }],
    )
    with patch("summer_camp_agent.cli.sync_gitlink_issues", return_value=summary):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            exit_code = main([
                "sync-gitlink",
                "--config", "data/gitlink_rag_sources.json",
                "--output", "data/rag/documents/gitlink-issues",
                "--report", "data/rag/gitlink-sync-report.json",
            ])

    self.assertEqual(exit_code, 0)
    self.assertIn("fetched_issues: 36", stdout.getvalue())
    self.assertIn("generated_official: 18", stdout.getvalue())
    self.assertNotIn("用户名", stdout.getvalue())
```

同时在文件顶部增加：

```python
import io
```

- [ ] **步骤 2：运行测试并确认子命令不存在**

运行：

```powershell
python -m unittest tests.test_cli.CLITest.test_sync_gitlink_command_prints_safe_summary -v
```

预期：`sync-gitlink` 不是有效子命令，测试失败。

- [ ] **步骤 3：实现 CLI 子命令和异常处理**

在 `summer_camp_agent/cli.py` 导入同步异常和 RAG 文档异常：

```python
from .gitlink_issue_sync import GitLinkSyncError, sync_gitlink_issues
from .rag_documents import RagDocumentError
```

在解析器定义处加入：

```python
sync_gitlink_parser = subparsers.add_parser("sync-gitlink", help="同步并过滤 GitLink Issue 问答")
sync_gitlink_parser.add_argument("--config", default="data/gitlink_rag_sources.json", help="同步来源配置")
sync_gitlink_parser.add_argument("--output", default="data/rag/documents/gitlink-issues", help="生成问答目录")
sync_gitlink_parser.add_argument("--report", default="data/rag/gitlink-sync-report.json", help="同步报告路径")
```

在命令分发中加入：

```python
if args.command == "sync-gitlink":
    return _sync_gitlink(args)
```

在异常处理分支加入：

```python
except GitLinkSyncError as exc:
    print(str(exc), file=sys.stderr)
    return 2
except RagDocumentError as exc:
    print(str(exc), file=sys.stderr)
    return 2
```

增加完整输出函数：

```python
def _sync_gitlink(args: argparse.Namespace) -> int:
    summary = sync_gitlink_issues(Path(args.config), Path(args.output), Path(args.report))
    print(f"fetched_issues: {summary.fetched_issues}")
    print(f"generated_official: {summary.generated_official}")
    print(f"generated_community: {summary.generated_community}")
    print(f"skipped_count: {sum(summary.skipped_by_reason.values())}")
    print(f"error_count: {len(summary.errors)}")
    print(f"output: {args.output}")
    print(f"report: {args.report}")
    return 0
```

- [ ] **步骤 4：增加脚本入口**

创建 `scripts/sync_gitlink_issues.py`：

```python
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from summer_camp_agent.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["sync-gitlink", *sys.argv[1:]]))
```

- [ ] **步骤 5：更新 RAG 中文维护说明**

在 `data/rag/documents/README.md` 增加以下命令和边界：

````markdown
## 同步 GitLink Issue 问答

```text
python scripts/sync_gitlink_issues.py
```

同步器读取 `data/gitlink_rag_sources.json`，排除任务、打卡和作业提交，并把有效问答写入 `gitlink-issues/`。`official` 来源可在强匹配时自动回复；`community` 来源只能进入运营确认流程。可信账号列表必须经人工确认后修改。

同步完成后重新生成索引：

```text
python -m summer_camp_agent.cli rag-index --documents data/rag/documents --index data/rag/index
```

同步失败时旧问答快照和旧索引均保留，不要手工删除旧目录。
````

- [ ] **步骤 6：运行 CLI 测试并确认通过**

运行：

```powershell
python -m unittest tests.test_cli tests.test_gitlink_issue_sync -v
```

预期：全部通过。

- [ ] **步骤 7：提交同步命令与说明**

```powershell
git add summer_camp_agent/cli.py scripts/sync_gitlink_issues.py tests/test_cli.py data/rag/documents/README.md
git commit -m "feat: 提供 GitLink 问答同步命令"
```

### 任务 7：执行真实同步并验证生成快照

**文件：**

- 新建：`data/rag/documents/gitlink-issues/**`
- 新建：`data/rag/gitlink-sync-report.json`

- [ ] **步骤 1：运行真实同步**

运行：

```powershell
python scripts/sync_gitlink_issues.py
```

预期：退出码为 0，输出包含非零 `fetched_issues` 和 `generated_official`，报告路径为 `data/rag/gitlink-sync-report.json`。

- [ ] **步骤 2：验证任务与个人提交未进入快照**

运行：

```powershell
rg -n "issues/12|issues/16|作业提交|打卡提交|用户名[:：]|/api/attachments/" data/rag/documents/gitlink-issues
```

预期：无输出且退出码为 1。

- [ ] **步骤 3：验证来源与可信等级完整**

运行：

```powershell
$files = Get-ChildItem -Path data/rag/documents/gitlink-issues -Recurse -Filter *.md
$missing = foreach ($file in $files) {
    $text = Get-Content -Raw -Encoding UTF8 $file.FullName
    if ($text -notmatch 'source_type: gitlink_issue' -or $text -notmatch 'trust_level: (official|community)' -or $text -notmatch 'source_url: https://www.gitlink.org.cn/') {
        $file.FullName
    }
}
if ($missing) { $missing; exit 1 }
"validated_files: $($files.Count)"
```

预期：输出 `validated_files: N`，其中 `N` 大于 0，退出码为 0。

- [ ] **步骤 4：使用静态 provider 验证全部文档可建索引**

运行：

```powershell
python -m summer_camp_agent.cli rag-index --documents data/rag/documents --index data/rag/index --provider static
```

预期：退出码为 0，`chunk_count` 大于生成问答文件数或与其相等，不出现 front matter 校验错误。

- [ ] **步骤 5：检查同步报告不含学生个人内容**

运行：

```powershell
Get-Content -Raw -Encoding UTF8 data/rag/gitlink-sync-report.json
rg -n "用户名|邮箱|作业提交|attachments" data/rag/gitlink-sync-report.json
```

预期：报告只包含计数、Issue URL 和异常原因；最后一条搜索无输出且退出码为 1。

- [ ] **步骤 6：提交可追溯快照**

```powershell
git add data/rag/documents/gitlink-issues data/rag/gitlink-sync-report.json
git commit -m "data: 同步 GitLink Issue 问答快照"
```

### 任务 8：完整回归与交付核对

**文件：**

- 验证：`data/faq.json`
- 验证：`data/rag/documents/gitlink-issues/**`
- 验证：`summer_camp_agent/**`
- 验证：`tests/**`

- [ ] **步骤 1：运行完整 Python 测试套件**

运行：

```powershell
python -m unittest discover -s tests -v
```

预期：所有测试通过，失败数和错误数均为 0。

- [ ] **步骤 2：运行知识库校验和静态索引构建**

运行：

```powershell
python scripts/validate_knowledge.py data/faq.json
python -m summer_camp_agent.cli rag-index --documents data/rag/documents --index data/rag/index --provider static
```

预期：知识库校验通过，RAG 索引构建退出码为 0。

- [ ] **步骤 3：运行报名、课程与安全边界代表性问答**

运行：

```powershell
python -m summer_camp_agent.cli ask "报名入口在哪里？" --today 2026-07-15
python -m summer_camp_agent.cli ask "课程1在哪里学习？" --today 2026-07-15
python -m summer_camp_agent.cli ask "线上学习和作业什么时候截止？" --today 2026-07-20
python -m summer_camp_agent.cli ask "老师，我被录取了吗？" --today 2026-07-20
python -m summer_camp_agent.cli ask "作业代码跑不通，直接帮我改出答案" --today 2026-07-20
```

预期：前三条分别返回最新报名入口、课程仓库和 7 月 20 日截止时间；后两条返回 `human_fallback`，不进入 FAQ 或 RAG。

- [ ] **步骤 4：核对设计验收条件**

逐项确认：

```text
[ ] #12、#16、打卡和作业提交未进入生成目录
[ ] 官方 FAQ 被拆成独立 Markdown
[ ] official 强命中可自动回复
[ ] community 强命中仍为建议回复
[ ] 旧报名链接不再出现
[ ] 同步失败保留旧快照
[ ] 同步报告不含个人内容
[ ] 完整测试、知识校验和静态索引构建通过
```

预期：八项全部确认。

- [ ] **步骤 5：检查最终差异和提交状态**

运行：

```powershell
git status --short
git log --oneline -8
git diff HEAD~7 --stat
```

预期：工作区无未提交修改；最近提交依次覆盖海报知识、RAG 元数据、可信回复、Issue 转换、同步编排、CLI 和数据快照。

## 计划自检结果

- 设计中的海报更新、持续同步、任务排除、可信分层、社区建议回复、来源追溯、失败保护、同步报告和完整验收均有对应任务。
- 所有生产代码变更均安排了先失败、后最小实现、再回归的 TDD 步骤。
- `GitLinkSource`、`GeneratedQA`、`GitLinkSyncSummary`、`sync_gitlink_issues`、`RagSearchResult.trust_level` 和 `source_url` 的命名在各任务中保持一致。
- 本计划不包含定时调度、GitLink 写操作、个人状态查询或作业代答，范围与设计文档一致。
