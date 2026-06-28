import json
import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.work_trace import WorkTraceRecorder, WorkTraceStep


class WorkTraceRecorderTest(unittest.TestCase):
    def test_records_structured_steps_as_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "work_trace.jsonl"
            recorder = WorkTraceRecorder(path)

            recorder.record(
                WorkTraceStep(
                    event_id="evt-1",
                    group_name="夏令营咨询群",
                    phase="think",
                    summary="生成回复建议",
                    actor="agent",
                    action="draft_reply",
                    outcome="ok",
                    reasoning="FAQ 命中报名入口",
                    details={"confidence": 0.96},
                )
            )

            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(rows[0]["event_id"], "evt-1")
        self.assertEqual(rows[0]["phase"], "think")
        self.assertEqual(rows[0]["action"], "draft_reply")
        self.assertEqual(rows[0]["details"], {"confidence": 0.96})
        self.assertIn("trace_id", rows[0])
        self.assertIn("created_at", rows[0])


if __name__ == "__main__":
    unittest.main()
