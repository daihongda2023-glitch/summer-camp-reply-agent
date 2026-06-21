from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from .chat_log_sanitizer import hash_identifier
from .workbench_models import ChatEvent, GroupConfig
from .workbench_session import WorkbenchItem, WorkbenchSession


class SummerCampWorkbenchApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("夏令营群聊答疑运营工作台")
        self.root.geometry("1180x720")
        self.root.minsize(920, 560)

        self.group_config = GroupConfig(group_name="夏令营咨询群", mode="semi_auto")
        self.session = WorkbenchSession(self.group_config)
        self.current_item: WorkbenchItem | None = None
        self.group_listbox: tk.Listbox
        self.message_stream: scrolledtext.ScrolledText
        self.decision_text: scrolledtext.ScrolledText
        self.reply_text: tk.Text
        self.status_var = tk.StringVar(value="就绪")
        self.mode_var = tk.StringVar(value="半自动")

        self._build_ui()
        self._append_system_message("工作台已启动。当前为半自动模式：触发消息会生成草稿，发送前可人工修改。")

    @staticmethod
    def default_group_names() -> list[str]:
        return ["夏令营咨询群", "入营通知群", "技术答疑群"]

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, minsize=220, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.columnconfigure(2, minsize=300, weight=0)
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
        ttk.Button(actions, text="导入记录", command=self._show_not_ready).grid(row=0, column=0, sticky="ew")
        ttk.Button(actions, text="暂停监听", command=self._show_not_ready).grid(row=1, column=0, sticky="ew", pady=(6, 0))

    def _build_message_panel(self) -> None:
        panel = tk.Frame(self.root, padx=12, pady=10)
        panel.grid(row=1, column=1, sticky="nsew")
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)
        tk.Label(panel, text="消息流", font=("Microsoft YaHei UI", 11, "bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", pady=(0, 8)
        )
        self.message_stream = scrolledtext.ScrolledText(panel, wrap=tk.WORD, font=("Microsoft YaHei UI", 10), state=tk.DISABLED)
        self.message_stream.grid(row=1, column=0, sticky="nsew")

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

    def _generate_draft_from_input(self) -> None:
        question = self.reply_text.get("1.0", tk.END).strip()
        if not question:
            messagebox.showinfo("需要输入", "请先在底部输入学生问题，再生成草稿。")
            return
        event = ChatEvent(
            event_id=hash_identifier(f"{datetime.now().isoformat()}:{question}"),
            group_id_hash="sha256:manual",
            group_name=self.group_config.group_name,
            sender_alias="学生",
            sender_role="student",
            message_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            content=question,
            raw_type="text",
            source="manual",
        )
        self._append_message("学生", question)
        item = self.session.process_event(event)
        self.current_item = item
        if item.reply_decision.reply:
            self._set_reply(item.reply_decision.reply)
            self._append_message("Agent 草稿", item.reply_decision.reply)
        self._render_decision(item)
        self.status_var.set(f"处理结果：{item.reply_decision.mode}")

    def _send_reply(self) -> None:
        reply = self.reply_text.get("1.0", tk.END).strip()
        if not reply:
            return
        if self.current_item is not None:
            self.session.confirm_reply(self.current_item, reply)
        self._append_message("运营", reply)
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
        self.session.confirm_reply(self.current_item, self.reply_text.get("1.0", tk.END).strip())
        self.status_var.set("已保存到待审核候选库。")

    def _mark_escalated(self) -> None:
        self.status_var.set("已标记转人工。")
        self._append_system_message("该问题已标记为转人工处理。")

    def _show_not_ready(self) -> None:
        messagebox.showinfo("后续接入", "该能力会在监听与导入切片中接入。")

    def _render_decision(self, item: WorkbenchItem) -> None:
        lines = [
            f"触发：{', '.join(item.trigger.reasons) or '未触发'}",
            f"关键词：{', '.join(item.trigger.matched_keywords) or '无'}",
            f"动作：{item.review_card.action}",
            f"建议：{item.review_card.recommendation}",
            f"意图：{item.review_card.intent or '未知'}",
            f"来源：{item.review_card.source or '无'}",
            f"置信度：{item.review_card.confidence:.2f}",
            f"模式：{item.reply_decision.mode}",
            f"原因：{item.reply_decision.reason or '无'}",
        ]
        self.decision_text.configure(state=tk.NORMAL)
        self.decision_text.delete("1.0", tk.END)
        self.decision_text.insert(tk.END, "\n".join(lines))
        self.decision_text.configure(state=tk.DISABLED)

    def _set_reply(self, text: str) -> None:
        self.reply_text.delete("1.0", tk.END)
        self.reply_text.insert(tk.END, text)

    def _append_system_message(self, text: str) -> None:
        self._append_message("系统", text)

    def _append_message(self, speaker: str, text: str) -> None:
        self.message_stream.configure(state=tk.NORMAL)
        self.message_stream.insert(tk.END, f"{speaker}：\n{text}\n\n")
        self.message_stream.configure(state=tk.DISABLED)
        self.message_stream.see(tk.END)


def main() -> None:
    root = tk.Tk()
    SummerCampWorkbenchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
