import tempfile
import unittest
from datetime import date
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from summer_camp_agent.activity import init_activity, list_activities, load_activity
from summer_camp_agent.cli import main
from summer_camp_agent.demo import run_demo
from summer_camp_agent.engine import AnswerEngine
from summer_camp_agent.knowledge import KnowledgeBase


class ActivityProfileTest(unittest.TestCase):
    def test_builtin_profiles_cover_online_offline_and_hybrid(self):
        profiles = {profile.id: profile for profile in list_activities()}

        self.assertEqual(profiles["online-workshop"].formats, ("online",))
        self.assertEqual(profiles["offline-meetup"].formats, ("offline",))
        self.assertEqual(profiles["hybrid-summit"].formats, ("online", "offline"))
        self.assertEqual(profiles["summer-camp"].formats, ("online", "offline"))
        self.assertIn("咨询群值班同学", profiles["summer-camp"].serves)
        self.assertIn("现场签到志愿者", profiles["offline-meetup"].serves)

    def test_activity_packs_do_not_share_answers(self):
        online = load_activity("online-workshop")
        offline = load_activity("offline-meetup")
        online_reply = AnswerEngine(
            KnowledgeBase.from_json(online.knowledge_path),
            organizer=online.organizer,
            notice_channel=online.notice_channel,
        ).answer("有线下会场吗？")
        offline_reply = AnswerEngine(
            KnowledgeBase.from_json(offline.knowledge_path),
            organizer=offline.organizer,
            notice_channel=offline.notice_channel,
        ).answer("有直播链接吗？")

        self.assertEqual(online_reply.intent, "format.online_only")
        self.assertIn("不设置线下会场", online_reply.reply)
        self.assertEqual(offline_reply.intent, "format.offline_only")
        self.assertIn("不提供线上直播", offline_reply.reply)
        self.assertNotIn("metax-tech.com", online_reply.reply)

    def test_expired_camp_fact_still_answers_on_the_message_date(self):
        engine = AnswerEngine(KnowledgeBase.from_default(), today=date(2026, 10, 27))

        current = engine.answer("线下夏令营在哪里举办？")
        historical = engine.answer("线下夏令营在哪里举办？", on_date=date(2026, 7, 29))

        self.assertEqual(current.action, "needs_info")
        self.assertEqual(historical.action, "auto_reply")
        self.assertEqual(historical.intent, "offline.location")

    def test_demo_command_passes_for_every_activity_format(self):
        rows = run_demo()

        self.assertGreaterEqual(len(rows), 8)
        self.assertTrue(all(row.ok for row in rows))
        covered = {fmt for row in rows for fmt in row.formats}
        self.assertEqual(covered, {"online", "offline"})

    def test_cli_lists_and_answers_selected_activity(self):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["activities"])
        self.assertEqual(exit_code, 0)
        self.assertIn("online-workshop", output.getvalue())
        self.assertIn("线下活动组织者", output.getvalue())
        self.assertIn("活动值守", output.getvalue())
        self.assertIn("offline-meetup", output.getvalue())
        self.assertIn("hybrid-summit", output.getvalue())

        ask_output = StringIO()
        with redirect_stdout(ask_output):
            ask_code = main(["ask", "--activity", "offline-meetup", "活动地点在哪里？"])
        self.assertEqual(ask_code, 0)
        self.assertIn("action: auto_reply", ask_output.getvalue())
        self.assertIn("intent: venue.address", ask_output.getvalue())
        self.assertIn("model: 未调用", ask_output.getvalue())
        self.assertIn("示例路 1 号", ask_output.getvalue())

    def test_unknown_activity_is_rejected(self):
        exit_code = main(["ask", "--activity", "missing-event", "你好"])
        self.assertEqual(exit_code, 2)

    def test_init_activity_creates_a_pack_for_new_contributors(self):
        with tempfile.TemporaryDirectory() as directory:
            target = init_activity(
                "city-reading",
                "城市阅读会",
                ["offline"],
                ["读书会组织者", "现场志愿者"],
                root=Path(directory),
            )
            profile = json_load(target / "activity.json")
            faq = json_load(target / "faq.json")
            knowledge = KnowledgeBase.from_json(target / "faq.json")

            self.assertEqual(profile["serves"], ["读书会组织者", "现场志愿者"])
            self.assertEqual(profile["formats"], ["offline"])
            self.assertGreaterEqual(len(faq), 2)
            reply = AnswerEngine(knowledge).answer("这场活动是做什么的？")
            self.assertEqual(reply.action, "auto_reply")
            self.assertIn("城市阅读会", reply.reply)

            with self.assertRaises(Exception):
                init_activity(
                    "city-reading",
                    "城市阅读会",
                    ["offline"],
                    ["读书会组织者"],
                    root=Path(directory),
                )

    def test_check_reports_who_each_pack_serves(self):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["check"])
        text = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("活动值守 Activity Desk", text)
        self.assertIn("咨询群值班同学", text)
        self.assertIn("init-activity", text)

    def test_models_command_states_faq_and_optional_models(self):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["models"])
        text = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("不调用大模型", text)
        self.assertIn("deepseek-v4-pro", text)
        self.assertIn("text-embedding-3-small", text)
        self.assertIn("https://api.deepseek.com", text)
        self.assertNotIn("sk-", text)


def json_load(path: Path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
