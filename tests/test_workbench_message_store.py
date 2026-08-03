import tempfile
import unittest
from pathlib import Path

from summer_camp_agent.review import ReviewCard
from summer_camp_agent.workbench_message_store import WorkbenchMessageStore
from summer_camp_agent.workbench_models import (
    ChatEvent,
    ReplyDecision,
    TriggerDecision,
)
from summer_camp_agent.workbench_session import WorkbenchItem


def workbench_item(event_id: str, content: str) -> WorkbenchItem:
    return WorkbenchItem(
        event=ChatEvent(
            event_id=event_id,
            group_id_hash="sha256:group",
            group_name="测试群",
            sender_alias="成员001",
            sender_role="student",
            message_time="2026-07-25 10:00:00",
            content=content,
            raw_type="text",
            source="test",
        ),
        trigger=TriggerDecision(
            should_process=False,
            reasons=[],
            matched_keywords=[],
        ),
        review_card=ReviewCard(
            original_question=content,
            recommendation="mark_pending",
            available_actions=["send", "edit", "escalate", "mark_pending"],
            action="needs_info",
            reply="当前资料暂无明确说明。",
            reason="unknown",
            confidence=0.25,
            semantic_confidence=0.72,
            faq_confidence=0.25,
            rag_confidence=0.10,
        ),
        reply_decision=ReplyDecision(
            mode="draft",
            reply="当前资料暂无明确说明。",
            confidence=0.25,
            reason="unknown",
            requires_review=True,
        ),
    )


class WorkbenchMessageStoreTest(unittest.TestCase):
    def test_message_store_upserts_by_event_id_and_restores_snapshot(self):
        item = workbench_item("evt-1", "普通消息")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "messages.db"
            store = WorkbenchMessageStore(path)
            first = store.insert_pending(
                item,
                match_status="unmatched",
                unmatched_reasons=[
                    "missing_question_mark",
                    "missing_keyword",
                    "missing_agent_mention",
                ],
            )
            second = store.insert_pending(
                item,
                match_status="unmatched",
                unmatched_reasons=["missing_question_mark"],
            )
            restored = WorkbenchMessageStore(path).get("evt-1")

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.message_id, "evt-1")
        self.assertEqual(restored.item.event.content, "普通消息")
        self.assertEqual(restored.item.review_card.semantic_confidence, 0.72)
        self.assertEqual(restored.review_status, "pending_review")
        self.assertEqual(restored.match_status, "unmatched")
        self.assertEqual(
            restored.unmatched_reasons,
            [
                "missing_question_mark",
                "missing_keyword",
                "missing_agent_mention",
            ],
        )

    def test_completed_message_is_updated_in_place_and_not_reset_by_duplicate_insert(self):
        item = workbench_item("evt-1", "普通消息")
        with tempfile.TemporaryDirectory() as directory:
            store = WorkbenchMessageStore(Path(directory) / "messages.db")
            store.insert_pending(item, match_status="matched", unmatched_reasons=[])
            updated = store.complete(
                "evt-1",
                review_status="sent",
                review_action="confirm_sent",
                review_note="运营确认已发送",
            )
            store.insert_pending(item, match_status="matched", unmatched_reasons=[])
            rows = store.list_all()

        self.assertEqual(len(rows), 1)
        self.assertEqual(updated.review_status, "sent")
        self.assertEqual(rows[0].review_status, "sent")
        self.assertEqual(rows[0].review_action, "confirm_sent")
        self.assertTrue(rows[0].completed_at)

    def test_store_filters_pending_and_completed_history(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkbenchMessageStore(Path(directory) / "messages.db")
            store.insert_pending(
                workbench_item("evt-pending", "待审核"),
                match_status="matched",
                unmatched_reasons=[],
            )
            store.insert_pending(
                workbench_item("evt-sent", "已发送"),
                match_status="matched",
                unmatched_reasons=[],
            )
            store.complete("evt-sent", "sent", "confirm_sent", "")

            pending = store.list_pending()
            sent = store.list_all(review_status="sent")

        self.assertEqual([row.message_id for row in pending], ["evt-pending"])
        self.assertEqual([row.message_id for row in sent], ["evt-sent"])

    def test_message_store_rejects_invalid_values_and_round_trips_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkbenchMessageStore(Path(directory) / "messages.db")
            with self.assertRaisesRegex(ValueError, "event_id"):
                store.insert_pending(
                    workbench_item("", "消息"),
                    match_status="matched",
                    unmatched_reasons=[],
                )
            with self.assertRaisesRegex(ValueError, "match_status"):
                store.insert_pending(
                    workbench_item("evt-1", "消息"),
                    match_status="maybe",
                    unmatched_reasons=[],
                )
            store.insert_pending(
                workbench_item("evt-1", "消息"),
                match_status="matched",
                unmatched_reasons=[],
            )
            with self.assertRaisesRegex(ValueError, "review_status"):
                store.complete("evt-1", "deleted", "delete", "")

            store.set_metadata("legacy_inbox_migrated", "true")

            self.assertEqual(
                store.get_metadata("legacy_inbox_migrated"),
                "true",
            )


if __name__ == "__main__":
    unittest.main()
