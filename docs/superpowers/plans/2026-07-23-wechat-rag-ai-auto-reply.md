# 微信 RAG AI 自动回复实施计划

> **面向执行代理：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。所有步骤使用复选框跟踪。

**目标：** 在微信消息命中规则但 FAQ 未命中时，基于高置信官方 RAG 证据调用 OpenAI 生成自然回复，并在 AI 失败时安全降级为官方原文。

**架构：** 保留“人工兜底 → FAQ → RAG”的确定性事实路由，在 RAG 高置信官方命中之后插入独立的回答生成器。生成器使用 OpenAI Responses API 和结构化输出；问答引擎校验生成结果并决定使用 `rag_ai` 或 `rag_fallback`，工作台继续承担模式判断、模拟或真实发送以及日志记录。

**技术栈：** Python 3 标准库、`unittest`、OpenAI Responses API、Electron、React、TypeScript。

---

## 文件职责

- 新建 `summer_camp_agent/rag_ai.py`：定义生成结果、生成器协议、OpenAI Responses API 客户端、结构化响应解析与本地输出校验。
- 修改 `summer_camp_agent/engine.py`：在高置信官方 RAG 命中后调用生成器，并实现原文降级。
- 修改 `summer_camp_agent/rag_runtime.py`：从环境变量创建可选 OpenAI 生成器。
- 修改 `summer_camp_agent/workbench_session.py`：向默认问答引擎注入生成器，并把生成元数据写入工作轨迹与发送日志。
- 修改 `summer_camp_agent/workbench_server.py`：仅在真实工作台启动时加载默认 OpenAI 生成器，避免单元测试意外访问网络。
- 修改 `summer_camp_agent/review.py`、`summer_camp_agent/workbench_models.py`、`summer_camp_agent/workbench_api.py`：透传和序列化生成方式、模型与错误类型。
- 修改 `desktop/src/shared/types.ts`、`desktop/src/renderer/App.tsx`：在详情区显示生成方式与模型。
- 新建 `tests/test_rag_ai.py`：覆盖请求协议、响应解析、输出校验和错误映射。
- 修改 `tests/test_engine.py`、`tests/test_workbench_session.py`、`tests/test_workbench_api.py`、`desktop/tests/static.test.mjs`：覆盖集成行为与元数据。
- 修改 `tests/test_full_reply_chain.py`：覆盖多个 RAG 命中场景、社区阻断、未知问题和降级路径。
- 新建 `scripts/verify_rag_ai_reply.py`：使用真实 OpenAI 接口与模拟微信发送器完成三场景联调。
- 修改 `docs/technical-architecture.md`：记录 AI 生成环境变量、事实边界和降级行为。

### 任务 1：实现 OpenAI RAG 回答生成器

**文件：**

- 新建：`summer_camp_agent/rag_ai.py`
- 新建：`tests/test_rag_ai.py`

- [ ] **步骤 1：先写请求协议与成功解析的失败测试**

在 `tests/test_rag_ai.py` 创建可捕获 HTTP 请求的上下文管理器，并验证模型、问题、证据、结构化输出配置与解析结果：

```python
import json
import unittest
from unittest.mock import patch

from summer_camp_agent.rag_ai import OpenAIRagAnswerGenerator
from summer_camp_agent.rag_index import IndexedChunk
from summer_camp_agent.rag_retriever import RagSearchResult, ScoredChunk


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def official_result():
    chunk = IndexedChunk(
        chunk_id="chunk-1",
        source_path="issue-19.md",
        source_title="比赛镜像",
        source_sha256="sha256:test",
        heading="请问能否公开下载比赛镜像？",
        text="请问能否公开下载比赛镜像？\n可以通过开发者社区下载。",
        metadata={
            "trust_level": "official",
            "source_url": "https://www.gitlink.org.cn/example/issues/19",
        },
        embedding=[],
    )
    return RagSearchResult(
        reply="可以通过开发者社区下载。",
        source="比赛镜像（https://www.gitlink.org.cn/example/issues/19）",
        confidence=0.96,
        chunks=[ScoredChunk(chunk, 0.96)],
        is_strong=True,
        trust_level="official",
        source_url="https://www.gitlink.org.cn/example/issues/19",
    )


class OpenAIRagAnswerGeneratorTest(unittest.TestCase):
    def test_sends_grounded_structured_response_request_and_parses_answer(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse(
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {"answer": "可以在开发者社区下载比赛镜像。", "grounded": True},
                                        ensure_ascii=False,
                                    ),
                                }
                            ],
                        }
                    ]
                }
            )

        generator = OpenAIRagAnswerGenerator(api_key="test-key", model="gpt-test", timeout_seconds=7)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = generator.generate("比赛镜像能下载吗？", official_result())

        self.assertEqual(result.status, "generated")
        self.assertEqual(result.answer, "可以在开发者社区下载比赛镜像。")
        self.assertEqual(result.model, "gpt-test")
        self.assertEqual(captured["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(captured["body"]["model"], "gpt-test")
        self.assertEqual(captured["body"]["text"]["format"]["type"], "json_schema")
        self.assertIn("比赛镜像能下载吗？", captured["body"]["input"])
        self.assertIn("可以通过开发者社区下载", captured["body"]["input"])
```

- [ ] **步骤 2：运行测试并确认因模块不存在而失败**

运行：

```powershell
python -m unittest tests.test_rag_ai.OpenAIRagAnswerGeneratorTest.test_sends_grounded_structured_response_request_and_parses_answer -v
```

预期：`FAIL` 或 `ERROR`，明确提示 `summer_camp_agent.rag_ai` 不存在。

- [ ] **步骤 3：实现最小生成器、请求构造和成功响应解析**

在 `summer_camp_agent/rag_ai.py` 实现以下公开接口：

```python
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .rag_retriever import RagSearchResult


DEFAULT_OPENAI_CHAT_MODEL = "gpt-5.6-luna"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
MAX_GENERATED_REPLY_CHARS = 600


@dataclass(frozen=True)
class RagGenerationResult:
    status: str
    answer: str = ""
    model: str = ""
    error: str = ""


class RagAnswerGenerator(Protocol):
    model: str

    def generate(self, question: str, rag_result: RagSearchResult) -> RagGenerationResult:
        ...


class OpenAIRagAnswerGenerator:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_OPENAI_CHAT_MODEL,
        base_url: str = DEFAULT_OPENAI_BASE_URL,
        timeout_seconds: int = 15,
    ):
        self._api_key = api_key.strip()
        self.model = model.strip() or DEFAULT_OPENAI_CHAT_MODEL
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> "OpenAIRagAnswerGenerator | None":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            model=os.environ.get("OPENAI_CHAT_MODEL", DEFAULT_OPENAI_CHAT_MODEL),
            base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        )

    def generate(self, question: str, rag_result: RagSearchResult) -> RagGenerationResult:
        evidence = _build_evidence(rag_result)
        if not evidence:
            return RagGenerationResult("invalid", model=self.model, error="missing_evidence")
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=json.dumps(_request_payload(self.model, question, evidence), ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
            answer, grounded = _parse_response(raw_body)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            return RagGenerationResult("unavailable", model=self.model, error=_error_code(exc))
        except (ValueError, json.JSONDecodeError):
            return RagGenerationResult("invalid", model=self.model, error="invalid_response")
        if not grounded:
            return RagGenerationResult("invalid", model=self.model, error="not_grounded")
        validation_error = validate_generated_answer(answer, evidence, rag_result.source_url)
        if validation_error:
            return RagGenerationResult("invalid", model=self.model, error=validation_error)
        return RagGenerationResult("generated", answer=answer.strip(), model=self.model)
```

同一文件中加入完整的证据、请求和响应辅助函数：

```python
SYSTEM_INSTRUCTIONS = """你是夏令营咨询群回复助手。只能依据用户提供的官方证据回答。
不得补充证据中没有的日期、数字、链接、规则或承诺；证据不足时将 grounded 设为 false。
面向学生直接作答，使用简洁自然的中文，不输出 Markdown 标题、代码块或内部分析过程。"""


def _build_evidence(rag_result: RagSearchResult) -> str:
    if not rag_result.chunks:
        return ""
    best = rag_result.chunks[0].chunk
    if best.metadata.get("trust_level", "official") != "official":
        return ""
    return (
        f"标题：{best.heading or best.source_title}\n"
        f"正文：{best.text.strip()}\n"
        f"来源：{rag_result.source}\n"
        f"来源地址：{rag_result.source_url}"
    ).strip()


def _request_payload(model: str, question: str, evidence: str) -> dict[str, object]:
    return {
        "model": model,
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": f"学生问题：\n{question.strip()}\n\n官方证据：\n{evidence}",
        "reasoning": {"effort": "none"},
        "max_output_tokens": 500,
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "rag_reply",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string"},
                        "grounded": {"type": "boolean"},
                    },
                    "required": ["answer", "grounded"],
                    "additionalProperties": False,
                },
            }
        },
    }


def _parse_response(raw_body: str) -> tuple[str, bool]:
    payload = json.loads(raw_body)
    output = payload.get("output") if isinstance(payload, dict) else None
    if not isinstance(output, list):
        raise ValueError("Responses API 缺少 output。")
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            parsed = json.loads(str(part.get("text") or ""))
            answer = parsed.get("answer") if isinstance(parsed, dict) else None
            grounded = parsed.get("grounded") if isinstance(parsed, dict) else None
            if not isinstance(answer, str) or not isinstance(grounded, bool):
                raise ValueError("Responses API 结构化输出字段类型错误。")
            return answer, grounded
    raise ValueError("Responses API 缺少 output_text。")
```

- [ ] **步骤 4：运行成功路径测试并确认通过**

运行：

```powershell
python -m unittest tests.test_rag_ai.OpenAIRagAnswerGeneratorTest.test_sends_grounded_structured_response_request_and_parses_answer -v
```

预期：`1 test`，`OK`。

- [ ] **步骤 5：先添加失败、拒答和输出校验测试**

在 `tests/test_rag_ai.py` 增加：

```python
    def test_rejects_ungrounded_answer(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")
        response = {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"answer":"猜测回复","grounded":false}'}]}]}
        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(response)):
            result = generator.generate("问题", official_result())
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.error, "not_grounded")

    def test_rejects_url_not_present_in_evidence(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")
        response = {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"answer":"请访问 https://invalid.example.com","grounded":true}'}]}]}
        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(response)):
            result = generator.generate("问题", official_result())
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.error, "unsupported_url")

    def test_rejects_reply_longer_than_limit(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")
        response = {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"answer":"答" * 601,"grounded":True}, ensure_ascii=False)}]}]}
        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(response)):
            result = generator.generate("问题", official_result())
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.error, "answer_too_long")

    def test_maps_timeout_to_unavailable(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")
        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            result = generator.generate("问题", official_result())
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.error, "timeout")

    def test_from_env_returns_none_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(OpenAIRagAnswerGenerator.from_env())
```

- [ ] **步骤 6：运行新增测试并确认校验功能尚未完备时失败**

运行：

```powershell
python -m unittest tests.test_rag_ai -v
```

预期：至少一个新增校验或错误映射测试失败，失败原因对应尚未实现的规则。

- [ ] **步骤 7：实现确定性输出校验和错误映射**

在 `summer_camp_agent/rag_ai.py` 增加：

```python
import re


URL_PATTERN = re.compile(r"https?://[^\s，。；、]+")


def validate_generated_answer(answer: str, evidence: str, source_url: str = "") -> str:
    normalized = answer.strip()
    if not normalized:
        return "empty_answer"
    if len(normalized) > MAX_GENERATED_REPLY_CHARS:
        return "answer_too_long"
    allowed_text = f"{evidence}\n{source_url}"
    if any(url not in allowed_text for url in URL_PATTERN.findall(normalized)):
        return "unsupported_url"
    if normalized.startswith("{") or "```" in normalized:
        return "invalid_wrapper"
    return ""


def _error_code(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib.error.HTTPError):
        return f"http_{exc.code}"
    return "network_error"
```

确保 `_parse_response` 只读取 `output` 中 `type == "message"` 的 `output_text.text`，并把其中 JSON 解码为 `answer: str` 和 `grounded: bool`；类型不符时抛出 `ValueError`。

- [ ] **步骤 8：运行生成器全部测试并提交**

运行：

```powershell
python -m unittest tests.test_rag_ai -v
```

预期：全部通过，输出 `OK`。

提交：

```powershell
git add -- summer_camp_agent/rag_ai.py tests/test_rag_ai.py
git commit -m "feat: 增加 RAG AI 回答生成器"
```

### 任务 2：把 AI 生成与安全降级接入问答引擎

**文件：**

- 修改：`summer_camp_agent/engine.py`
- 修改：`tests/test_engine.py`

- [ ] **步骤 1：先写官方 RAG 生成成功与失败降级测试**

在 `tests/test_engine.py` 增加假生成器与两个测试：

```python
from summer_camp_agent.rag_ai import RagGenerationResult
from summer_camp_agent.rag_index import IndexedChunk
from summer_camp_agent.rag_retriever import ScoredChunk


class FakeRagAnswerGenerator:
    model = "fake-model"

    def __init__(self, result):
        self.result = result
        self.calls = []

    def generate(self, question, rag_result):
        self.calls.append((question, rag_result))
        return self.result


def strong_official_rag_result():
    chunk = IndexedChunk(
        chunk_id="chunk-1",
        source_path="issue-19.md",
        source_title="比赛镜像",
        source_sha256="sha256:test",
        heading="比赛镜像",
        text="比赛镜像\n可以从开发者社区下载。",
        metadata={"trust_level": "official", "source_url": "https://www.gitlink.org.cn/example/issues/19"},
        embedding=[],
    )
    return RagSearchResult(
        reply="可以从开发者社区下载。",
        source="比赛镜像",
        confidence=0.96,
        chunks=[ScoredChunk(chunk, 0.96)],
        is_strong=True,
        trust_level="official",
        source_url="https://www.gitlink.org.cn/example/issues/19",
    )


    def test_strong_official_rag_uses_ai_generated_answer(self):
        rag_result = strong_official_rag_result()
        generator = FakeRagAnswerGenerator(RagGenerationResult("generated", "AI 整理后的回复", "fake-model"))
        engine = AnswerEngine(
            KnowledgeBase.from_default(),
            rag_retriever=FakeRagRetriever(rag_result),
            rag_answer_generator=generator,
        )

        result = engine.answer("比赛镜像能下载吗？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.reply, "AI 整理后的回复")
        self.assertEqual(result.generation_mode, "rag_ai")
        self.assertEqual(result.generation_model, "fake-model")
        self.assertEqual(len(generator.calls), 1)

    def test_ai_failure_falls_back_to_official_rag_text(self):
        rag_result = strong_official_rag_result()
        generator = FakeRagAnswerGenerator(RagGenerationResult("unavailable", model="fake-model", error="timeout"))
        engine = AnswerEngine(
            KnowledgeBase.from_default(),
            rag_retriever=FakeRagRetriever(rag_result),
            rag_answer_generator=generator,
        )

        result = engine.answer("比赛镜像能下载吗？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.reply, rag_result.reply)
        self.assertEqual(result.generation_mode, "rag_fallback")
        self.assertEqual(result.generation_error, "timeout")
```

- [ ] **步骤 2：运行两个测试并确认构造参数或字段缺失导致失败**

运行：

```powershell
python -m unittest tests.test_engine.AnswerEngineTest.test_strong_official_rag_uses_ai_generated_answer tests.test_engine.AnswerEngineTest.test_ai_failure_falls_back_to_official_rag_text -v
```

预期：失败信息指向 `rag_answer_generator` 或 `generation_mode` 尚不存在。

- [ ] **步骤 3：实现生成器注入、生成成功与原文降级**

在 `AnswerResult` 末尾增加默认字段：

```python
    generation_mode: str = ""
    generation_model: str = ""
    generation_error: str = ""
```

给 `AnswerEngine.__init__` 增加 `rag_answer_generator=None` 并保存。把 RAG 分支改为：

```python
        rag_result = self._retrieve_from_rag(text)
        if rag_result is not None:
            generation_mode = "rag_community" if rag_result.trust_level == "community" else "rag_fallback"
            generation_model = ""
            generation_error = ""
            reply = rag_result.reply
            if (
                rag_result.trust_level == "official"
                and rag_result.is_strong
                and self.rag_answer_generator is not None
                and rag_result.chunks
            ):
                generated = self.rag_answer_generator.generate(text, rag_result)
                generation_model = generated.model
                generation_error = generated.error
                if generated.status == "generated":
                    reply = generated.answer
                    generation_mode = "rag_ai"
            return AnswerResult(
                action="auto_reply" if rag_result.is_strong else "suggested_reply",
                intent="rag.document",
                reply=reply,
                source=rag_result.source,
                confidence=rag_result.confidence,
                generation_mode=generation_mode,
                generation_model=generation_model,
                generation_error=generation_error,
            )
```

同时让 `_faq_answer` 返回 `generation_mode="faq"`，`_needs_info` 返回 `generation_mode="needs_info"`，人工兜底返回 `generation_mode="human_fallback"`。

- [ ] **步骤 4：运行测试并确认生成与降级通过**

运行：

```powershell
python -m unittest tests.test_engine -v
```

预期：全部通过，现有 FAQ、社区和未知问题行为无回归。

- [ ] **步骤 5：添加“不应调用 AI”的回归断言**

扩展现有 FAQ、社区和未知问题测试：

```python
        self.assertEqual(result.generation_mode, "faq")
        self.assertEqual(generator.calls, [])
```

社区测试断言 `generation_mode == "rag_community"`；未知问题断言 `generation_mode == "needs_info"`。对生成器使用会记录调用的假实现，确认 FAQ、社区、低置信和未知问题均不会调用生成器。

- [ ] **步骤 6：运行引擎测试并提交**

运行：

```powershell
python -m unittest tests.test_engine -v
```

预期：全部通过。

提交：

```powershell
git add -- summer_camp_agent/engine.py tests/test_engine.py
git commit -m "feat: 接入 RAG AI 生成与原文降级"
```

### 任务 3：装配真实运行时且保持测试不访问网络

**文件：**

- 修改：`summer_camp_agent/rag_runtime.py`
- 修改：`summer_camp_agent/workbench_session.py`
- 修改：`summer_camp_agent/workbench_server.py`
- 修改：`tests/test_rag_retriever.py`
- 修改：`tests/test_workbench_session.py`

- [ ] **步骤 1：先写运行时配置测试**

在 `tests/test_rag_retriever.py` 增加：

```python
from unittest.mock import patch
from summer_camp_agent.rag_runtime import load_default_rag_answer_generator


    def test_default_rag_answer_generator_uses_openai_environment(self):
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_CHAT_MODEL": "gpt-test",
                "OPENAI_BASE_URL": "https://example.test/v1",
            },
            clear=True,
        ):
            generator = load_default_rag_answer_generator()

        self.assertIsNotNone(generator)
        self.assertEqual(generator.model, "gpt-test")
        self.assertEqual(generator.base_url, "https://example.test/v1")

    def test_default_rag_answer_generator_is_optional_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(load_default_rag_answer_generator())
```

- [ ] **步骤 2：运行测试并确认导入失败**

运行：

```powershell
python -m unittest tests.test_rag_retriever -v
```

预期：失败信息提示 `load_default_rag_answer_generator` 不存在。

- [ ] **步骤 3：实现运行时加载函数**

在 `summer_camp_agent/rag_runtime.py` 增加：

```python
from .rag_ai import OpenAIRagAnswerGenerator, RagAnswerGenerator


def load_default_rag_answer_generator() -> RagAnswerGenerator | None:
    return OpenAIRagAnswerGenerator.from_env()
```

该函数不要使用 `lru_cache`，确保测试和进程内配置刷新能够读取最新环境变量。

- [ ] **步骤 4：让工作台会话支持显式注入生成器**

给 `WorkbenchSession.__init__` 增加 `rag_answer_generator=None`，并修改默认引擎创建：

```python
        self.review = review or OperatorReview(
            AnswerEngine(
                KnowledgeBase.from_default(),
                rag_retriever=load_default_rag_retriever(),
                rag_answer_generator=rag_answer_generator,
            )
        )
```

`WorkbenchSession` 自身不主动读取密钥；这保证单元测试和被嵌入调用不会意外请求外部接口。

- [ ] **步骤 5：只在真实服务器入口加载默认生成器**

把 `summer_camp_agent/workbench_server.py` 的状态创建改为：

```python
from .rag_runtime import load_default_rag_answer_generator


def create_server(port: int = 8765) -> tuple[ThreadingHTTPServer, str]:
    state = WorkbenchApiState(rag_answer_generator=load_default_rag_answer_generator())
    server = ThreadingHTTPServer(("127.0.0.1", port), create_handler(state))
    url = f"http://127.0.0.1:{server.server_address[1]}"
    return server, url
```

给 `WorkbenchApiState.__init__` 增加同名参数，并传给 `WorkbenchSession`。

- [ ] **步骤 6：写会话注入测试并确认通过**

在 `tests/test_workbench_session.py` 使用任务 2 定义的 `strong_official_rag_result` 等价测试数据，加入：

```python
    def test_session_passes_injected_generator_to_default_engine(self):
        generator = FakeRagAnswerGenerator(
            RagGenerationResult("generated", "AI 整理后的回复", "fake-model")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = OperatorReview(
                AnswerEngine(
                    KnowledgeBase.from_default(),
                    rag_retriever=FakeRagRetriever(strong_official_rag_result()),
                    rag_answer_generator=generator,
                )
            )
            session = WorkbenchSession(
                GroupConfig(group_name="咨询群", mode="auto"),
                candidate_path=root / "candidates.jsonl",
                log_path=root / "logs.jsonl",
                review=review,
            )
            item = session.process_event(make_event("rag-ai-session", "比赛镜像能下载吗？"))

        self.assertEqual(item.review_card.reply, "AI 整理后的回复")
        self.assertEqual(item.review_card.generation_mode, "rag_ai")
```

运行：

```powershell
python -m unittest tests.test_rag_retriever tests.test_workbench_session -v
```

预期：全部通过且没有真实 HTTP 请求。

- [ ] **步骤 7：提交运行时装配**

```powershell
git add -- summer_camp_agent/rag_runtime.py summer_camp_agent/workbench_session.py summer_camp_agent/workbench_server.py summer_camp_agent/workbench_api.py tests/test_rag_retriever.py tests/test_workbench_session.py
git commit -m "feat: 在微信工作台装配 RAG AI 生成器"
```

### 任务 4：记录并展示生成方式

**文件：**

- 修改：`summer_camp_agent/review.py`
- 修改：`summer_camp_agent/workbench_models.py`
- 修改：`summer_camp_agent/workbench_session.py`
- 修改：`summer_camp_agent/workbench_api.py`
- 修改：`tests/test_review.py`
- 修改：`tests/test_workbench_store.py`
- 修改：`tests/test_workbench_api.py`
- 修改：`desktop/src/shared/types.ts`
- 修改：`desktop/src/renderer/App.tsx`
- 修改：`desktop/tests/static.test.mjs`

- [ ] **步骤 1：先写审核卡与持久日志元数据测试**

在 `tests/test_review.py` 的 RAG 场景断言：

```python
        self.assertEqual(card.generation_mode, "rag_ai")
        self.assertEqual(card.generation_model, "fake-model")
```

在 `tests/test_workbench_store.py` 创建 `ReplyLogEntry` 时加入：

```python
                generation_mode="rag_ai",
                generation_model="gpt-test",
                generation_error="",
```

并断言 JSONL 中三个字段正确保存。

- [ ] **步骤 2：运行测试并确认字段不存在导致失败**

运行：

```powershell
python -m unittest tests.test_review tests.test_workbench_store -v
```

预期：失败信息指向生成元数据字段不存在。

- [ ] **步骤 3：透传元数据到审核卡和日志模型**

给 `ReviewCard` 和 `ReplyLogEntry` 增加：

```python
    generation_mode: str = ""
    generation_model: str = ""
    generation_error: str = ""
```

`OperatorReview.create_card` 从 `AnswerResult` 复制这些字段。`WorkbenchSession` 创建 `ReplyLogEntry` 时复制审核卡字段，并在 `think` 工作轨迹的 `details` 中记录：

```python
                "generation_mode": card.generation_mode,
                "generation_model": card.generation_model,
                "generation_error": card.generation_error,
```

- [ ] **步骤 4：先写 API 序列化测试**

在 `tests/test_workbench_api.py` 对 AI RAG 项目断言：

```python
        item = payload["items"][0]
        self.assertEqual(item["generation_mode"], "rag_ai")
        self.assertEqual(item["generation_model"], "fake-model")
        self.assertEqual(item["generation_error"], "")
```

- [ ] **步骤 5：实现 API 序列化并运行 Python 测试**

在 `serialize_item` 返回值加入：

```python
        "generation_mode": item.review_card.generation_mode,
        "generation_model": item.review_card.generation_model,
        "generation_error": item.review_card.generation_error,
```

运行：

```powershell
python -m unittest tests.test_review tests.test_workbench_store tests.test_workbench_api -v
```

预期：全部通过。

- [ ] **步骤 6：先写桌面端静态契约测试**

在 `desktop/tests/static.test.mjs` 增加断言，要求类型定义和详情视图包含 `generation_mode`、`generation_model`，并显示中文标签“生成方式”“生成模型”。

运行：

```powershell
npm test
```

工作目录：`desktop`

预期：新增断言失败。

- [ ] **步骤 7：实现桌面端字段与详情展示**

在 `WorkbenchItem` TypeScript 接口增加：

```typescript
  generation_mode: string
  generation_model: string
  generation_error: string
```

在 `DecisionDetails` 中增加：

```tsx
      <DetailRow label="生成方式" value={item.generation_mode || '无'} />
      <DetailRow label="生成模型" value={item.generation_model || '无'} />
      {item.generation_error && <DetailRow label="生成降级原因" value={item.generation_error} />}
```

- [ ] **步骤 8：运行桌面端验证并提交**

运行：

```powershell
npm test
npm run typecheck
```

工作目录：`desktop`

预期：两条命令均退出码 0。

提交：

```powershell
git add -- summer_camp_agent/review.py summer_camp_agent/workbench_models.py summer_camp_agent/workbench_session.py summer_camp_agent/workbench_api.py tests/test_review.py tests/test_workbench_store.py tests/test_workbench_api.py desktop/src/shared/types.ts desktop/src/renderer/App.tsx desktop/tests/static.test.mjs
git commit -m "feat: 记录并展示 RAG AI 生成方式"
```

### 任务 5：完成多场景模拟微信闭环

**文件：**

- 修改：`tests/test_full_reply_chain.py`

- [ ] **步骤 1：把模拟状态工厂改为可注入生成器**

修改测试帮助方法：

```python
    def make_state(self, root, rag_answer_generator=None):
        state = WorkbenchApiState(
            candidate_path=root / "candidates.jsonl",
            log_path=root / "logs.jsonl",
            wechat_config_path=root / "wechat_bridge_config.json",
            rag_answer_generator=rag_answer_generator,
        )
        state.configure_wechat(
            {
                "base_url": "http://127.0.0.1:5031",
                "token_env": "WEFLOW_API_TOKEN",
                "group_name": "测试群",
                "session_id": "",
                "keywords": ["测试"],
                "poll_interval_seconds": 5,
                "enabled": True,
                "show_debug_config": False,
                "send_mode": "auto_send",
            }
        )
        state.paste_adapter = SimulatedPublishAdapter()
        return state
```

增加会根据问题返回明确文本并记录调用次数的生成器：

```python
class ScenarioGenerator:
    model = "fake-model"

    def __init__(self):
        self.questions = []

    def generate(self, question, rag_result):
        self.questions.append(question)
        labels = {
            "请问能否公开下载比赛镜像？": "镜像可以按官方资料指引下载。",
            "页面选了 3.7.2.1，服务器里为什么还是 3.7.1.5？": "页面版本和服务器显示版本的差异请按官方说明处理。",
            "MACA C++、Triton 和 TileLang 是放在一个榜里比吗？": "不同语言实现按官方评测规则参与比较。",
        }
        return RagGenerationResult(
            "generated",
            answer=labels[question],
            model=self.model,
        )
```

- [ ] **步骤 2：先写三个 RAG AI 自动发送场景**

使用子测试覆盖：

```python
        cases = [
            ("请问能否公开下载比赛镜像？", "镜像下载"),
            ("页面选了 3.7.2.1，服务器里为什么还是 3.7.1.5？", "版本差异"),
            ("MACA C++、Triton 和 TileLang 是放在一个榜里比吗？", "语言评测"),
        ]
```

每个场景都断言：

```python
        self.assertEqual(item["intent"], "rag.document")
        self.assertEqual(item["generation_mode"], "rag_ai")
        self.assertEqual(item["mode"], "auto_send")
        self.assertEqual(item["status"], "已回复")
        self.assertEqual(state.paste_adapter.sent[-1][1], item["reply"])
```

- [ ] **步骤 3：运行测试并确认生成器尚未贯穿工作台时失败**

运行：

```powershell
python -m unittest tests.test_full_reply_chain.FullReplyChainSimulationTest.test_official_rag_scenarios_use_ai_and_reach_simulated_auto_publish -v
```

预期：失败原因是生成器未注入、生成方式缺失或某个自然问题未达到强匹配。

- [ ] **步骤 4：只修复检索表达覆盖，不降低全局安全阈值**

如果版本差异或语言评测自然问法未命中，优先在 `data/rag` 文档标题已有表述基础上调整测试问题或局部归一化；不得降低 `DEFAULT_STRONG_SIMILARITY`，不得把社区内容提升为强匹配。每次调整后运行 `tests.test_rag_retriever` 与当前闭环测试。

- [ ] **步骤 5：添加 FAQ、社区和未知问题隔离场景**

增加测试并断言：

- “报名入口在哪里？”命中 FAQ，`generation_mode == "faq"`，生成器调用数不增加。
- “CMake 构建失败怎么办？”为 `rag_community`，模式不是 `auto_send`，模拟发送器没有新增发送。
- “营服是什么颜色？”为 `needs_info`，模式不是 `auto_send`，生成器调用数不增加。

- [ ] **步骤 6：添加 AI 超时和无依据链接降级场景**

分别注入返回以下结果的假生成器：

```python
RagGenerationResult("unavailable", model="fake-model", error="timeout")
RagGenerationResult("invalid", model="fake-model", error="unsupported_url")
```

对两个场景断言最终仍为 `auto_send`，`generation_mode == "rag_fallback"`，回复等于官方 RAG 原文，且错误类型正确记录。

- [ ] **步骤 7：运行完整模拟闭环并提交**

运行：

```powershell
python -m unittest tests.test_full_reply_chain -v
```

预期：FAQ、三种 AI RAG、社区阻断、未知问题和两种降级场景全部通过。

提交：

```powershell
git add -- tests/test_full_reply_chain.py summer_camp_agent/rag_retriever.py tests/test_rag_retriever.py
git commit -m "test: 验证微信 RAG AI 自动回复闭环"
```

### 任务 6：增加真实 OpenAI 联调脚本并执行验证

**文件：**

- 新建：`scripts/verify_rag_ai_reply.py`
- 修改：`docs/technical-architecture.md`

- [ ] **步骤 1：实现只使用模拟微信发送器的真实 AI 联调脚本**

脚本必须：

- 检查 `OPENAI_API_KEY`，缺失时以非零退出码和中文提示退出。
- 使用 `load_default_rag_retriever()` 和 `load_default_rag_answer_generator()`。
- 构造三个公开测试问题。
- 对每个问题运行真实问答引擎、检查 `generation_mode == "rag_ai"`、检查回复非空且不超过 600 字。
- 使用模拟发送器保存最终回复，不调用 `WindowsPasteBackend`、WeFlow 或真实微信窗口。
- 输出每个场景的意图、生成模型、来源与最终回复，不输出密钥和 Authorization 头。

脚本使用完整工作台状态、模拟监听器和模拟发送器，核心结构如下：

```python
import tempfile
from pathlib import Path

from summer_camp_agent.rag_runtime import load_default_rag_answer_generator
from summer_camp_agent.wechat_assisted_paste import PasteResult
from summer_camp_agent.wechat_live_listener import ListenerPollResult
from summer_camp_agent.workbench_api import WorkbenchApiState
from summer_camp_agent.workbench_models import ChatEvent


QUESTIONS = [
    "请问能否公开下载比赛镜像？",
    "页面选了 3.7.2.1，服务器里为什么还是 3.7.1.5？",
    "MACA C++、Triton 和 TileLang 是放在一个榜里比吗？",
]


class SimulatedListener:
    def __init__(self, events):
        self.events = events

    def poll_once(self, *, include_seen=False):
        events, self.events = self.events, []
        return ListenerPollResult("ok", "真实 AI 联调消息已载入", events)


class SimulatedPublishAdapter:
    def __init__(self):
        self.sent = []

    def send_to_wechat_foreground(self, text, target_group_name=""):
        self.sent.append((target_group_name, text))
        return PasteResult(
            "sent_verified",
            "模拟自动发送成功。",
            "测试群 - 微信",
            target_found=True,
            input_focused=True,
            filled=True,
            verified=True,
            target_status="matched",
            input_status="focused",
            verification_status="matched",
        )


def make_event(index: int, question: str) -> ChatEvent:
    return ChatEvent(
        event_id=f"live-rag-ai-{index}",
        group_id_hash="sha256:live-rag-ai-group",
        group_name="测试群",
        sender_alias=f"模拟成员{index:03d}",
        sender_role="student",
        message_time="2026-07-23 12:00:00",
        content=question,
        raw_type="text",
        source="live_rag_ai_simulation",
    )


def main() -> int:
    generator = load_default_rag_answer_generator()
    if generator is None:
        print("缺少 OPENAI_API_KEY，无法执行真实 AI 联调。")
        return 2
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = WorkbenchApiState(
            candidate_path=root / "candidates.jsonl",
            log_path=root / "logs.jsonl",
            wechat_config_path=root / "wechat.json",
            rag_answer_generator=generator,
        )
        state.configure_wechat(
            {
                "group_name": "测试群",
                "keywords": ["测试"],
                "enabled": True,
                "send_mode": "auto_send",
            }
        )
        state.wechat_listener = SimulatedListener(
            [make_event(index, question) for index, question in enumerate(QUESTIONS, 1)]
        )
        state.paste_adapter = SimulatedPublishAdapter()
        payload = state.poll_wechat_once()
        for question, item in zip(QUESTIONS, payload["items"], strict=True):
            if item["generation_mode"] != "rag_ai" or item["status"] != "已回复":
                print(
                    f"验证失败：{question} -> {item['generation_mode']} / "
                    f"{item['generation_error']} / {item['status']}"
                )
                return 1
            if not item["reply"].strip() or len(item["reply"]) > 600:
                print(f"验证失败：{question} -> 回复为空或过长")
                return 1
            print(
                f"问题：{question}\n模型：{item['generation_model']}\n"
                f"来源：{item['answer_source']}\n回复：{item['reply']}\n"
            )
        if len(state.paste_adapter.sent) != len(QUESTIONS):
            print("验证失败：模拟发送数量与场景数量不一致。")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **步骤 2：在技术架构文档记录配置与降级边界**

在 `docs/technical-architecture.md` 增加中文小节，明确：

```text
OPENAI_API_KEY：真实 AI 生成所需密钥。
OPENAI_CHAT_MODEL：可选，默认 gpt-5.6-luna。
OPENAI_BASE_URL：可选，默认 https://api.openai.com/v1。
AI 只处理高置信官方 RAG；失败后发送官方原文；社区和未知问题不自动发送。
```

- [ ] **步骤 3：运行真实 OpenAI 三场景联调**

运行：

```powershell
python scripts/verify_rag_ai_reply.py
```

预期：三个场景均显示 `gpt-5.6-luna` 或环境变量指定模型，脚本退出码 0；输出不包含 API Key。

- [ ] **步骤 4：检查工作区中不存在密钥泄漏**

运行：

```powershell
rg -n "Bearer [A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}" summer_camp_agent tests scripts docs data desktop
```

预期：无匹配。测试中的字面量 `test-key` 不属于密钥格式。

- [ ] **步骤 5：提交联调脚本和文档**

```powershell
git add -- scripts/verify_rag_ai_reply.py docs/technical-architecture.md
git commit -m "test: 增加 RAG AI 真实接口联调"
```

### 任务 7：执行全量回归和最终审查

**文件：**

- 检查：本计划涉及的全部文件

- [ ] **步骤 1：运行 Python 全量测试**

运行：

```powershell
python -m unittest discover -s tests -v
```

预期：全部通过，0 个失败、0 个错误；测试过程不得访问真实 OpenAI 接口。

- [ ] **步骤 2：运行桌面端测试、类型检查与构建**

运行：

```powershell
npm test
npm run typecheck
npm run build
```

工作目录：`desktop`

预期：三条命令全部退出码 0。

- [ ] **步骤 3：重新运行真实 OpenAI 联调**

运行：

```powershell
python scripts/verify_rag_ai_reply.py
```

预期：三个 RAG 场景均完成真实 AI 生成并记录到模拟发送器，退出码 0。

- [ ] **步骤 4：检查差异、格式和用户已有改动**

运行：

```powershell
git status --short
git diff --check
git diff --stat
```

预期：没有空白错误；只包含计划内改动和用户原有未提交改动，不覆盖或回退用户文件。

- [ ] **步骤 5：逐项核对验收标准**

核对：

- FAQ 未命中且官方 RAG 强命中会使用 AI。
- AI 失败会降级官方原文并继续自动发送。
- FAQ 不调用 AI。
- 社区、未知问题和人工兜底不自动发送。
- 三个不同主题完成真实 AI 与模拟微信发送闭环。
- API、日志和桌面详情能够区分 `faq`、`rag_ai`、`rag_fallback`、`rag_community`、`needs_info`。

- [ ] **步骤 6：提交最终必要修正**

仅在全量验证发现并修复问题时执行：

先用 `git diff --name-only` 确认修复范围，再仅暂存计划内且本轮确实修改过的文件。例如修复发生在生成器和对应测试时运行：

```powershell
git add -- summer_camp_agent/rag_ai.py tests/test_rag_ai.py
git diff --cached --check
git commit -m "fix: 修正 RAG AI 自动回复回归问题"
```

不得使用 `git add .`，避免误提交用户原有工作区改动。
