"""Reusable GUI widgets."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

_LIST_FONT = ("Microsoft YaHei UI", 11)


class ScrollableComboBox(ctk.CTkFrame):
    """Combo box with an inline scrollable list.

    Keeping the list inside the tab avoids Windows top-level/focus glitches and
    makes the mouse wheel work consistently.
    """

    _open_widget: ScrollableComboBox | None = None

    def __init__(
        self,
        master,
        variable: tk.StringVar,
        values: list[str] | None = None,
        command: Callable[[str], None] | None = None,
        list_height: int = 220,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._variable = variable
        self._values = list(values or [])
        self._command = command
        self._list_height = list_height
        self._filtered: list[str] = []
        self._filter_job: str | None = None

        self.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)

        self._entry = ctk.CTkEntry(top, textvariable=variable)
        self._entry.grid(row=0, column=0, sticky="ew")
        self._entry.bind("<Button-1>", self._toggle_list)
        self._entry.bind("<Key>", lambda _e: "break")
        self._button = ctk.CTkButton(top, text="▼", width=32, command=self._toggle_list)
        self._button.grid(row=0, column=1, padx=(6, 0))

        self._dropdown = ctk.CTkFrame(self)
        self._dropdown.grid_columnconfigure(0, weight=1)

        self._search_var = tk.StringVar()
        self._search = ctk.CTkEntry(self._dropdown, placeholder_text="搜索字体", textvariable=self._search_var)
        self._search.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))

        list_frame = tk.Frame(self._dropdown)
        list_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        list_frame.grid_columnconfigure(0, weight=1)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        self._listbox = tk.Listbox(
            list_frame,
            height=max(5, list_height // 24),
            font=_LIST_FONT,
            activestyle="none",
            exportselection=False,
            selectmode=tk.SINGLE,
            yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=self._listbox.yview)
        self._listbox.grid(row=0, column=0, sticky="ew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self._search_var.trace_add("write", self._schedule_filter)
        self._listbox.bind("<Double-Button-1>", self._pick_selected)
        self._listbox.bind("<Return>", self._pick_selected)
        self._listbox.bind("<ButtonRelease-1>", self._pick_selected)
        self._listbox.bind("<MouseWheel>", self._on_wheel)
        self._dropdown.bind("<MouseWheel>", self._on_wheel)

        self._fill_listbox(self._values)

    def configure(self, **kwargs) -> None:
        if "values" in kwargs:
            self._values = list(kwargs.pop("values"))
            self._fill_listbox(self._values)
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if kwargs:
            super().configure(**kwargs)

    def get(self) -> str:
        return self._variable.get()

    def set(self, value: str) -> None:
        self._variable.set(value)

    def close(self) -> None:
        if self._filter_job:
            self.after_cancel(self._filter_job)
            self._filter_job = None
        self._dropdown.grid_remove()
        self._button.configure(text="▼")
        if ScrollableComboBox._open_widget is self:
            ScrollableComboBox._open_widget = None

    def destroy(self) -> None:
        self.close()
        super().destroy()

    def _toggle_list(self, _event=None) -> str:
        if self._dropdown.winfo_ismapped():
            self.close()
        else:
            self._open_list()
        return "break"

    def _open_list(self) -> None:
        if not self._values:
            return
        if ScrollableComboBox._open_widget is not None and ScrollableComboBox._open_widget is not self:
            ScrollableComboBox._open_widget.close()
        ScrollableComboBox._open_widget = self
        self._search_var.set("")
        self._fill_listbox(self._values)
        self._dropdown.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self._button.configure(text="▲")
        self._search.focus_set()

    def _schedule_filter(self, *_args) -> None:
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(120, self._apply_filter)

    def _apply_filter(self) -> None:
        self._filter_job = None
        q = self._search_var.get().strip().lower()
        items = [v for v in self._values if q in v.lower()] if q else self._values
        self._fill_listbox(items)

    def _fill_listbox(self, items: list[str]) -> None:
        self._filtered = list(items)
        self._listbox.delete(0, tk.END)
        for name in self._filtered:
            self._listbox.insert(tk.END, name)
        if self._filtered:
            self._listbox.selection_set(0)
            self._listbox.see(0)

    def _on_wheel(self, event: tk.Event) -> str:
        delta = -1 if event.delta > 0 else 1
        self._listbox.yview_scroll(delta, "units")
        return "break"

    def _pick_selected(self, _event=None) -> str:
        sel = self._listbox.curselection()
        if sel:
            value = self._filtered[sel[0]]
            self._variable.set(value)
            if self._command:
                self._command(value)
            self.close()
        return "break"
