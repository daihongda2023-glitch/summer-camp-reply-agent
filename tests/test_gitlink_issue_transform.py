import unittest

from summer_camp_agent.gitlink_issue_transform import (
    GitLinkSource,
    extract_generated_qas,
    render_generated_qa,
    sanitize_answer,
    should_exclude_issue,
)


class GitLinkIssueTransformTest(unittest.TestCase):
    def test_sanitize_answer_removes_all_supported_image_placeholders(self):
        answer = "有效回答\n![[截屏.png]]\n![截图](https://example.com/a.png)\n<img src=\"a.png\">"

        self.assertEqual(sanitize_answer(answer), "有效回答")

    def test_skips_trusted_author_question_and_tentative_update(self):
        issue = {
            "project_issues_index": 6,
            "subject": "镜像版本需要确认",
            "description": "",
            "updated_at": "2026-06-18 15:41",
            "tags": [],
        }
        comments = [
            {
                "user": {"login": "topshare"},
                "notes": "TileLang 使用固定版本还是最新源码？这个需要确定一下。",
            },
            {
                "user": {"login": "yyyymmm"},
                "notes": "应该需要更新为新镜像，近几天会更新最新指南。",
            },
        ]

        self.assertEqual(extract_generated_qas(issue, comments, self.source), [])

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

    def test_splits_official_faq_table_into_independent_questions(self):
        issue = {
            "project_issues_index": 4,
            "subject": "FAQ（更新至 7.13）",
            "description": (
                "| 问题 | 类型 | 回答 |\n"
                "| --- | --- | --- |\n"
                "| 是否可以同时参加两个赛题？ | 赛题类 | 可以。 |\n"
                "| 最终评测是整卡吗？ | 赛题类 | 使用沐曦 C500 64G GPU 整卡评测。 |"
            ),
            "updated_at": "2026-07-13 15:56",
            "author": {"login": "yyyymmm"},
            "tags": [],
        }

        qas = extract_generated_qas(issue, [], self.source)

        self.assertEqual(len(qas), 2)
        self.assertEqual(qas[0].question, "是否可以同时参加两个赛题？")
        self.assertEqual(qas[0].filename, "issue-4-faq-01.md")
        self.assertEqual(qas[1].answer, "使用沐曦 C500 64G GPU 整卡评测。")
        self.assertTrue(all(qa.trust_level == "official" for qa in qas))

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
            "notes": (
                "## 遇到的 cmake 构建问题（已解决）\n"
                "用户名：student\n"
                "![](/api/attachments/a.png)\n"
                "执行 `pip install cmake` 后构建通过。"
            ),
        }]

        qas = extract_generated_qas(issue, comments, self.source)

        self.assertEqual(len(qas), 1)
        self.assertEqual(qas[0].trust_level, "community")
        self.assertEqual(qas[0].question, "遇到的 cmake 构建问题（已解决）")
        self.assertNotIn("用户名", qas[0].answer)
        self.assertNotIn("attachments", qas[0].answer)
        self.assertIn("pip install cmake", qas[0].answer)

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
