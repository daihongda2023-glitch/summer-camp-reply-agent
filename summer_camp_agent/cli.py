from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .chat_log_sanitizer import hash_identifier
from .engine import AnswerEngine
from .knowledge import KnowledgeBase, KnowledgeValidationError
from .review import OperatorReview, ReviewCard, save_pending_question
from .weflow_import import (
    WeFlowAuthError,
    WeFlowImportConfig,
    WeFlowImportError,
    WeFlowSessionSelectionRequired,
    import_weflow_chat,
)


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="夏令营自动回复 agent 本地工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask_parser = subparsers.add_parser("ask", help="输入学生问题并生成建议回复")
    ask_parser.add_argument("question", help="学生问题")
    ask_parser.add_argument("--today", help="按 YYYY-MM-DD 指定当前日期，便于测试过期规则")
    ask_parser.add_argument("--knowledge", help="知识库 JSON 路径")

    review_parser = subparsers.add_parser("review", help="生成运营半自动审核卡")
    review_parser.add_argument("question", help="学生问题")
    review_parser.add_argument("--today", help="按 YYYY-MM-DD 指定当前日期，便于测试过期规则")
    review_parser.add_argument("--knowledge", help="知识库 JSON 路径")
    review_parser.add_argument("--pending-log", help="当建议标记待补充时，写入 JSONL 待确认清单")

    validate_parser = subparsers.add_parser("validate", help="校验知识库结构和自动回复安全字段")
    validate_parser.add_argument("knowledge", nargs="?", help="知识库 JSON 路径，默认使用 data/faq.json")

    import_weflow_parser = subparsers.add_parser("import-weflow", help="从 WeFlow 本地 API 导入微信群聊天记录")
    import_weflow_parser.add_argument("--group", required=True, help="微信群聊名称")
    import_weflow_parser.add_argument("--session-id", default="", help="WeFlow 会话 ID，多个群聊同名时使用")
    import_weflow_parser.add_argument("--keywords", default="", help="逗号分隔关键词，例如：报名,住宿,交通")
    import_weflow_parser.add_argument("--start", default="", help="开始日期 YYYYMMDD")
    import_weflow_parser.add_argument("--end", default="", help="结束日期 YYYYMMDD")
    import_weflow_parser.add_argument("--limit", type=int, default=5000, help="单页拉取上限，最大 5000")
    import_weflow_parser.add_argument("--output-dir", default="imports/chat_logs", help="输出目录")
    import_weflow_parser.add_argument("--base-url", default="http://127.0.0.1:5031", help="WeFlow 本地 API 地址")
    import_weflow_parser.add_argument("--token-env", default="WEFLOW_API_TOKEN", help="保存 WeFlow Token 的环境变量名")
    import_weflow_parser.add_argument("--include-media", action="store_true", help="保留纯媒体占位消息，不下载媒体文件")

    args = parser.parse_args(argv)
    try:
        if args.command == "ask":
            return _ask(args)
        if args.command == "review":
            return _review(args)
        if args.command == "validate":
            return _validate(args.knowledge)
        if args.command == "import-weflow":
            return _import_weflow(args)
    except KnowledgeValidationError as exc:
        print(f"知识库校验失败: {exc}", file=sys.stderr)
        return 1
    except WeFlowSessionSelectionRequired as exc:
        print(str(exc), file=sys.stderr)
        for index, session in enumerate(exc.sessions, start=1):
            print(f"{index}. name={session.name} id_hash={hash_identifier(session.id)} type={session.type}", file=sys.stderr)
        return 2
    except WeFlowAuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except WeFlowImportError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 1


def _ask(args: argparse.Namespace) -> int:
    kb = _load_knowledge(args.knowledge)
    today = date.fromisoformat(args.today) if args.today else None
    result = AnswerEngine(kb, today=today).answer(args.question)
    print(f"action: {result.action}")
    if result.intent:
        print(f"intent: {result.intent}")
    if result.reason:
        print(f"reason: {result.reason}")
    if result.source:
        print(f"source: {result.source}")
    if result.confidence:
        print(f"confidence: {result.confidence:.2f}")
    print("reply:")
    print(result.reply)
    return 0


def _validate(path: str | None) -> int:
    kb = _load_knowledge(path)
    print(f"知识库校验通过，共 {len(kb.items)} 条。")
    return 0


def _review(args: argparse.Namespace) -> int:
    kb = _load_knowledge(args.knowledge)
    today = date.fromisoformat(args.today) if args.today else None
    engine = AnswerEngine(kb, today=today)
    card = OperatorReview(engine).create_card(args.question)
    pending_saved = False
    if args.pending_log and card.recommendation == "mark_pending":
        save_pending_question(card, args.pending_log)
        pending_saved = True
    _print_review_card(card, pending_saved=pending_saved)
    return 0


def _import_weflow(args: argparse.Namespace) -> int:
    keywords = [item.strip() for item in args.keywords.split(",") if item.strip()]
    config = WeFlowImportConfig(
        group_name=args.group,
        session_id=args.session_id,
        keywords=keywords,
        start=args.start,
        end=args.end,
        limit=args.limit,
        output_dir=Path(args.output_dir),
        base_url=args.base_url,
        token_env=args.token_env,
        include_media=args.include_media,
    )
    summary = import_weflow_chat(config)
    print(f"group: {summary.group_name}")
    print(f"session_id_hash: {summary.session_id_hash}")
    print(f"pulled_count: {summary.pulled_count}")
    print(f"written_count: {summary.written_count}")
    print(f"skipped_count: {summary.skipped_count}")
    print(f"output: {summary.output_path}")
    return 0


def _print_review_card(card: ReviewCard, pending_saved: bool) -> None:
    print(f"question: {card.original_question}")
    print(f"recommendation: {card.recommendation}")
    print(f"available_actions: {', '.join(card.available_actions)}")
    print(f"action: {card.action}")
    if card.intent:
        print(f"intent: {card.intent}")
    if card.reason:
        print(f"reason: {card.reason}")
    if card.source:
        print(f"source: {card.source}")
    if card.confidence:
        print(f"confidence: {card.confidence:.2f}")
    print(f"pending_saved: {str(pending_saved).lower()}")
    print("reply:")
    print(card.reply)


def _load_knowledge(path: str | None) -> KnowledgeBase:
    if path:
        return KnowledgeBase.from_json(Path(path))
    return KnowledgeBase.from_default()


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
