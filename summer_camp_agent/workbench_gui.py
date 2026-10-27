from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .chat_log_sanitizer import hash_identifier
from .workbench_models import ChatEvent, GroupConfig
from .workbench_presenter import build_demo_events, format_item_summary, status_label, truncate_text
from .workbench_session import WorkbenchItem, WorkbenchSession
from .workbench_sources import ChatSourceError, JsonlChatSource


class SummerCampWorkbenchApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("夏令营群聊答疑运营工作台")
        self.root.geometry("1240x760")
        self.root.minsize(980, 600)

        self.group_config = GroupConfig(group_name="夏令营咨询群", mode="semi_auto")
        self.session = WorkbenchSession(self.group_config)
        self.current_item: WorkbenchItem | None = None
        self.items: list[WorkbenchItem] = []
        self.row_items: list[WorkbenchItem | None] = []
        self.group_listbox: tk.Listbox
        self.message_stream: tk.Listbox
        self.decision_text: scrolledtext.ScrolledText
        self.reply_text: tk.Text
        self.status_var = tk.StringVar(value="就绪")
        self.mode_var = tk.StringVar(value="半自动模式")

        self._build_ui()
        self._load_demo_data()

    @staticmethod
    def default_group_names() -> list[str]:
        return ["夏令营咨询群", "入营通知群", "技术答疑群"]

    @staticmethod
    def demo_events() -> list[ChatEvent]:
        return build_demo_events()

    @staticmethod
    def format_item_summary(item: WorkbenchItem) -> str:
        return format_item_summary(item)

    @staticmethod
    def _status_label(item: WorkbenchItem) -> str:
        return status_label(item)

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        return truncate_text(text, limit)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, minsize=230, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.columnconfigure(2, minsize=340, weight=0)
        self.root.rowconfigure(1, weight=1)

        self._build_header()
        self._build_group_panel()
        self._build_message_panel()
        self._build_decision_panel()
        self._build_reply_bar()
        self._build_status_bar()

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg="#f6f7f8", padx=14, pady=10)
        header.grid(row=0, column=0, columnspan=3, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="夏令营群聊答疑运营工作台",
            font=("Microsoft YaHei UI", 15, "bold"),
            bg="#f6f7f8",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            header,
            textvariable=self.mode_var,
            font=("Microsoft YaHei UI", 10),
            fg="#256029",
            bg="#f6f7f8",
        ).grid(row=0, column=1, sticky="e")

    def _build_group_panel(self) -> None:
        panel = tk.Frame(self.root, bg="#f2f3f5", padx=10, pady=10)
        panel.grid(row=1, column=0, sticky="nsew")
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)
        tk.Label(panel, text="群聊", bg="#f2f3f5", font=("Microsoft YaHei UI", 11, "bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", pady=(0, 8)
        )
        self.group_listbox = tk.Listbox(panel, activestyle="none", exportselection=False, font=("Microsoft YaHei UI", 10))
        for name in self.default_group_names():
            self.group_listbox.insert(tk.END, f"● {name}  半自动")
        self.group_listbox.selection_set(0)
        self.group_listbox.grid(row=1, column=0, sticky="nsew")

        actions = tk.Frame(panel, bg="#f2f3f5")
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        ttk.Button(actions, text="载入演示", command=self._load_demo_data).grid(row=0, column=0, sticky="ew")
        ttk.Button(actions, text="导入 JSONL", command=self._import_jsonl).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(actions, text="暂停监听", command=self._pause_listener).grid(row=2, column=0, sticky="ew", pady=(6, 0))

    def _build_message_panel(self) -> None:
        panel = tk.Frame(self.root, padx=12, pady=10)
        panel.grid(row=1, column=1, sticky="nsew")
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)
        tk.Label(panel, text="消息流", font=("Microsoft YaHei UI", 11, "bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", pady=(0, 8)
        )
        self.message_stream = tk.Listbox(
            panel,
            activestyle="none",
            exportselection=False,
            font=("Microsoft YaHei UI", 10),
            selectmode=tk.SINGLE,
        )
        self.message_stream.grid(row=1, column=0, sticky="nsew")
        self.message_stream.bind("<<ListboxSelect>>", self._on_message_select)

    def _build_decision_panel(self) -> None:
        panel = tk.Frame(self.root, padx=12, pady=10, bg="#fbfbfb")
        panel.grid(row=1, column=2, sticky="nsew")
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)
        tk.Label(
            panel,
            text="决策面板",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg="#fbfbfb",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.decision_text = scrolledtext.ScrolledText(panel, wrap=tk.WORD, font=("Microsoft YaHei UI", 9), state=tk.DISABLED)
        self.decision_text.grid(row=1, column=0, sticky="nsew")

        button_row = tk.Frame(panel, bg="#fbfbfb")
        button_row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        button_row.columnconfigure(0, weight=1)
        button_row.columnconfigure(1, weight=1)
        ttk.Button(button_row, text="保存候选", command=self._save_current_candidate).grid(row=0, column=0, sticky="ew")
        ttk.Button(button_row, text="转人工", command=self._mark_escalated).grid(row=0, column=1, sticky="ew", padx=(8, 0))

    def _build_reply_bar(self) -> None:
        panel = tk.Frame(self.root, padx=12, pady=10)
        panel.grid(row=2, column=0, columnspan=3, sticky="ew")
        panel.columnconfigure(0, weight=1)
        self.reply_text = tk.Text(panel, height=3, wrap=tk.WORD, font=("Microsoft YaHei UI", 10))
        self.reply_text.grid(row=0, column=0, sticky="ew")

        button_row = tk.Frame(panel)
        button_row.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        ttk.Button(button_row, text="生成草稿", command=self._generate_draft_from_input).grid(row=0, column=0, sticky="ew")
        ttk.Button(button_row, text="发送", command=self._send_reply).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(button_row, text="复制", command=self._copy_reply).grid(row=2, column=0, sticky="ew", pady=(6, 0))

    def _build_status_bar(self) -> None:
        tk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            padx=12,
            pady=6,
            font=("Microsoft YaHei UI", 9),
            fg="#555555",
        ).grid(row=3, column=0, columnspan=3, sticky="ew")

    def _load_demo_data(self) -> None:
        self._load_events(self.demo_events(), "已载入演示数据：包含可答复、转人工、待补充和未触发消息。")

    def _import_jsonl(self) -> None:
        path = filedialog.askopenfilename(
            title="选择已脱敏聊天记录 JSONL",
            filetypes=[("JSONL 文件", "*.jsonl"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            events = JsonlChatSource(path).load_events()
        except (ChatSourceError, OSError, ValueError) as exc:
            messagebox.showerror("导入失败", str(exc))
            return
        self._load_events(events, f"已导入 {len(events)} 条聊天记录：{path}")

    def _load_events(self, events: list[ChatEvent], status: str) -> None:
        self.items.clear()
        self.row_items.clear()
        self.message_stream.delete(0, tk.END)
        self.current_item = None
        self._set_reply("")
        self._clear_decision("请选择一条消息查看触发结果、回复依据和处理建议。")

        for event in events:
            self._add_event(event)

        if self.items:
            self._select_row(0)
        self.status_var.set(status)

    def _add_event(self, event: ChatEvent) -> WorkbenchItem:
        item = self.session.process_event(event)
        self.items.append(item)
        self.row_items.append(item)
        self.message_stream.insert(tk.END, self.format_item_summary(item))
        self._style_row(self.message_stream.size() - 1, item)
        return item

    def _style_row(self, index: int, item: WorkbenchItem) -> None:
        colors = {
            "draft": ("#111111", "#f7fbff"),
            "auto_send": ("#1f6f43", "#f3fbf6"),
            "escalate": ("#8a4b00", "#fff8ed"),
            "mark_pending": ("#755100", "#fffbe8"),
            "ignored": ("#777777", "#f7f7f7"),
        }
        foreground, background = colors.get(item.reply_decision.mode, ("#111111", "#ffffff"))
        self.message_stream.itemconfig(index, foreground=foreground, background=background)

    def _select_row(self, index: int) -> None:
        self.message_stream.selection_clear(0, tk.END)
        self.message_stream.selection_set(index)
        self.message_stream.activate(index)
        self._show_item_at_row(index)

    def _on_message_select(self, _event: tk.Event) -> None:
        selection = self.message_stream.curselection()
        if not selection:
            return
        self._show_item_at_row(selection[0])

    def _show_item_at_row(self, row_index: int) -> None:
        if row_index >= len(self.row_items):
            return
        item = self.row_items[row_index]
        if item is None:
            return
        self.current_item = item
        self._render_decision(item)
        self._set_reply(item.reply_decision.reply)
        self.status_var.set(f"当前消息：{self._status_label(item)}")

    def _generate_draft_from_input(self) -> None:
        question = self.reply_text.get("1.0", tk.END).strip()
        if not question:
            messagebox.showinfo("需要输入", "请先在底部输入学生问题，再生成草稿。")
            return
        event = ChatEvent(
            event_id=hash_identifier(f"{datetime.now().isoformat()}:{question}"),
            group_id_hash="sha256:manual",
            group_name=self.group_config.group_name,
            sender_alias="手动输入",
            sender_role="student",
            message_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            content=question,
            raw_type="text",
            source="manual",
        )
        self._add_event(event)
        self._select_row(self.message_stream.size() - 1)

    def _send_reply(self) -> None:
        reply = self.reply_text.get("1.0", tk.END).strip()
        if not reply:
            return
        if self.current_item is not None:
            self.session.confirm_reply(self.current_item, reply)
        self._append_log_row(f"[已发送] 运营：{self._truncate(reply, 58)}")
        self.status_var.set("已记录发送动作。普通微信阶段不执行隐藏式自动发送。")

    def _copy_reply(self) -> None:
        reply = self.reply_text.get("1.0", tk.END).strip()
        if not reply:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(reply)
        self.status_var.set("已复制回复内容。")

    def _save_current_candidate(self) -> None:
        if self.current_item is None:
            messagebox.showinfo("暂无候选", "请先选择或生成一条草稿。")
            return
        reply = self.reply_text.get("1.0", tk.END).strip()
        if self.session.save_candidate(self.current_item, reply):
            self._append_log_row(f"[已入候选] {self._truncate(self.current_item.event.content, 48)}")
            self.status_var.set("已保存到待审核候选库，未写入正式 FAQ。")

    def _mark_escalated(self) -> None:
        self._append_log_row("[转人工] 当前问题已标记为人工跟进")
        self.status_var.set("已标记转人工。")

    def _pause_listener(self) -> None:
        self.status_var.set("已暂停监听。本地 MVP 当前以演示数据和 JSONL 导入为主。")

    def _append_log_row(self, text: str) -> None:
        self.row_items.append(None)
        self.message_stream.insert(tk.END, text)
        self.message_stream.itemconfig(self.message_stream.size() - 1, foreground="#555555", background="#f6f7f8")
        self.message_stream.see(tk.END)

    def _render_decision(self, item: WorkbenchItem) -> None:
        lines = [
            f"学生问题：{item.event.content}",
            "",
            f"处理状态：{self._status_label(item)}",
            f"触发原因：{', '.join(item.trigger.reasons) or '未触发'}",
            f"命中关键词：{', '.join(item.trigger.matched_keywords) or '无'}",
            "",
            f"建议动作：{item.review_card.recommendation}",
            f"引擎动作：{item.review_card.action}",
            f"意图：{item.review_card.intent or '未知'}",
            f"来源：{item.review_card.source or '无'}",
            f"置信度：{item.review_card.confidence:.2f}",
            f"模式决策：{item.reply_decision.mode}",
            f"原因：{item.reply_decision.reason or item.review_card.reason or '无'}",
            "",
            "回复草稿：",
            item.reply_decision.reply or "当前无需生成回复。",
        ]
        self._set_decision("\n".join(lines))

    def _clear_decision(self, text: str) -> None:
        self._set_decision(text)

    def _set_decision(self, text: str) -> None:
        self.decision_text.configure(state=tk.NORMAL)
        self.decision_text.delete("1.0", tk.END)
        self.decision_text.insert(tk.END, text)
        self.decision_text.configure(state=tk.DISABLED)

    def _set_reply(self, text: str) -> None:
        self.reply_text.delete("1.0", tk.END)
        if text:
            self.reply_text.insert(tk.END, text)


def main() -> None:
    root = tk.Tk()
    SummerCampWorkbenchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
