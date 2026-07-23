import unittest
from datetime import date

from summer_camp_agent.engine import AnswerEngine, AnswerResult
from summer_camp_agent.answer_providers import ProviderAnswer
from summer_camp_agent.knowledge import KnowledgeBase
from summer_camp_agent.rag_ai import RagGenerationResult
from summer_camp_agent.rag_index import IndexedChunk
from summer_camp_agent.rag_retriever import RagSearchResult, ScoredChunk
from summer_camp_agent.semantic_router import SemanticAnalysisResult


class FakeRagRetriever:
    def __init__(self, result):
        self.result = result
        self.questions = []

    def retrieve(self, question):
        self.questions.append(question)
        return self.result


class SemanticFakeRagRetriever(FakeRagRetriever):
    def __init__(self, result):
        super().__init__(None)
        self.semantic_result = result
        self.chunks = [item.chunk for item in result.chunks]
        self.semantic_calls = []

    def retrieve_semantic(self, question, candidate_ids, semantic_confidence):
        self.semantic_calls.append((question, candidate_ids, semantic_confidence))
        return self.semantic_result


class FakeSemanticAnalyzer:
    model = "semantic-model"

    def __init__(self, result):
        self.result = result
        self.calls = []

    def analyze(self, question, catalog):
        self.calls.append((question, catalog))
        return self.result


class FakeRagAnswerGenerator:
    model = "fake-model"

    def __init__(self, result):
        self.result = result
        self.calls = []

    def generate(self, question, rag_result):
        self.calls.append((question, rag_result))
        return self.result


class CustomProvider:
    name = "custom"

    def answer(self, question):
        return ProviderAnswer.hit(
            AnswerResult(
                action="suggested_reply",
                reply=f"自定义回复：{question}",
                intent="custom.intent",
                source="custom-provider",
                confidence=0.88,
            )
        )


def make_engine(today=date(2026, 6, 20), rag_retriever=None):
    kb = KnowledgeBase.from_default()
    return AnswerEngine(kb, today=today, rag_retriever=rag_retriever)


def strong_official_rag_result():
    chunk = IndexedChunk(
        chunk_id="chunk-1",
        source_path="issue-19.md",
        source_title="比赛镜像",
        source_sha256="sha256:test",
        heading="比赛镜像",
        text="比赛镜像\n可以从开发者社区下载。",
        embedding=[],
        metadata={
            "trust_level": "official",
            "source_url": "https://www.gitlink.org.cn/example/issues/19",
        },
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


def analyzed(**overrides):
    values = {
        "status": "analyzed",
        "canonical_question": "标准问题",
        "intent": "unknown",
        "faq_candidate_ids": [],
        "rag_candidate_ids": [],
        "rag_queries": [],
        "semantic_confidence": 0.94,
        "requires_human": False,
        "reason": "语义匹配",
        "model": "semantic-model",
    }
    values.update(overrides)
    return SemanticAnalysisResult(**values)


class AnswerEngineTest(unittest.TestCase):
    def test_answers_registration_link_from_latest_official_poster_before_deadline(self):
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

    def test_returns_miss_for_unknown_question_without_claiming_recorded(self):
        result = make_engine().answer("营服是什么颜色？")

        self.assertEqual(result.action, "needs_info")
        self.assertEqual(result.generation_mode, "needs_info")
        self.assertIn("当前资料还没有明确说明", result.reply)
        self.assertNotIn("已记录", result.reply)

    def test_escalates_personal_selection_result(self):
        result = make_engine().answer("老师，我被录取了吗？能帮我查下面试结果吗？")

        self.assertEqual(result.action, "human_fallback")
        self.assertEqual(result.reason, "personal_status")
        self.assertEqual(result.generation_mode, "human_fallback")
        self.assertIn("个人报名状态、录取结果或面试结果", result.reply)

    def test_escalates_assignment_answer_request(self):
        result = make_engine().answer("作业代码跑不通，能直接帮我改出答案吗？")

        self.assertEqual(result.action, "human_fallback")
        self.assertEqual(result.reason, "technical_assignment")
        self.assertIn("技术作业", result.reply)

    def test_expired_registration_uses_explicit_expired_answer(self):
        result = make_engine(today=date(2026, 7, 16)).answer("报名入口在哪里？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.intent, "registration.link")
        self.assertIn("报名已于 2026 年 7 月 15 日截止", result.reply)
        self.assertIn("https://developer.metax-tech.com/activities/18", result.reply)

    def test_natural_registration_time_question_uses_deadline_faq(self):
        result = make_engine(today=date(2026, 7, 22)).answer("报名时间是什么时候？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.intent, "registration.deadline")
        self.assertIn("报名已于 2026 年 7 月 15 日截止", result.reply)

    def test_expired_item_without_expired_answer_is_not_sent(self):
        result = make_engine(today=date(2026, 8, 8)).answer("线下夏令营什么时候举办？")

        self.assertEqual(result.action, "needs_info")
        self.assertIn("当前资料还没有明确说明", result.reply)

    def test_uses_rag_when_faq_does_not_match(self):
        rag_result = RagSearchResult(
            reply="同学你好，营服颜色以后续官方通知为准。",
            source="线下手册 / 物料安排",
            confidence=0.91,
            chunks=[],
            is_strong=True,
        )
        rag = FakeRagRetriever(rag_result)

        result = make_engine(rag_retriever=rag).answer("营服是什么颜色？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.intent, "rag.document")
        self.assertEqual(result.reply, rag_result.reply)
        self.assertEqual(result.source, "线下手册 / 物料安排")
        self.assertEqual(result.confidence, 0.91)
        self.assertEqual(rag.questions, ["营服是什么颜色？"])

    def test_strong_official_rag_uses_ai_generated_answer(self):
        rag_result = strong_official_rag_result()
        generator = FakeRagAnswerGenerator(
            RagGenerationResult(
                "generated",
                answer="AI 整理后的回复",
                model="fake-model",
            )
        )
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
        generator = FakeRagAnswerGenerator(
            RagGenerationResult(
                "unavailable",
                model="fake-model",
                error="timeout",
            )
        )
        engine = AnswerEngine(
            KnowledgeBase.from_default(),
            rag_retriever=FakeRagRetriever(rag_result),
            rag_answer_generator=generator,
        )

        result = engine.answer("比赛镜像能下载吗？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.reply, rag_result.reply)
        self.assertEqual(result.generation_mode, "rag_fallback")
        self.assertEqual(result.generation_model, "fake-model")
        self.assertEqual(result.generation_error, "timeout")

    def test_uses_rag_when_faq_match_is_below_auto_reply_threshold(self):
        rag_result = RagSearchResult(
            reply="报名后的具体安排请查看最新官方通知。",
            source="官方通知 / 报名后安排",
            confidence=0.90,
            chunks=[],
            is_strong=True,
        )
        rag = FakeRagRetriever(rag_result)
        engine = make_engine(rag_retriever=rag)
        question = "报名后具体怎么安排？"

        matched_item, faq_confidence = engine._retrieve(question)
        result = engine.answer(question)

        self.assertIsNotNone(matched_item)
        self.assertLess(faq_confidence, 0.55)
        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.intent, "rag.document")
        self.assertEqual(result.reply, rag_result.reply)
        self.assertEqual(rag.questions, [question])

    def test_does_not_call_rag_when_faq_has_confident_answer(self):
        rag_result = RagSearchResult(
            reply="错误的 RAG 回复",
            source="线下手册",
            confidence=0.99,
            chunks=[],
            is_strong=True,
        )
        rag = FakeRagRetriever(rag_result)
        generator = FakeRagAnswerGenerator(
            RagGenerationResult(
                "generated",
                answer="错误的 AI 回复",
                model="fake-model",
            )
        )

        result = AnswerEngine(
            KnowledgeBase.from_default(),
            rag_retriever=rag,
            rag_answer_generator=generator,
        ).answer("报名入口在哪里？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.intent, "registration.link")
        self.assertEqual(result.generation_mode, "faq")
        self.assertIn("https://developer.metax-tech.com/activities/18", result.reply)
        self.assertNotIn("v.wjx.cn", result.reply)
        self.assertEqual(rag.questions, [])
        self.assertEqual(generator.calls, [])

    def test_returns_needs_info_when_rag_misses(self):
        generator = FakeRagAnswerGenerator(
            RagGenerationResult(
                "generated",
                answer="错误的 AI 回复",
                model="fake-model",
            )
        )
        result = AnswerEngine(
            KnowledgeBase.from_default(),
            rag_retriever=FakeRagRetriever(None),
            rag_answer_generator=generator,
        ).answer("营服是什么颜色？")

        self.assertEqual(result.action, "needs_info")
        self.assertEqual(result.generation_mode, "needs_info")
        self.assertIn("当前资料还没有明确说明", result.reply)
        self.assertEqual(generator.calls, [])

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

        generator = FakeRagAnswerGenerator(
            RagGenerationResult(
                "generated",
                answer="错误的 AI 回复",
                model="fake-model",
            )
        )
        result = AnswerEngine(
            KnowledgeBase.from_default(),
            rag_retriever=FakeRagRetriever(rag_result),
            rag_answer_generator=generator,
        ).answer("cmake 构建失败怎么办？")

        self.assertEqual(result.action, "suggested_reply")
        self.assertEqual(result.intent, "rag.document")
        self.assertEqual(result.generation_mode, "rag_community")
        self.assertEqual(result.source, rag_result.source)
        self.assertEqual(generator.calls, [])

    def test_semantic_faq_candidate_answers_low_lexical_similarity_question(self):
        analyzer = FakeSemanticAnalyzer(
            analyzed(
                canonical_question="线下夏令营在哪里举办？",
                intent="offline.location",
                faq_candidate_ids=["faq.offline.location"],
                semantic_confidence=0.96,
            )
        )
        engine = AnswerEngine(
            KnowledgeBase.from_default(),
            semantic_analyzer=analyzer,
            today=date(2026, 7, 23),
        )

        result = engine.answer("线下营地址是什么？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.intent, "offline.location")
        self.assertEqual(result.generation_mode, "faq")
        self.assertEqual(result.semantic_status, "analyzed")
        self.assertEqual(result.semantic_confidence, 0.96)
        self.assertLess(result.faq_confidence, 0.55)
        self.assertEqual(len(analyzer.calls), 1)
        self.assertIn(
            "faq.offline.location",
            [item["id"] for item in analyzer.calls[0][1].faq_items],
        )

    def test_not_grounded_semantic_rag_becomes_pending_with_cautious_reply(self):
        rag_result = strong_official_rag_result()
        rag_result = RagSearchResult(
            **{
                **rag_result.__dict__,
                "confidence": 0.94,
                "retrieval_mode": "semantic",
                "lexical_confidence": 0.326,
                "semantic_confidence": 0.94,
            }
        )
        retriever = SemanticFakeRagRetriever(rag_result)
        analyzer = FakeSemanticAnalyzer(
            analyzed(
                canonical_question="XPUOJ 的 MoE 分数为什么下降？",
                intent="evaluation.scoring",
                rag_candidate_ids=["chunk-1"],
                semantic_confidence=0.94,
            )
        )
        generator = FakeRagAnswerGenerator(
            RagGenerationResult(
                "invalid",
                model="fake-model",
                error="not_grounded",
            )
        )
        engine = AnswerEngine(
            KnowledgeBase.from_default(),
            rag_retriever=retriever,
            rag_answer_generator=generator,
            semantic_analyzer=analyzer,
        )

        result = engine.answer("XPUOJ测评 MoE 耗时减少了但是分数反而降低了？")

        self.assertEqual(result.action, "suggested_reply")
        self.assertEqual(result.generation_mode, "rag_insufficient")
        self.assertEqual(result.reason, "not_grounded")
        self.assertEqual(result.semantic_intent, "evaluation.scoring")
        self.assertEqual(result.rag_confidence, 0.326)
        self.assertIn("没有说明", result.reply)
        self.assertIn("XPUOJ", result.reply)
        self.assertEqual(
            retriever.semantic_calls[0][1],
            ["chunk-1"],
        )

    def test_semantic_rag_candidate_can_generate_grounded_answer(self):
        rag_result = strong_official_rag_result()
        rag_result = RagSearchResult(
            **{
                **rag_result.__dict__,
                "confidence": 0.95,
                "retrieval_mode": "semantic",
                "lexical_confidence": 0.20,
                "semantic_confidence": 0.95,
            }
        )
        analyzer = FakeSemanticAnalyzer(
            analyzed(
                canonical_question="赛题问题应该通过什么渠道提问并联系谁？",
                intent="support.contact",
                rag_candidate_ids=["chunk-1"],
                semantic_confidence=0.95,
            )
        )
        generator = FakeRagAnswerGenerator(
            RagGenerationResult(
                "generated",
                answer="建议优先通过 GitLink Issue 提交问题，并加入赛事答疑群。",
                model="fake-model",
            )
        )
        engine = AnswerEngine(
            KnowledgeBase.from_default(),
            rag_retriever=SemanticFakeRagRetriever(rag_result),
            rag_answer_generator=generator,
            semantic_analyzer=analyzer,
        )

        result = engine.answer("夏令营期间我碰到问题该找谁处理？")

        self.assertEqual(result.action, "auto_reply")
        self.assertEqual(result.generation_mode, "rag_ai")
        self.assertEqual(result.semantic_intent, "support.contact")
        self.assertEqual(result.reply, "建议优先通过 GitLink Issue 提交问题，并加入赛事答疑群。")

    def test_human_safety_fallback_runs_before_external_semantic_analyzer(self):
        analyzer = FakeSemanticAnalyzer(analyzed())
        engine = AnswerEngine(
            KnowledgeBase.from_default(),
            semantic_analyzer=analyzer,
        )

        result = engine.answer("老师，我被录取了吗？能帮我查下面试结果吗？")

        self.assertEqual(result.action, "human_fallback")
        self.assertEqual(analyzer.calls, [])

    def test_unavailable_semantic_analyzer_falls_back_to_local_faq(self):
        analyzer = FakeSemanticAnalyzer(
            SemanticAnalysisResult(
                "unavailable",
                model="semantic-model",
                error="insufficient_quota",
            )
        )
        engine = AnswerEngine(
            KnowledgeBase.from_default(),
            semantic_analyzer=analyzer,
            today=date(2026, 7, 23),
        )

        result = engine.answer("线下夏令营在哪？")

        self.assertEqual(result.intent, "offline.location")
        self.assertEqual(result.generation_mode, "faq")
        self.assertEqual(result.semantic_status, "unavailable")
        self.assertEqual(result.semantic_error, "insufficient_quota")

    def test_can_use_custom_answer_provider_chain(self):
        result = AnswerEngine(
            KnowledgeBase.from_default(),
            providers=[CustomProvider()],
        ).answer("报名入口在哪里？")

        self.assertEqual(result.action, "suggested_reply")
        self.assertEqual(result.intent, "custom.intent")
        self.assertEqual(result.source, "custom-provider")
        self.assertEqual(result.reply, "自定义回复：报名入口在哪里？")


if __name__ == "__main__":
    unittest.main()
