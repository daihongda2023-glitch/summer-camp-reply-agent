from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACTIVITIES_DIR = PROJECT_ROOT / "activities"
ALLOWED_FORMATS = {"online", "offline"}
FORMAT_LABELS = {"online": "线上", "offline": "线下"}
PRODUCT_NAME = "活动值守"
PRODUCT_NAME_EN = "Activity Desk"
ACTIVITY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


class ActivityError(ValueError):
    """活动包不存在或内容不符合约定。"""


@dataclass(frozen=True)
class ActivityProfile:
    id: str
    name: str
    formats: tuple[str, ...]
    audience: str
    organizer: str
    notice_channel: str
    assistant_role: str
    router_role: str
    prompt_audience: str
    assignment_contact: str
    serves: tuple[str, ...]
    knowledge_path: Path
    documents_path: Path | None
    description: str

    @property
    def format_label(self) -> str:
        return "、".join(FORMAT_LABELS[item] for item in self.formats)


def list_activities() -> list[ActivityProfile]:
    if not ACTIVITIES_DIR.is_dir():
        raise ActivityError(f"活动目录不存在：{ACTIVITIES_DIR}")
    profiles = [_load_activity_file(path) for path in sorted(ACTIVITIES_DIR.glob("*/activity.json"))]
    ids = [profile.id for profile in profiles]
    if len(ids) != len(set(ids)):
        raise ActivityError("活动包 ID 重复。")
    if "summer-camp" not in ids:
        raise ActivityError("缺少默认活动包 summer-camp。")
    return profiles


def load_activity(activity_id: str | None) -> ActivityProfile:
    target = (activity_id or "summer-camp").strip() or "summer-camp"
    for profile in list_activities():
        if profile.id == target:
            return profile
    known = "、".join(profile.id for profile in list_activities())
    raise ActivityError(f"未知活动 {target}。可选：{known}")


def _load_activity_file(path: Path) -> ActivityProfile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActivityError(f"活动包无法读取：{path}") from exc
    if not isinstance(raw, dict):
        raise ActivityError(f"活动包必须是 JSON 对象：{path}")

    required = [
        "id",
        "name",
        "formats",
        "audience",
        "organizer",
        "notice_channel",
        "assistant_role",
        "router_role",
        "prompt_audience",
        "assignment_contact",
        "serves",
        "knowledge",
        "description",
    ]
    missing = [field for field in required if field not in raw]
    if missing:
        raise ActivityError(f"{path} 缺少字段：{', '.join(missing)}")

    activity_id = str(raw["id"]).strip()
    if activity_id != path.parent.name:
        raise ActivityError(f"{path} 的 id 必须与目录名一致。")
    formats = raw["formats"]
    if not isinstance(formats, list) or not formats:
        raise ActivityError(f"{activity_id} 至少要声明一种形式：online 或 offline。")
    normalized_formats = tuple(str(item).strip() for item in formats)
    if any(item not in ALLOWED_FORMATS for item in normalized_formats):
        raise ActivityError(f"{activity_id} 的 formats 只能包含 online 和 offline。")
    serves = _string_list(raw.get("serves"), f"{activity_id} 的 serves")
    if not serves:
        raise ActivityError(f"{activity_id} 需要至少一条适用对象 serves。")

    knowledge_path = _resolve(str(raw["knowledge"]))
    if not knowledge_path.is_file():
        raise ActivityError(f"{activity_id} 的知识库不存在：{knowledge_path}")
    documents_raw = str(raw.get("documents") or "").strip()
    documents_path = _resolve(documents_raw) if documents_raw else None
    if documents_path is not None and not documents_path.is_dir():
        raise ActivityError(f"{activity_id} 的资料目录不存在：{documents_path}")

    return ActivityProfile(
        id=activity_id,
        name=str(raw["name"]).strip(),
        formats=normalized_formats,
        audience=str(raw["audience"]).strip(),
        organizer=str(raw["organizer"]).strip(),
        notice_channel=str(raw["notice_channel"]).strip(),
        assistant_role=str(raw["assistant_role"]).strip(),
        router_role=str(raw["router_role"]).strip(),
        prompt_audience=str(raw["prompt_audience"]).strip(),
        assignment_contact=str(raw["assignment_contact"]).strip(),
        serves=tuple(serves),
        knowledge_path=knowledge_path,
        documents_path=documents_path,
        description=str(raw["description"]).strip(),
    )


def init_activity(
    activity_id: str,
    name: str,
    formats: list[str],
    serves: list[str],
    *,
    root: Path | None = None,
) -> Path:
    """生成一场可提交的活动包模板。新贡献者只填资料，不改问答内核。"""
    cleaned_id = activity_id.strip()
    if not ACTIVITY_ID_PATTERN.fullmatch(cleaned_id):
        raise ActivityError("活动 ID 需要使用小写英文、数字和连字符，例如 city-reading。")
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ActivityError("活动名称不能为空。")
    normalized_formats = tuple(dict.fromkeys(item.strip() for item in formats if item.strip()))
    if not normalized_formats or any(item not in ALLOWED_FORMATS for item in normalized_formats):
        raise ActivityError("formats 只能是 online、offline，或两者都写。")
    cleaned_serves = [item.strip() for item in serves if item.strip()]
    if not cleaned_serves:
        raise ActivityError("至少写一个适用对象，例如社团负责人或值班志愿者。")

    base = root or ACTIVITIES_DIR
    target = base / cleaned_id
    if target.exists():
        raise ActivityError(f"活动包已存在：{target}")
    target.mkdir(parents=True)
    knowledge_name = "faq.json"
    profile = {
        "id": cleaned_id,
        "name": cleaned_name,
        "formats": list(normalized_formats),
        "audience": "参与者",
        "organizer": "主办方",
        "notice_channel": "活动群",
        "assistant_role": f"{cleaned_name}咨询回复助手",
        "router_role": f"{cleaned_name}咨询系统的语义路由器",
        "prompt_audience": "参与者",
        "assignment_contact": "活动工作人员",
        "serves": cleaned_serves,
        "knowledge": f"activities/{cleaned_id}/{knowledge_name}",
        "description": f"{cleaned_name}的活动包。由组织者填写已确认信息，值班人员审核后再发送。",
    }
    (target / "activity.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (target / knowledge_name).write_text(
        json.dumps(_template_faq(cleaned_name, normalized_formats), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def split_list(value: str) -> list[str]:
    return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]


def _template_faq(name: str, formats: tuple[str, ...]) -> list[dict[str, object]]:
    items = [
        _template_item(
            "faq.event.about",
            "event.about",
            "这场活动是做什么的？",
            ["活动介绍", "这是什么活动"],
            ["活动", "介绍"],
            f"{name}的资料还是模板。请组织者把活动介绍、时间和参与方式写成已经确认的内容。",
        )
    ]
    if "online" in formats:
        items.append(
            _template_item(
                "faq.session.link",
                "session.link",
                "直播链接在哪里？",
                ["线上入口在哪里", "会议链接是什么"],
                ["直播", "线上", "链接"],
                "线上入口还是模板。请换成真实直播或会议地址后再用于自动回复。",
            )
        )
    if "offline" in formats:
        items.append(
            _template_item(
                "faq.venue.address",
                "venue.address",
                "活动地点在哪里？",
                ["线下地点在哪里", "在哪里举办"],
                ["地点", "线下"],
                "线下地点还是模板。请换成真实会场和签到时间后再用于自动回复。",
            )
        )
    if "online" in formats and "offline" in formats:
        items.append(
            _template_item(
                "faq.attendance.choice",
                "attendance.choice",
                "可以只参加线上吗？",
                ["必须到现场吗"],
                ["只参加", "线上"],
                "参加方式还是模板。请写明可以只参加线上、只到现场，还是两种都需要。",
            )
        )
    return items


def _template_item(
    item_id: str,
    intent: str,
    question: str,
    aliases: list[str],
    keywords: list[str],
    answer: str,
) -> dict[str, object]:
    return {
        "id": item_id,
        "stage": "活动准备",
        "intent": intent,
        "question": question,
        "question_aliases": aliases,
        "keywords": keywords,
        "answer": answer,
        "source": "活动包模板",
        "source_date": "2026-10-27",
        "last_updated": "2026-10-27",
        "valid_until": "2027-12-31",
        "auto_reply": True,
        "needs_human_fallback": False,
        "human_fallback_reason": "",
        "owner": "主办方",
    }


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ActivityError(f"{label} 必须是字符串数组。")
    items = [str(item).strip() for item in value if str(item).strip()]
    return items


def _resolve(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path
