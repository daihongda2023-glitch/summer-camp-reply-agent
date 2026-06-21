from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, scrolledtext

from .desktop_chat import DesktopChatSession


class SummerCampAgentApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.session = DesktopChatSession()
        self.root.title("夏令营自动回复 Agent")
        self.root.geometry("760x620")
        self.root.minsize(560, 420)

        self._build_ui()
        self._append_agent(
            "你好，我是夏令营自动回复 Agent。\n"
            "你可以直接输入学生问题，例如：报名入口在哪里？线下夏令营什么时候举办？\n"
            "如果回答不对，可以输入：修正上个问题的回答结果：这里写正确答案。\n"
            "这会写入本地覆盖 FAQ，仅用于桌面验证。"
        )

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = tk.Frame(self.root, padx=16, pady=12)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        title = tk.Label(
            header,
            text="夏令营自动回复 Agent",
            font=("Microsoft YaHei UI", 16, "bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="ew")

        subtitle = tk.Label(
            header,
            text="本地验证版：基于当前知识库生成建议回复，未知或敏感问题会转人工/待补充。",
            font=("Microsoft YaHei UI", 9),
            fg="#555555",
            anchor="w",
        )
        subtitle.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        self.chat = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            padx=12,
            pady=12,
            font=("Microsoft YaHei UI", 10),
            state=tk.DISABLED,
        )
        self.chat.grid(row=1, column=0, sticky="nsew", padx=16)

        input_frame = tk.Frame(self.root, padx=16, pady=12)
        input_frame.grid(row=2, column=0, sticky="ew")
        input_frame.columnconfigure(0, weight=1)

        self.input_var = tk.StringVar()
        self.input_entry = tk.Entry(
            input_frame,
            textvariable=self.input_var,
            font=("Microsoft YaHei UI", 11),
        )
        self.input_entry.grid(row=0, column=0, sticky="ew")
        self.input_entry.bind("<Return>", self._on_send)

        send_button = tk.Button(input_frame, text="发送", width=10, command=self._on_send)
        send_button.grid(row=0, column=1, padx=(8, 0))

        pending_button = tk.Button(
            input_frame,
            text="标记待补充",
            width=12,
            command=self._on_save_pending,
        )
        pending_button.grid(row=0, column=2, padx=(8, 0))

        self.status_var = tk.StringVar(value="就绪")
        status = tk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            padx=16,
            pady=8,
            font=("Microsoft YaHei UI", 9),
            fg="#555555",
        )
        status.grid(row=3, column=0, sticky="ew")

        self.input_entry.focus_set()

    def _on_send(self, event: object | None = None) -> None:
        question = self.input_var.get().strip()
        if not question:
            return
        self.input_var.set("")
        self._append_user(question)
        message = self.session.ask(question)
        self._append_agent(message.display_text)
        self.status_var.set(f"建议动作：{message.recommendation}")

    def _on_save_pending(self) -> None:
        if self.session.save_last_pending():
            self.status_var.set("已写入 data/pending_questions.jsonl")
            messagebox.showinfo("已标记", "已写入待补充清单。")
            return
        messagebox.showinfo("无需标记", "当前最近一条回复不是待补充问题。")

    def _append_user(self, text: str) -> None:
        self._append("你", text)

    def _append_agent(self, text: str) -> None:
        self._append("Agent", text)

    def _append(self, speaker: str, text: str) -> None:
        self.chat.configure(state=tk.NORMAL)
        self.chat.insert(tk.END, f"{speaker}：\n{text}\n\n")
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)


def main() -> None:
    root = tk.Tk()
    SummerCampAgentApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
