import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from summer_camp_agent.weflow_import import (
    WeFlowAuthError,
    WeFlowImportClient,
    WeFlowImportConfig,
    WeFlowImportError,
    WeFlowSessionSelectionRequired,
    import_weflow_chat,
    resolve_weflow_token,
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


class FakeUrlOpen:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)


class WeFlowImportTest(unittest.TestCase):
    def test_resolve_weflow_token_prefers_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "WeFlow-config.json"
            config_path.write_text(json.dumps({"httpApiToken": "config-token"}), encoding="utf-8")

            with patch.dict("os.environ", {"WEFLOW_API_TOKEN": "env-token"}, clear=False):
                token = resolve_weflow_token(config_path=config_path)

        self.assertEqual(token, "env-token")

    def test_resolve_weflow_token_falls_back_to_weflow_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "WeFlow-config.json"
            config_path.write_text(
                json.dumps({"httpApiToken": "config-token", "keep": "value"}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {}, clear=True):
                token = resolve_weflow_token(config_path=config_path)

        self.assertEqual(token, "config-token")

    def test_resolve_weflow_token_reports_actionable_missing_token(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "WeFlow-config.json"
            config_path.write_text(json.dumps({"httpApiToken": ""}), encoding="utf-8")

            with patch.dict("os.environ", {}, clear=True), self.assertRaisesRegex(WeFlowAuthError, "WeFlow 配置"):
                resolve_weflow_token(config_path=config_path)

    def test_rejects_remote_base_url(self):
        with self.assertRaisesRegex(WeFlowImportError, "只允许连接本机"):
            WeFlowImportClient("https://example.com", "token")

    def test_search_sessions_uses_bearer_token(self):
        opener = FakeUrlOpen([{"sessions": [{"id": "room@chatroom", "name": "测试群", "type": "group"}]}])
        client = WeFlowImportClient("http://127.0.0.1:5031", "secret-token", urlopen=opener)

        sessions = client.search_sessions("测试")

        self.assertEqual(sessions[0].id, "room@chatroom")
        self.assertEqual(opener.requests[0].headers["Authorization"], "Bearer secret-token")

    def test_search_sessions_filters_unrelated_groups_when_api_ignores_keyword(self):
        opener = FakeUrlOpen(
            [
                {
                    "sessions": [
                        {"id": "a@chatroom", "name": "无关群", "type": "group"},
                        {"id": "b@chatroom", "name": "沐曦开源英才夏令营咨询群", "type": "group"},
                        {"id": "channel", "name": "沐曦通知", "type": "channel"},
                    ]
                }
            ]
        )
        client = WeFlowImportClient("http://127.0.0.1:5031", "token", urlopen=opener)

        sessions = client.search_sessions("沐曦")

        self.assertEqual([session.id for session in sessions], ["b@chatroom"])

    def test_import_writes_sanitized_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            opener = FakeUrlOpen(
                [
                    {"sessions": [{"id": "room@chatroom", "name": "测试群", "type": "group"}]},
                    {
                        "meta": {"name": "测试群", "groupId": "room@chatroom"},
                        "messages": [
                            {
                                "sender": "wxid_a",
                                "timestamp": 1781911260,
                                "type": 0,
                                "content": "报名入口在哪里？手机号 13800138000",
                                "platformMessageId": "msg1",
                            },
                            {
                                "sender": "wxid_b",
                                "timestamp": 1781911320,
                                "type": 0,
                                "content": "午饭吃什么？",
                                "platformMessageId": "msg2",
                            },
                        ],
                        "sync": {"hasMore": False},
                    },
                ]
            )
            client = WeFlowImportClient("http://127.0.0.1:5031", "token", urlopen=opener)
            config = WeFlowImportConfig(
                group_name="测试群",
                keywords=["报名"],
                start="20260601",
                end="20260630",
                output_dir=Path(directory),
            )

            summary = import_weflow_chat(config, client=client, token="token")
            lines = summary.output_path.read_text(encoding="utf-8").splitlines()
            row = json.loads(lines[0])

            self.assertEqual(summary.written_count, 1)
            self.assertEqual(row["sender_alias"], "成员001")
            self.assertIn("[手机号]", row["content"])
            self.assertNotIn("wxid_a", json.dumps(row, ensure_ascii=False))

    def test_multiple_sessions_require_selection(self):
        opener = FakeUrlOpen(
            [
                {
                    "sessions": [
                        {"id": "a@chatroom", "name": "测试群 A", "type": "group"},
                        {"id": "b@chatroom", "name": "测试群 B", "type": "group"},
                    ]
                }
            ]
        )
        client = WeFlowImportClient("http://127.0.0.1:5031", "token", urlopen=opener)

        with self.assertRaises(WeFlowSessionSelectionRequired) as ctx:
            import_weflow_chat(WeFlowImportConfig(group_name="测试群", keywords=[]), client=client, token="token")

        self.assertEqual(len(ctx.exception.sessions), 2)

    def test_auth_error_is_reported_without_token(self):
        response = BytesIO(b'{"error":"unauthorized"}')
        error = HTTPError("http://127.0.0.1", 401, "Unauthorized", {}, response)
        client = WeFlowImportClient("http://127.0.0.1:5031", "token", urlopen=FakeUrlOpen([error]))

        with self.assertRaises(WeFlowAuthError):
            client.search_sessions("测试")

    def test_connection_error_is_reported(self):
        client = WeFlowImportClient("http://127.0.0.1:5031", "token", urlopen=FakeUrlOpen([URLError("refused")]))

        with self.assertRaisesRegex(WeFlowImportError, "无法连接"):
            client.search_sessions("测试")

    def test_http_500_includes_weflow_error_body_and_cursor_hint(self):
        response = BytesIO(json.dumps({"error": "创建游标失败: -3，请查看日志"}).encode("utf-8"))
        server_error = HTTPError("http://127.0.0.1", 500, "Internal Server Error", {}, response)
        client = WeFlowImportClient("http://127.0.0.1:5031", "token", urlopen=FakeUrlOpen([server_error]))

        with self.assertRaisesRegex(WeFlowImportError, "消息数据库"):
            client.search_sessions("测试")

    def test_pull_messages_falls_back_to_legacy_messages_endpoint(self):
        response = BytesIO(b'{"error":"not found"}')
        not_found = HTTPError("http://127.0.0.1", 404, "Not Found", {}, response)
        opener = FakeUrlOpen(
            [
                not_found,
                {
                    "meta": {"name": "测试群", "groupId": "room@chatroom"},
                    "messages": [],
                    "sync": {"hasMore": False},
                },
            ]
        )
        client = WeFlowImportClient("http://127.0.0.1:5031", "token", urlopen=opener)

        payload = client.pull_messages("room@chatroom", since=1781911260, end=1781997660, limit=5000, offset=0)

        self.assertEqual(payload["messages"], [])
        self.assertIn("/api/v1/messages", opener.requests[1].full_url)
        self.assertIn("talker=room%40chatroom", opener.requests[1].full_url)


if __name__ == "__main__":
    unittest.main()
