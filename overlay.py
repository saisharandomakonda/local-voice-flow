from __future__ import annotations

import ctypes
import math
import threading
import time
import tkinter as tk
from tkinter import messagebox
from collections.abc import Callable


IDLE_SIZE = (58, 58)
ACTIVE_SIZE = (286, 72)
BACKGROUND = "#171717"
SURFACE = "#202020"
BORDER = "#3d3d3d"
FOREGROUND = "#f3f2ef"
MUTED = "#9d9d9d"
ACCENT = "#d4d4d4"
ACCENT_ALT = "#fafaf9"
ERROR = "#cf7770"
TRANSPARENT = "#010203"


class Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class VoiceOverlay:
    def __init__(self, on_quit: Callable[[], None], usage_summary: Callable[[], str]):
        self.on_quit = on_quit
        self.usage_summary = usage_summary
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", TRANSPARENT)
        self.root.attributes("-alpha", 0.98)
        self.root.configure(bg=TRANSPARENT)

        self.canvas = tk.Canvas(
            self.root,
            width=IDLE_SIZE[0],
            height=IDLE_SIZE[1],
            bg=TRANSPARENT,
            highlightthickness=0,
        )
        self.canvas.pack()

        self.state = "idle"
        self.message = ""
        self.state_changed_at = time.monotonic()
        self.audio_level = 0.0
        self.display_level = 0.0
        self.quit_requested = False
        self.lock = threading.Lock()
        self.last_size: tuple[int, int] | None = None
        self.last_render: tuple[str, str] | None = None

        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Usage & cost", command=self._show_usage)
        menu.add_separator()
        menu.add_command(label="Quit Local Voice Flow", command=self.request_quit)
        self.canvas.bind("<Button-3>", lambda event: menu.tk_popup(event.x_root, event.y_root))
        self.canvas.bind("<Button-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.drag_origin = (0, 0)

        self._tick()

    def set_state(self, state: str, message: str = "") -> None:
        with self.lock:
            self.state = state
            self.message = message
            self.state_changed_at = time.monotonic()
            if state != "listening":
                self.audio_level = 0.0

    def set_audio_level(self, level: float) -> None:
        with self.lock:
            self.audio_level = max(0.0, min(level, 1.0))

    def request_quit(self) -> None:
        with self.lock:
            self.quit_requested = True

    def run(self) -> None:
        self.root.mainloop()

    def _tick(self) -> None:
        with self.lock:
            state = self.state
            message = self.message
            changed_at = self.state_changed_at
            level = self.audio_level
            should_quit = self.quit_requested

        if should_quit:
            self.on_quit()
            self.root.destroy()
            return

        elapsed = time.monotonic() - changed_at
        if state == "success" and elapsed > 1.2:
            self.set_state("idle")
            state = "idle"
        elif state == "error" and elapsed > 4.0:
            self.set_state("idle")
            state = "idle"

        size = IDLE_SIZE if state == "idle" else ACTIVE_SIZE
        self._set_size(size)
        render_key = (state, message)
        if state in {"listening", "transcribing"} or render_key != self.last_render:
            self.last_render = render_key
            self.canvas.delete("all")
            radius = 28 if state == "idle" else 24
            self._rounded_rectangle(4, 6, size[0] - 1, size[1] - 1, radius, "#07080c")
            self._rounded_rectangle(1, 1, size[0] - 4, size[1] - 4, radius, BORDER)
            self._rounded_rectangle(2, 2, size[0] - 5, size[1] - 5, radius - 1, BACKGROUND)

            if state == "idle":
                self._draw_voice_mark(27, 28)
            elif state == "listening":
                self._draw_listening(level, elapsed)
            elif state == "transcribing":
                self._draw_transcribing(elapsed)
            elif state == "success":
                self._draw_status("✓", "Pasted", ACCENT)
            else:
                self._draw_status("!", message or "Something went wrong", ERROR)

        delay = 50 if state in {"listening", "transcribing"} else 250
        self.root.after(delay, self._tick)

    def _draw_listening(self, level: float, elapsed: float) -> None:
        self.canvas.create_oval(20, 19, 29, 28, fill=ACCENT, outline="")
        self.canvas.create_text(
            40,
            23,
            text="Listening",
            fill=FOREGROUND,
            anchor="w",
            font=("Segoe UI Variable Display", 12, "bold"),
        )
        self.canvas.create_text(
            20,
            49,
            text="Ctrl + Win to finish",
            fill=MUTED,
            anchor="w",
            font=("Segoe UI Variable Text", 9),
        )

        self.display_level = max(level, self.display_level * 0.76)
        center_y = 35
        colors = ("#a3a3a3", "#b8b8b8", ACCENT, "#e5e5e5", ACCENT_ALT)
        for index in range(11):
            phase = elapsed * 9 + index * 0.68
            motion = 0.45 + 0.55 * abs(math.sin(phase))
            height = 4 + 31 * min(1.0, self.display_level * 3.2) * motion
            x = 174 + index * 8
            self.canvas.create_line(
                x,
                center_y - height / 2,
                x,
                center_y + height / 2,
                fill=colors[min(index, 10 - index, 4)],
                width=3,
                capstyle=tk.ROUND,
            )

    def _draw_transcribing(self, elapsed: float) -> None:
        self.canvas.create_text(
            22,
            27,
            text="Transcribing",
            fill=FOREGROUND,
            anchor="w",
            font=("Segoe UI Variable Display", 12, "bold"),
        )
        self.canvas.create_text(
            22,
            49,
            text="Turning speech into text",
            fill=MUTED,
            anchor="w",
            font=("Segoe UI Variable Text", 9),
        )
        self.canvas.create_arc(
            235,
            20,
            267,
            52,
            start=-elapsed * 280,
            extent=255,
            style=tk.ARC,
            outline=ACCENT_ALT,
            width=3,
        )

    def _draw_status(self, symbol: str, text: str, color: str) -> None:
        self.canvas.create_oval(18, 18, 54, 54, fill=color, outline="")
        self.canvas.create_text(
            36,
            36,
            text=symbol,
            fill=BACKGROUND,
            font=("Segoe UI Variable Display", 16, "bold"),
        )
        self.canvas.create_text(
            68,
            36,
            text=text[:24],
            fill=FOREGROUND,
            anchor="w",
            font=("Segoe UI Variable Display", 11, "bold"),
        )

    def _draw_voice_mark(self, x: int, y: int) -> None:
        self.canvas.create_oval(x - 18, y - 18, x + 18, y + 18, fill=SURFACE, outline="")
        heights = (10, 21, 29, 17, 8)
        colors = ("#a3a3a3", "#c2c2c2", ACCENT_ALT, "#d8d8d8", ACCENT)
        for index, height in enumerate(heights):
            bar_x = x - 12 + index * 6
            self.canvas.create_line(
                bar_x,
                y - height / 2,
                bar_x,
                y + height / 2,
                fill=colors[index],
                width=3,
                capstyle=tk.ROUND,
            )
        self.canvas.create_oval(44, 9, 50, 15, fill=ACCENT_ALT, outline="")

    def _set_size(self, size: tuple[int, int]) -> None:
        if size == self.last_size:
            return
        self.last_size = size
        width, height = size
        work_area = Rect()
        ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(work_area), 0)
        x = work_area.right - width - 22
        y = work_area.bottom - height - 18
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.canvas.configure(width=width, height=height)

    def _rounded_rectangle(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        radius: int,
        color: str,
    ) -> None:
        self.canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=color, outline="")
        self.canvas.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=color, outline="")
        self.canvas.create_oval(x1, y1, x1 + radius * 2, y1 + radius * 2, fill=color, outline="")
        self.canvas.create_oval(x2 - radius * 2, y1, x2, y1 + radius * 2, fill=color, outline="")
        self.canvas.create_oval(x1, y2 - radius * 2, x1 + radius * 2, y2, fill=color, outline="")
        self.canvas.create_oval(x2 - radius * 2, y2 - radius * 2, x2, y2, fill=color, outline="")

    def _start_drag(self, event) -> None:
        self.drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event) -> None:
        x = event.x_root - self.drag_origin[0]
        y = event.y_root - self.drag_origin[1]
        self.root.geometry(f"+{x}+{y}")

    def _show_usage(self) -> None:
        messagebox.showinfo("Local Voice Flow usage", self.usage_summary(), parent=self.root)
