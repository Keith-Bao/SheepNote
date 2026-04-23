"""
SheepNote — 桌面便签小组件 v3
架构：一个隐藏的 tk.Tk 主进程 + 多个 tk.Toplevel 便签窗口
"""
import colorsys
import tkinter as tk
from tkinter import ttk
import atexit, ctypes, json, os, sys

# ── 路径（兼容 PyInstaller）────────────────────────────────────────
if getattr(sys, "frozen", False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(_BASE, "notes_data.json")

# ── 单实例 Mutex + IPC 唤醒事件 ───────────────────────────────────
_MUTEX      = "StickyNoteApp_v3_SingleInstance"
_SHOW_EVENT = "StickyNoteApp_v3_ShowAll"

def _single_instance() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX)
    if ctypes.windll.kernel32.GetLastError() == 183:
        ev = ctypes.windll.kernel32.OpenEventW(0x0002, False, _SHOW_EVENT)
        if ev:
            ctypes.windll.kernel32.SetEvent(ev)
            ctypes.windll.kernel32.CloseHandle(ev)
        return False
    return True

# ── 全局常量 ──────────────────────────────────────────────────────
BG_NOTE    = "#FFF9C4"
FG_TASK    = "#2D2D2D"
FG_DONE    = "#AAAAAA"
FG_HINT    = "#CCCCCC"
ACCENT     = "#3949AB"

FS_DEF, FS_MIN, FS_MAX = 11, 9, 18
AL_DEF, AL_MIN          = 1.0, 0.3
FONT_CB   = ("Segoe UI Symbol", 14)
FONT_BOLD = ("Microsoft YaHei", 11, "bold")

# ── 便签预设颜色 + 对应工具栏色 ──────────────────────────────────
NOTE_COLORS = [
    ("#FFF9C4", "暖黄"),
    ("#DBEAFE", "天蓝"),
    ("#DCFCE7", "薄荷"),
    ("#FFE4E8", "樱粉"),
    ("#F3E8FF", "薰衣草"),
]
# 预设便签色 → 工具栏色（手工调优）
_PRESET_TB = {
    "#fff9c4": "#F9A825",
    "#dbeafe": "#2563EB",
    "#dcfce7": "#16A34A",
    "#ffe4e8": "#E11D48",
    "#f3e8ff": "#9333EA",
}


# ════════════════════════════════════════════════════════════════════
class App:
    """管理所有便签窗口的主进程。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("SheepNote")
        self.notes: list[StickyNote] = []

        self._show_ev = ctypes.windll.kernel32.CreateEventW(
            None, False, False, _SHOW_EVENT)

        data      = self._read()
        note_list = data.get("notes", [])
        for nd in (note_list or [{}]):
            self._open(nd)

        atexit.register(self.save)
        self._poll_show_event()

    def _poll_show_event(self):
        if ctypes.windll.kernel32.WaitForSingleObject(self._show_ev, 0) == 0:
            self.show_all()
        self.root.after(500, self._poll_show_event)

    def _open(self, data: dict = None):
        offset = len(self.notes) * 28
        note   = StickyNote(self.root, data or {}, self, offset)
        self.notes.append(note)

    def new_note(self):
        self._open({})
        self.save()

    def show_all(self):
        for note in self.notes:
            note.win.deiconify()
        self.save()

    def hide_all(self):
        self.save()
        for note in self.notes:
            note.win.withdraw()

    def delete_note(self, note: "StickyNote"):
        if note in self.notes:
            self.notes.remove(note)
        self.save()
        note.win.destroy()
        if not self.notes:
            self.root.destroy()

    def save(self):
        data = {"notes": [n.snapshot() for n in self.notes]}
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _read(self) -> dict:
        if not os.path.exists(DATA_FILE):
            return {}
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def run(self):
        self.root.mainloop()


# ════════════════════════════════════════════════════════════════════
class StickyNote:
    """单个便签窗口（tk.Toplevel）。"""

    def __init__(self, master: tk.Tk, data: dict, app: App, offset: int = 0):
        self.app  = app
        self.win  = tk.Toplevel(master)
        self.win.title("SheepNote")
        self.win.overrideredirect(True)

        self._dx = self._dy = 0
        self._rsx = self._rsy = self._rsw = self._rsh = 0

        self.tasks:    list[dict] = data.get("tasks",    [])
        self._topmost: bool  = data.get("topmost",  False)
        self._fs:      int   = data.get("font_size", FS_DEF)
        self._alpha:   float = data.get("alpha",     AL_DEF)
        self._bg:      str   = data.get("color",     BG_NOTE)
        self._locked:  bool  = False
        self._saved_geo = data
        self._offset    = offset

        # 计算派生色（hover、工具栏）
        self._bghv = self._tbg = self._tbfg = self._tbsep = ""
        self._compute_derived_colors()

        # 工具栏 widget 引用列表（用于换色）
        self._tb_widgets: list[tk.Widget] = []

        # 弹窗引用
        self._new_entry:   tk.Entry    | None = None
        self._new_cb:      tk.Label    | None = None
        self._fs_popup:    tk.Toplevel | None = None
        self._al_popup:    tk.Toplevel | None = None
        self._color_popup: tk.Toplevel | None = None
        self._list_popup:  tk.Toplevel | None = None

        self.win.configure(bg=self._bg)
        self.win.attributes("-topmost", self._topmost)
        self.win.attributes("-alpha",   self._alpha)

        self._build()
        self._refresh()
        self._apply_geo()

    # ── 颜色计算 ──────────────────────────────────────────────────
    def _compute_derived_colors(self):
        """根据 _bg 计算 hover 色、工具栏色、工具栏文字色、分隔线色。"""
        h  = self._bg.lstrip('#')
        r8 = int(h[0:2], 16)
        g8 = int(h[2:4], 16)
        b8 = int(h[4:6], 16)

        # hover：略深 8%
        self._bghv = "#{:02x}{:02x}{:02x}".format(
            max(0, int(r8 * 0.92)),
            max(0, int(g8 * 0.92)),
            max(0, int(b8 * 0.92)),
        )

        # 工具栏色：预设直接查表，自定义用 HSV 推算
        lookup = _PRESET_TB.get(self._bg.lower())
        if lookup:
            self._tbg = lookup
        else:
            hue, sat, val = colorsys.rgb_to_hsv(r8/255, g8/255, b8/255)
            new_s = min(1.0, sat * 3.2 + 0.40)
            new_v = max(0.45, val * 0.64)
            nr, ng, nb = colorsys.hsv_to_rgb(hue, new_s, new_v)
            self._tbg = "#{:02x}{:02x}{:02x}".format(
                int(nr*255), int(ng*255), int(nb*255))

        # 工具栏文字：根据亮度选黑/白
        th = self._tbg.lstrip('#')
        tr, tg, tb = int(th[0:2], 16), int(th[2:4], 16), int(th[4:6], 16)
        brightness = (tr*299 + tg*587 + tb*114) / 1000
        self._tbfg  = "#FFFFFF" if brightness < 155 else "#3E2723"

        # 分隔线：工具栏色提亮 25%
        self._tbsep = "#{:02x}{:02x}{:02x}".format(
            min(255, int(tr * 1.25)),
            min(255, int(tg * 1.25)),
            min(255, int(tb * 1.25)),
        )

    def _apply_tb_color(self):
        """把当前工具栏色刷新到所有工具栏 widget 上。"""
        # 折叠时保持隐藏，展开状态才刷颜色
        if self._tb_h > 0:
            self._set_tb_content_visible(True)
        # 缩放三角单独更新（Canvas polygon 不走上面的循环）
        self._rsz_canvas.itemconfig(self._rsz_tri, fill=self._tbg)

    def _set_color(self, color: str):
        self._bg = color
        self._compute_derived_colors()
        self._apply_tb_color()
        self.win.configure(bg=color)
        self._list_outer.configure(bg=color)
        self.canvas.configure(bg=color)
        self.sf.configure(bg=color)
        self._rsz_canvas.configure(bg=color)   # 三角背景跟随便签色（视觉透明）
        self._sb_canvas.configure(bg=color)    # 滚动条背景透明
        self._refresh()
        self.app.save()

    # ════════════════════════════════════════════════════════════════
    # UI 构建
    # ════════════════════════════════════════════════════════════════
    def _build(self):
        # ── 工具栏（初始隐藏，hover 时滑出）───────────────────────────
        self.tb = tk.Frame(self.win, bg=self._tbg, height=0)
        self.tb.pack(fill=tk.X)
        self.tb.pack_propagate(False)
        self._tb_h        = 0     # 当前动画高度
        self._tb_anim_id  = None  # after id: 动画帧
        self._tb_hide_id  = None  # after id: 延迟隐藏

        self.title_lbl = tk.Label(
            self.tb, text="⠿  SheepNote",
            bg=self._tbg, fg=self._tbfg, font=FONT_BOLD, cursor="fleur"
        )
        self.title_lbl.pack(side=tk.LEFT, padx=(8, 2))
        self._tb_widgets.append(self.title_lbl)

        self.list_btn = self._tbtn("📋", self._toggle_list_popup, hover="#E65100")
        self.list_btn.pack(side=tk.LEFT, padx=2)

        nb = self._tbtn("＋", self.app.new_note, hover="#43A047")
        nb.pack(side=tk.LEFT, padx=2)

        # 右侧
        self.rbar = tk.Frame(self.tb, bg=self._tbg)
        self.rbar.pack(side=tk.RIGHT, padx=4)

        self._tbtn("×", self.app.hide_all, hover="#E53935", parent=self.rbar).pack(
            side=tk.RIGHT, padx=1)

        self.lock_btn = self._tbtn("🔒", self._toggle_lock, hover=ACCENT,
                                   parent=self.rbar)
        self.lock_btn.pack(side=tk.RIGHT, padx=1)

        self.pin_btn = self._tbtn("📍" if self._topmost else "📌",
                                  self._toggle_topmost, hover="#F57F17",
                                  parent=self.rbar)
        self.pin_btn.pack(side=tk.RIGHT, padx=1)

        self._sep()

        self.color_btn = self._tbtn("🎨", self._toggle_color_popup,
                                    hover="#FB8C00", parent=self.rbar)
        self.color_btn.pack(side=tk.RIGHT, padx=1)

        self._sep()

        self.al_btn = self._tbtn("◑", self._toggle_alpha_popup,
                                 hover="#5C6BC0", parent=self.rbar)
        self.al_btn.pack(side=tk.RIGHT, padx=1)

        self._sep()

        self.fs_btn = self._tbtn("A", self._toggle_fs_popup,
                                 hover="#00897B", parent=self.rbar)
        self.fs_btn.pack(side=tk.RIGHT, padx=1)

        for w in (self.tb, self.title_lbl):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>",     self._drag_move)

        # ── 任务区 ─────────────────────────────────────────────────
        self._list_outer = tk.Frame(self.win, bg=self._bg)
        self._list_outer.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self._list_outer, bg=self._bg,
                                highlightthickness=0)
        self.sf = tk.Frame(self.canvas, bg=self._bg)

        self.sf.bind("<Configure>",
                     lambda e: self.canvas.configure(
                         scrollregion=self.canvas.bbox("all")))
        self._cwin = self.canvas.create_window((0, 0), window=self.sf,
                                               anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_yscroll)
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(
                             self._cwin, width=e.width))
        self.canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._ctx = tk.Menu(self.win, tearoff=0)
        self._ctx.add_command(label="🗑  清除已完成", command=self._clear_done)
        self._ctx.add_separator()
        self._ctx.add_command(label="🗑  删除此便签",
                              command=lambda: self.app.delete_note(self))
        self.canvas.bind("<Button-3>",
                         lambda e: self._ctx.tk_popup(e.x_root, e.y_root))
        self.sf.bind("<Button-3>",
                     lambda e: self._ctx.tk_popup(e.x_root, e.y_root))

        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Apple 风格悬浮滚动条（覆盖在右侧，滚动时显示）
        self._sb_canvas = tk.Canvas(
            self._list_outer, width=10, bg=self._bg,
            highlightthickness=0, bd=0
        )
        self._sb_hide_id: str | None = None

        # ── 右下角常驻缩放三角（无背景 + 半透明，浮层始终可见）──
        self._rsz_canvas = tk.Canvas(
            self.win, width=18, height=18,
            bg=self._bg, highlightthickness=0, bd=0, cursor="sizing"
        )
        self._rsz_canvas.place(relx=1.0, rely=1.0, anchor="se")
        self._rsz_tri = self._rsz_canvas.create_polygon(
            0, 18, 18, 18, 18, 0,
            fill=self._tbg, outline="", stipple="gray50"
        )
        self._rsz_canvas.bind("<ButtonPress-1>", self._resize_start)
        self._rsz_canvas.bind("<B1-Motion>",     self._resize_move)

        # 绑定 hover 显示/隐藏工具栏
        self._bind_hover()

    # ── 工具栏按钮工厂（toolbar 专用）────────────────────────────
    def _tbtn(self, text, cmd, hover=None, parent=None) -> tk.Label:
        p   = parent if parent is not None else self.tb
        lbl = tk.Label(p, text=text, bg=self._tbg, fg=self._tbfg,
                       font=("Microsoft YaHei", 9), cursor="hand2", bd=0)
        _hv = hover or "#F0C060"
        lbl.bind("<Button-1>", lambda e: cmd())
        lbl.bind("<Enter>",    lambda e: lbl.config(bg=_hv))
        lbl.bind("<Leave>",    lambda e: lbl.config(bg=self._tbg,
                                                     fg=self._tbfg))
        self._tb_widgets.append(lbl)
        return lbl

    def _sep(self):
        lbl = tk.Label(self.rbar, text="│", bg=self._tbg, fg=self._tbsep)
        lbl.pack(side=tk.RIGHT, padx=2)
        self._tb_widgets.append(lbl)

    # ── Apple 风格滚动条 ──────────────────────────────────────────
    def _on_yscroll(self, first: str, last: str):
        first, last = float(first), float(last)
        if first <= 0.0 and last >= 1.0:
            self._hide_scrollbar()
            return
        self._draw_scrollbar(first, last)

    def _draw_scrollbar(self, first: float, last: float):
        sc = self._sb_canvas
        sc.delete("all")
        h = sc.winfo_height()
        if h < 4:
            h = self.canvas.winfo_height()
        if h < 4:
            return
        sc.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne", x=-2)
        sc.lift()

        thumb_h = max(24, int(h * (last - first)))
        thumb_y  = int(h * first)
        w = 5
        x1, x2 = 2, 2 + w
        y1, y2  = thumb_y + 2, thumb_y + thumb_h - 2
        r = w // 2
        c = "#555555"
        if y2 - y1 > 2 * r:
            sc.create_oval(x1, y1,       x2, y1 + 2*r, fill=c, outline="")
            sc.create_rectangle(x1, y1 + r, x2, y2 - r, fill=c, outline="")
            sc.create_oval(x1, y2 - 2*r, x2, y2,       fill=c, outline="")
        else:
            sc.create_oval(x1, y1, x2, max(y2, y1 + 2*r), fill=c, outline="")

        if self._sb_hide_id:
            sc.after_cancel(self._sb_hide_id)
        self._sb_hide_id = sc.after(1200, self._hide_scrollbar)

    def _hide_scrollbar(self):
        self._sb_canvas.place_forget()
        self._sb_hide_id = None

    # ── 工具栏 hover 显示 / 隐藏 ─────────────────────────────────
    def _bind_hover(self):
        """给所有主要区域绑定 Enter/Leave，实现 hover 显示工具栏。"""
        def on_enter(e):
            if self._tb_hide_id:
                self.win.after_cancel(self._tb_hide_id)
                self._tb_hide_id = None
            self._animate_tb(True)

        def on_leave(e):
            # 检查鼠标是否真的离开了窗口边界（而非在子控件间移动）
            try:
                wx = self.win.winfo_rootx()
                wy = self.win.winfo_rooty()
                ww = self.win.winfo_width()
                wh = self.win.winfo_height()
                if wx <= e.x_root <= wx + ww and wy <= e.y_root <= wy + wh:
                    return
            except Exception:
                return
            if self._tb_hide_id:
                self.win.after_cancel(self._tb_hide_id)
            self._tb_hide_id = self.win.after(
                350, lambda: self._animate_tb(False))

        targets = [self.win, self._list_outer, self.canvas,
                   self.sf, self.tb, self._rsz_canvas]
        targets += self._tb_widgets
        for w in targets:
            try:
                w.bind("<Enter>", on_enter, add="+")
                w.bind("<Leave>", on_leave, add="+")
            except Exception:
                pass

    def _animate_tb(self, show: bool):
        """启动工具栏滑入 / 滑出动画。"""
        if self._tb_anim_id:
            self.win.after_cancel(self._tb_anim_id)
            self._tb_anim_id = None
        target = 34 if show else 0
        if self._tb_h == target:
            return
        if not show:
            # 折叠时立即抹去所有颜色和文字，防止缩动过程中露出色条
            self._set_tb_content_visible(False)
        self._tb_step(target)

    def _tb_step(self, target: int):
        was_zero = (self._tb_h == 0)
        step = 5
        if target > self._tb_h:
            self._tb_h = min(target, self._tb_h + step)
            if was_zero:
                # 展开第一帧：先恢复颜色，再让高度可见
                self._set_tb_content_visible(True)
        else:
            self._tb_h = max(target, self._tb_h - step)
        try:
            self.tb.config(height=self._tb_h)
        except Exception:
            return
        if self._tb_h != target:
            self._tb_anim_id = self.win.after(
                10, lambda: self._tb_step(target))

    def _set_tb_content_visible(self, visible: bool):
        """把工具栏所有控件颜色切换为可见/隐藏（不改变高度）。"""
        if visible:
            self.tb.config(bg=self._tbg)
            self.rbar.config(bg=self._tbg)
            for w in self._tb_widgets:
                try:
                    txt = w.cget("text")
                    w.config(bg=self._tbg,
                             fg=self._tbsep if txt == "│" else self._tbfg)
                except Exception:
                    pass
        else:
            bg = self._bg
            self.tb.config(bg=bg)
            self.rbar.config(bg=bg)
            for w in self._tb_widgets:
                try:
                    w.config(bg=bg, fg=bg)
                except Exception:
                    pass

    # ════════════════════════════════════════════════════════════════
    # 弹出面板通用系统
    # ════════════════════════════════════════════════════════════════
    def _monitor_workarea(self) -> tuple:
        """返回当前便签窗口所在显示器的工作区 (left, top, right, bottom)。"""
        try:
            class RECT(ctypes.Structure):
                _fields_ = [("left",  ctypes.c_long), ("top",    ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize",    ctypes.c_ulong),
                            ("rcMonitor", RECT), ("rcWork", RECT),
                            ("dwFlags",   ctypes.c_ulong)]
            hwnd = self.win.winfo_id()
            hm   = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)
            mi   = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            ctypes.windll.user32.GetMonitorInfoW(hm, ctypes.byref(mi))
            r = mi.rcWork
            return r.left, r.top, r.right, r.bottom
        except Exception:
            return (0, 0,
                    self.win.winfo_screenwidth(),
                    self.win.winfo_screenheight())

    def _open_popup(self, anchor: tk.Widget, attr: str, build_fn) -> None:
        existing = getattr(self, attr, None)
        if existing:
            try:
                if existing.winfo_exists():
                    existing.destroy()
            except Exception:
                pass
            setattr(self, attr, None)
            return

        popup = tk.Toplevel(self.win)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg="#E0E0E0")
        setattr(self, attr, popup)

        def _on_destroy(e):
            if getattr(self, attr, None) is popup:
                setattr(self, attr, None)
        popup.bind("<Destroy>", _on_destroy)

        card = tk.Frame(popup, bg="#FFFFFF", padx=16, pady=14)
        card.pack(padx=1, pady=1, fill=tk.BOTH, expand=True)
        build_fn(card)

        # 覆盖整个虚拟桌面（兼容多显示器）
        u32 = ctypes.windll.user32
        vx = u32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        vy = u32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
        vw = u32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        vh = u32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
        overlay = tk.Toplevel(self.win)
        overlay.overrideredirect(True)
        overlay.configure(bg="black")
        overlay.attributes("-alpha", 0.01)
        overlay.attributes("-topmost", False)
        overlay.geometry(f"{vw}x{vh}+{vx}+{vy}")
        overlay.lower(popup)

        def _close():
            try:
                if overlay.winfo_exists(): overlay.destroy()
            except Exception: pass
            try:
                if popup.winfo_exists(): popup.destroy()
            except Exception: pass

        overlay.bind("<Button-1>", lambda e: _close())
        popup.bind("<Destroy>",
                   lambda e: overlay.destroy() if overlay.winfo_exists() else None,
                   add="+")

        popup.update_idletasks()
        pw = popup.winfo_reqwidth()
        ph = popup.winfo_reqheight()
        bx = anchor.winfo_rootx()
        by = anchor.winfo_rooty() + anchor.winfo_height() + 4
        # 在当前显示器工作区内 clamp（修复跨屏幕弹窗错位）
        ml, mt, mr, mb = self._monitor_workarea()
        bx = max(ml, min(bx, mr - pw - 6))
        by = max(mt, min(by, mb - ph - 6))
        popup.geometry(f"{pw}x{ph}+{bx}+{by}")
        popup.lift()

    # ── 字号弹出 ──────────────────────────────────────────────────
    def _toggle_fs_popup(self):
        def build(card):
            tk.Label(card, text="字体大小", bg="#FFFFFF", fg="#9E9E9E",
                     font=("Microsoft YaHei", 8)).pack(anchor="w")
            val_lbl = tk.Label(card, text=str(self._fs), bg="#FFFFFF",
                               fg="#212121",
                               font=("Microsoft YaHei", 26, "bold"), width=3)
            val_lbl.pack(pady=(4, 6))
            rng = tk.Frame(card, bg="#FFFFFF"); rng.pack(fill=tk.X)
            tk.Label(rng, text=f"A  {FS_MIN}pt", bg="#FFFFFF", fg="#BDBDBD",
                     font=("Microsoft YaHei", 8)).pack(side=tk.LEFT)
            tk.Label(rng, text=f"{FS_MAX}pt  A", bg="#FFFFFF", fg="#BDBDBD",
                     font=("Microsoft YaHei", 8)).pack(side=tk.RIGHT)
            var = tk.IntVar(value=self._fs)
            def on_change(v):
                nv = int(float(v))
                if nv != self._fs:
                    self._fs = nv; val_lbl.config(text=str(nv))
                    self._refresh(); self.app.save()
            ttk.Scale(card, from_=FS_MIN, to=FS_MAX, orient=tk.HORIZONTAL,
                      length=180, variable=var,
                      command=on_change).pack(pady=(2, 0))
        self._open_popup(self.fs_btn, "_fs_popup", build)

    # ── 透明度弹出 ────────────────────────────────────────────────
    def _toggle_alpha_popup(self):
        def build(card):
            tk.Label(card, text="便签透明度", bg="#FFFFFF", fg="#9E9E9E",
                     font=("Microsoft YaHei", 8)).pack(anchor="w")
            val_lbl = tk.Label(card, text=f"{int(self._alpha*100)}%",
                               bg="#FFFFFF", fg="#212121",
                               font=("Microsoft YaHei", 26, "bold"), width=4)
            val_lbl.pack(pady=(4, 6))
            rng = tk.Frame(card, bg="#FFFFFF"); rng.pack(fill=tk.X)
            tk.Label(rng, text=f"{int(AL_MIN*100)}%", bg="#FFFFFF",
                     fg="#BDBDBD",
                     font=("Microsoft YaHei", 8)).pack(side=tk.LEFT)
            tk.Label(rng, text="100%", bg="#FFFFFF", fg="#BDBDBD",
                     font=("Microsoft YaHei", 8)).pack(side=tk.RIGHT)
            var = tk.IntVar(value=int(self._alpha*100))
            def on_change(v):
                nv_pct = int(float(v))
                nv = max(AL_MIN, round(nv_pct/100, 2))
                if nv != self._alpha:
                    self._alpha = nv; val_lbl.config(text=f"{nv_pct}%")
                    self.win.attributes("-alpha", nv); self.app.save()
            ttk.Scale(card, from_=int(AL_MIN*100), to=100,
                      orient=tk.HORIZONTAL, length=180, variable=var,
                      command=on_change).pack(pady=(2, 0))
        self._open_popup(self.al_btn, "_al_popup", build)

    # ── 颜色弹出 ──────────────────────────────────────────────────
    def _toggle_color_popup(self):
        def build(card):
            tk.Label(card, text="便签颜色", bg="#FFFFFF", fg="#9E9E9E",
                     font=("Microsoft YaHei", 8)).pack(anchor="w",
                                                       pady=(0, 10))
            row = tk.Frame(card, bg="#FFFFFF"); row.pack()

            for hex_col, name in NOTE_COLORS:
                cf = tk.Frame(row, bg="#FFFFFF", cursor="hand2")
                cf.pack(side=tk.LEFT, padx=5)
                selected = self._bg.lower() == hex_col.lower()
                outer_bd = tk.Frame(
                    cf,
                    bg="#333333" if selected else "#DDDDDD",
                    padx=2 if selected else 1,
                    pady=2 if selected else 1,
                    cursor="hand2"
                )
                outer_bd.pack()
                swatch = tk.Label(outer_bd, bg=hex_col, width=4, height=2,
                                  cursor="hand2")
                swatch.pack()
                tk.Label(cf, text="✓" if selected else name,
                         bg="#FFFFFF",
                         fg="#333333" if selected else "#9E9E9E",
                         font=("Microsoft YaHei", 7)).pack()

                def _pick(e, c=hex_col):
                    self._set_color(c)
                    p = getattr(self, "_color_popup", None)
                    if p:
                        try: p.destroy()
                        except Exception: pass

                for w in (swatch, outer_bd, cf):
                    w.bind("<Button-1>", _pick)
                swatch.bind("<Enter>",
                            lambda e, f=outer_bd: f.config(bg="#555555"))
                swatch.bind("<Leave>",
                            lambda e, f=outer_bd, sel=selected:
                            f.config(bg="#333333" if sel else "#DDDDDD"))

            tk.Frame(card, bg="#F0F0F0", height=1).pack(
                fill=tk.X, pady=(12, 8))

            def open_picker():
                from tkinter.colorchooser import askcolor
                result = askcolor(color=self._bg, title="选择便签颜色",
                                  parent=self.win)
                if result[1]:
                    self._set_color(result[1])
                    p = getattr(self, "_color_popup", None)
                    if p:
                        try: p.destroy()
                        except Exception: pass

            custom_f = tk.Frame(card, bg="#F7F7F7", cursor="hand2")
            custom_f.pack(fill=tk.X)
            custom_lbl = tk.Label(custom_f, text="🎨  自定义颜色…",
                                  bg="#F7F7F7", fg="#424242",
                                  font=("Microsoft YaHei", 9), pady=7)
            custom_lbl.pack()
            for w in (custom_f, custom_lbl):
                w.bind("<Button-1>", lambda e: open_picker())
                w.bind("<Enter>", lambda e: custom_f.config(bg="#EEEEEE"))
                w.bind("<Leave>", lambda e: custom_f.config(bg="#F7F7F7"))

        self._open_popup(self.color_btn, "_color_popup", build)

    # ── 便签列表弹出 ──────────────────────────────────────────────
    @staticmethod
    def _note_label(idx: int, note: "StickyNote") -> str:
        for t in note.tasks:
            text = t["text"].strip()
            if text:
                return text[:20] + ("…" if len(text) > 20 else "")
        return f"便签 {idx + 1}"

    def _toggle_list_popup(self):
        def build(card):
            notes = self.app.notes
            hdr = tk.Frame(card, bg="#FFFFFF"); hdr.pack(fill=tk.X, pady=(0,10))
            tk.Label(hdr, text="便签列表", bg="#FFFFFF", fg="#424242",
                     font=("Microsoft YaHei", 11, "bold")).pack(side=tk.LEFT)
            tk.Label(hdr, text=f"{len(notes)} 个", bg="#FFFFFF", fg="#9E9E9E",
                     font=("Microsoft YaHei", 9)).pack(side=tk.RIGHT, pady=2)
            for i, note in enumerate(notes):
                self._list_row(card, i, note)
            tk.Frame(card, bg="#F0F0F0", height=1).pack(fill=tk.X,
                                                         pady=(10, 6))
            new_f = tk.Frame(card, bg="#F7F7F7", cursor="hand2")
            new_f.pack(fill=tk.X)
            new_lbl = tk.Label(new_f, text="＋  新建便签", bg="#F7F7F7",
                               fg="#2E7D32",
                               font=("Microsoft YaHei", 10), pady=7)
            new_lbl.pack()

            def _new():
                self.app.new_note()
                p = getattr(self, "_list_popup", None)
                if p:
                    try: p.destroy()
                    except Exception: pass

            for w in (new_f, new_lbl):
                w.bind("<Button-1>", lambda e: _new())
                w.bind("<Enter>", lambda e: new_f.config(bg="#E8F5E9"))
                w.bind("<Leave>", lambda e: new_f.config(bg="#F7F7F7"))

        self._open_popup(self.list_btn, "_list_popup", build)

    def _list_row(self, parent, idx: int, note: "StickyNote"):
        visible    = note.win.state() != "withdrawn"
        task_count = len(note.tasks)
        done_count = sum(1 for t in note.tasks if t["done"])
        label_text = self._note_label(idx, note)
        count_text = (f"{task_count} 个任务  ✓{done_count}"
                      if task_count else "暂无任务")
        ROW_BG  = "#FFFDE7" if visible else "#FAFAFA"
        ROW_HOV = "#FFF9C4" if visible else "#F0F0F0"

        row    = tk.Frame(parent, bg=ROW_BG, cursor="arrow")
        row.pack(fill=tk.X, pady=2)
        border = tk.Frame(row, bg=note._tbg if visible else "#BDBDBD", width=4)
        border.pack(side=tk.LEFT, fill=tk.Y)
        inner  = tk.Frame(row, bg=ROW_BG, padx=10, pady=8)
        inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        name_fg  = "#212121" if visible else "#9E9E9E"
        name_fnt = (("Microsoft YaHei", 10, "bold") if visible
                    else ("Microsoft YaHei", 10))
        tk.Label(inner, text=label_text, bg=ROW_BG, fg=name_fg,
                 font=name_fnt, anchor="w").pack(anchor="w")
        tk.Label(inner, text=count_text, bg=ROW_BG, fg="#BDBDBD",
                 font=("Microsoft YaHei", 8), anchor="w").pack(anchor="w")

        BTN_TXT = "● 显示" if visible else "○ 隐藏"
        BTN_BG  = note._tbg if visible else "#E0E0E0"
        BTN_FG  = note._tbfg if visible else "#9E9E9E"
        tog = tk.Label(row, text=BTN_TXT, bg=BTN_BG, fg=BTN_FG,
                       font=("Microsoft YaHei", 8), padx=8, pady=3,
                       cursor="hand2", relief="flat")
        tog.pack(side=tk.RIGHT, padx=(6, 10), pady=8)
        _vis = [visible]

        def toggle_vis():
            _vis[0] = not _vis[0]
            if _vis[0]:
                note.win.deiconify()
                row.config(bg="#FFFDE7"); border.config(bg=note._tbg)
                inner.config(bg="#FFFDE7")
                for ch in inner.winfo_children(): ch.config(bg="#FFFDE7")
                tog.config(text="● 显示", bg=note._tbg, fg=note._tbfg)
            else:
                note.win.withdraw()
                row.config(bg="#FAFAFA"); border.config(bg="#BDBDBD")
                inner.config(bg="#FAFAFA")
                for ch in inner.winfo_children(): ch.config(bg="#FAFAFA")
                tog.config(text="○ 隐藏", bg="#E0E0E0", fg="#9E9E9E")

        tog.bind("<Button-1>", lambda e: toggle_vis())
        tog.bind("<Enter>", lambda e, t=tog, v=_vis:
                 t.config(bg="#FFB300" if v[0] else "#D5D5D5"))
        tog.bind("<Leave>", lambda e, t=tog, v=_vis:
                 t.config(bg=note._tbg if v[0] else "#E0E0E0"))

        def hl_on(e):
            row.config(bg=ROW_HOV); inner.config(bg=ROW_HOV)
            for ch in inner.winfo_children(): ch.config(bg=ROW_HOV)
        def hl_off(e):
            cur = "#FFFDE7" if _vis[0] else "#FAFAFA"
            row.config(bg=cur); inner.config(bg=cur)
            for ch in inner.winfo_children(): ch.config(bg=cur)
        for w in (row, inner):
            w.bind("<Enter>", hl_on); w.bind("<Leave>", hl_off)

        ctx = tk.Menu(parent, tearoff=0)
        ctx.add_command(label="🗑  删除此便签",
                        command=lambda n=note: self.app.delete_note(n))
        for w in (row, inner):
            w.bind("<Button-3>", lambda e: ctx.tk_popup(e.x_root, e.y_root))

    # ════════════════════════════════════════════════════════════════
    # 任务列表渲染
    # ════════════════════════════════════════════════════════════════
    def _f(self)      -> tuple: return ("Microsoft YaHei", self._fs)
    def _f_done(self) -> tuple: return ("Microsoft YaHei", self._fs, "overstrike")

    def _flush_entries(self):
        """重绘前把正在编辑的 Entry 文本同步到 self.tasks，防止内容丢失。"""
        rows = [w for w in self.sf.winfo_children() if isinstance(w, tk.Frame)]
        for i, outer in enumerate(rows):
            if i >= len(self.tasks):
                break  # 最后一行是"添加新任务"占位行，跳过
            for inner in outer.winfo_children():
                if not isinstance(inner, tk.Frame):
                    continue
                for w in inner.winfo_children():
                    if isinstance(w, tk.Entry):
                        try:
                            text = w.get().strip()
                            if text and text != "添加新任务…":
                                self.tasks[i]["text"] = text
                        except tk.TclError:
                            pass

    def _refresh(self, focus_new=False):
        self._flush_entries()           # 先保存所有正在编辑的内容
        for w in self.sf.winfo_children():
            w.destroy()
        self._new_entry = self._new_cb = None
        for i, task in enumerate(self.tasks):
            self._make_row(i, task)
        if not self._locked:
            self._new_entry = self._make_new_row()
        if focus_new and self._new_entry:
            self.win.after(30, self._new_entry.focus_set)

    def _make_row(self, idx: int, task: dict):
        done        = task["done"]
        interactive = not self._locked
        bg, bghv    = self._bg, self._bghv

        outer = tk.Frame(self.sf, bg=bg); outer.pack(fill=tk.X)
        inner = tk.Frame(outer, bg=bg, pady=4); inner.pack(fill=tk.X, padx=8)

        def hl_on(e,  o=outer, i=inner): o.config(bg=bghv); i.config(bg=bghv)
        def hl_off(e, o=outer, i=inner): o.config(bg=bg);   i.config(bg=bg)

        cb_text = "☑" if done else "☐"
        cb_fg   = "#4CAF50" if done else "#AAAAAA"
        cb = tk.Label(inner, text=cb_text, fg=cb_fg, bg=bg, font=FONT_CB,
                      cursor="hand2" if interactive else "arrow")
        cb.pack(side=tk.LEFT, padx=(0, 5))
        if interactive:
            cb.bind("<Button-1>", lambda e, i=idx: self._toggle(i))
        cb.bind("<Enter>", hl_on); cb.bind("<Leave>", hl_off)

        if done or not interactive:
            font = self._f_done() if done else self._f()
            fg   = FG_DONE if done else FG_TASK
            lbl  = tk.Label(inner, text=task["text"], bg=bg, fg=fg,
                            font=font, anchor="w", justify=tk.LEFT)
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            if interactive:
                lbl.bind("<Button-1>", lambda e, i=idx: self._toggle(i))
            lbl.bind("<Enter>", hl_on); lbl.bind("<Leave>", hl_off)
        else:
            ent = tk.Entry(inner, font=self._f(), bg=bg, relief="flat",
                           fg=FG_TASK, highlightthickness=0, bd=0,
                           insertbackground=FG_TASK)
            ent.insert(0, task["text"])
            ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
            ent.bind("<FocusOut>", lambda e, i=idx: self._save_text(i, e.widget))
            ent.bind("<Return>",   lambda e: self._focus_new())
            ent.bind("<Enter>", hl_on); ent.bind("<Leave>", hl_off)

        if interactive:
            d = tk.Label(inner, text="×", bg=bg, fg="#DDDDDD",
                         font=("Microsoft YaHei", 11), cursor="hand2")
            d.pack(side=tk.RIGHT)
            d.bind("<Button-1>", lambda e, i=idx: self._delete(i))
            d.bind("<Enter>", lambda e, b=d: b.config(fg="#E53935", bg=bghv))
            d.bind("<Leave>", lambda e, b=d: b.config(fg="#DDDDDD", bg=bg))

        inner.bind("<Enter>", hl_on); inner.bind("<Leave>", hl_off)

    def _make_new_row(self) -> tk.Entry:
        bg = self._bg
        outer = tk.Frame(self.sf, bg=bg); outer.pack(fill=tk.X)
        inner = tk.Frame(outer, bg=bg, pady=4); inner.pack(fill=tk.X, padx=8)

        self._new_cb = tk.Label(inner, text="☐", bg=bg, fg=FG_HINT,
                                font=FONT_CB)
        self._new_cb.pack(side=tk.LEFT, padx=(0, 5))

        ent = tk.Entry(inner, font=self._f(), bg=bg, relief="flat",
                       fg=FG_HINT, highlightthickness=0, bd=0,
                       insertbackground=FG_TASK)
        ent.insert(0, "添加新任务…")
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ent.bind("<FocusIn>",  lambda e: self._new_in(ent))
        ent.bind("<FocusOut>", lambda e: self._new_out(ent))
        ent.bind("<Return>",   lambda e: self._add(ent))
        return ent

    def _new_in(self, e: tk.Entry):
        if e.get() == "添加新任务…":
            e.delete(0, tk.END)
        e.config(fg=FG_TASK)
        if self._new_cb: self._new_cb.config(fg="#AAAAAA")

    def _new_out(self, e: tk.Entry):
        if not e.get().strip():
            e.delete(0, tk.END); e.insert(0, "添加新任务…"); e.config(fg=FG_HINT)
            if self._new_cb: self._new_cb.config(fg=FG_HINT)

    def _focus_new(self):
        if self._new_entry: self._new_entry.focus_set()

    # ════════════════════════════════════════════════════════════════
    # 任务操作
    # ════════════════════════════════════════════════════════════════
    def _add(self, ent: tk.Entry):
        text = ent.get().strip()
        if not text or text == "添加新任务…": return
        self.tasks.append({"text": text, "done": False})
        self.app.save(); self._refresh(focus_new=True)

    def _save_text(self, idx: int, ent: tk.Entry):
        if idx >= len(self.tasks): return
        try: text = ent.get().strip()
        except tk.TclError: return
        if text:
            if self.tasks[idx]["text"] != text:
                self.tasks[idx]["text"] = text; self.app.save()
        else:
            self.win.after(
                0, lambda: self._delete(idx) if idx < len(self.tasks) else None)

    def _toggle(self, idx: int):
        self.tasks[idx]["done"] = not self.tasks[idx]["done"]
        self.app.save(); self._refresh()

    def _delete(self, idx: int):
        if idx < len(self.tasks):
            self.tasks.pop(idx); self.app.save(); self._refresh()

    def _clear_done(self):
        self.tasks = [t for t in self.tasks if not t["done"]]
        self.app.save(); self._refresh()

    # ════════════════════════════════════════════════════════════════
    # 锁定
    # ════════════════════════════════════════════════════════════════
    def _toggle_lock(self):
        self._locked = not self._locked
        if self._locked:
            self.lock_btn.config(bg=ACCENT)
            self.win.attributes("-alpha", max(AL_MIN,
                                             round(self._alpha - 0.2, 1)))
        else:
            self.lock_btn.config(bg=self._tbg)
            self.win.attributes("-alpha", self._alpha)
        self._refresh()

    # ════════════════════════════════════════════════════════════════
    # 置顶 / 拖拽 / 缩放
    # ════════════════════════════════════════════════════════════════
    def _toggle_topmost(self):
        self._topmost = not self._topmost
        self.win.attributes("-topmost", self._topmost)
        self.pin_btn.config(text="📍" if self._topmost else "📌",
                            bg=self._tbg)
        self.app.save()

    def _drag_start(self, e): self._dx, self._dy = e.x, e.y
    def _drag_move(self, e):
        x = self.win.winfo_x() + e.x - self._dx
        y = self.win.winfo_y() + e.y - self._dy
        self.win.geometry(f"+{x}+{y}")

    def _resize_start(self, e):
        self._rsx, self._rsy = e.x_root, e.y_root
        self._rsw, self._rsh = self.win.winfo_width(), self.win.winfo_height()

    def _resize_move(self, e):
        w = max(220, self._rsw + e.x_root - self._rsx)
        h = max(150, self._rsh + e.y_root - self._rsy)
        self.win.geometry(f"{w}x{h}")

    # ════════════════════════════════════════════════════════════════
    # 几何 / 快照
    # ════════════════════════════════════════════════════════════════
    def _apply_geo(self):
        d  = self._saved_geo
        w  = d.get("w", 290)
        h  = d.get("h", 430)
        sw = self.win.winfo_screenwidth()
        x  = d.get("x", sw - w - 20) + self._offset
        y  = d.get("y", 60)          + self._offset
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def snapshot(self) -> dict:
        return {
            "tasks":     self.tasks,
            "x":         self.win.winfo_x(),
            "y":         self.win.winfo_y(),
            "w":         self.win.winfo_width(),
            "h":         self.win.winfo_height(),
            "topmost":   self._topmost,
            "font_size": self._fs,
            "alpha":     self._alpha,
            "color":     self._bg,
        }


# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not _single_instance():
        sys.exit(0)
    App().run()
