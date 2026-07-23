import unittest
from unittest.mock import patch

from summer_camp_agent.workbench_server import create_server


class WorkbenchServerTest(unittest.TestCase):
    def test_create_server_loads_default_rag_answer_generator(self):
        generator = object()
        with patch(
            "summer_camp_agent.workbench_server.load_default_rag_answer_generator",
            return_value=generator,
        ), patch(
            "summer_camp_agent.workbench_server.WorkbenchApiState",
        ) as state_type:
            server, _ = create_server(port=0)
        try:
            state_type.assert_called_once_with(rag_answer_generator=generator)
        finally:
            server.server_close()

    def test_create_server_uses_localhost_and_requested_port(self):
        server, url = create_server(port=0)
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            self.assertTrue(url.startswith("http://127.0.0.1:"))
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
