import json
import io
import unittest
import urllib.error
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
        embedding=[],
        metadata={
            "trust_level": "official",
            "source_url": "https://www.gitlink.org.cn/example/issues/19",
        },
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
                                        {
                                            "answer": "可以在开发者社区下载比赛镜像。",
                                            "grounded": True,
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ],
                        }
                    ]
                }
            )

        generator = OpenAIRagAnswerGenerator(
            api_key="test-key",
            model="gpt-test",
            timeout_seconds=7,
        )
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

    def test_rejects_ungrounded_answer(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {"answer": "猜测回复", "grounded": False},
                                ensure_ascii=False,
                            ),
                        }
                    ],
                }
            ]
        }

        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(response)):
            result = generator.generate("问题", official_result())

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.error, "not_grounded")

    def test_rejects_url_not_present_in_evidence(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "answer": "请访问 https://invalid.example.com",
                                    "grounded": True,
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ],
                }
            ]
        }

        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(response)):
            result = generator.generate("问题", official_result())

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.error, "unsupported_url")

    def test_rejects_reply_longer_than_limit(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {"answer": "答" * 601, "grounded": True},
                                ensure_ascii=False,
                            ),
                        }
                    ],
                }
            ]
        }

        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(response)):
            result = generator.generate("问题", official_result())

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.error, "answer_too_long")

    def test_rejects_empty_answer_and_json_wrapper(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")
        cases = [
            ("", "empty_answer"),
            ('{"answer":"仍包在 JSON 中"}', "invalid_wrapper"),
            ("```json\n{}\n```", "invalid_wrapper"),
        ]
        for answer, expected_error in cases:
            with self.subTest(answer=answer):
                response = {
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {"answer": answer, "grounded": True},
                                        ensure_ascii=False,
                                    ),
                                }
                            ],
                        }
                    ]
                }
                with patch(
                    "urllib.request.urlopen",
                    return_value=FakeHttpResponse(response),
                ):
                    result = generator.generate("问题", official_result())

                self.assertEqual(result.status, "invalid")
                self.assertEqual(result.error, expected_error)

    def test_maps_timeout_to_unavailable(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")

        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            result = generator.generate("问题", official_result())

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.error, "timeout")

    def test_maps_http_error_to_unavailable_without_leaking_response(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")
        error = urllib.error.HTTPError(
            "https://api.openai.com/v1/responses",
            429,
            "rate limited",
            {},
            None,
        )

        with patch("urllib.request.urlopen", side_effect=error):
            result = generator.generate("问题", official_result())

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.error, "http_429")

    def test_maps_insufficient_quota_to_specific_safe_error(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")
        response = io.BytesIO(
            json.dumps(
                {
                    "error": {
                        "type": "insufficient_quota",
                        "code": "insufficient_quota",
                        "message": "sensitive provider detail",
                    }
                }
            ).encode("utf-8")
        )
        error = urllib.error.HTTPError(
            "https://api.openai.com/v1/responses",
            429,
            "quota exceeded",
            {},
            response,
        )

        with patch("urllib.request.urlopen", side_effect=error):
            result = generator.generate("问题", official_result())

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.error, "insufficient_quota")
        self.assertNotIn("sensitive", result.error)

    def test_maps_network_error_to_unavailable(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            result = generator.generate("问题", official_result())

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.error, "network_error")

    def test_maps_invalid_response_to_invalid_result(self):
        generator = OpenAIRagAnswerGenerator(api_key="test-key")

        with patch(
            "urllib.request.urlopen",
            return_value=FakeHttpResponse({"output": []}),
        ):
            result = generator.generate("问题", official_result())

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.error, "invalid_response")

    def test_from_env_returns_none_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(OpenAIRagAnswerGenerator.from_env())


if __name__ == "__main__":
    unittest.main()
