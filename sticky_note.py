"""
SheepNote — 桌面便签小组件 v4.5
Apple HIG 全面优化：
  P0 数据安全  : 删除便签/清除已完成加确认；任务删除支持 3s Undo Toast
  P1 核心体验  : Escape 关闭弹窗 / Ctrl+N 新建 / 统一 Token / FG_HINT 对比度修复
  P2 视觉一致  : 圆角 / DWM 投影 / ease-out 动画 / 锁定左侧色条
  P3 精细打磨  : 最小字号调整 / 弹窗字体统一 / 间距网格化
  v4.1 修复   : 滚轮泄漏 / Mutex 释放 / Toast 状态机 / 托盘线程同步 /
               _refresh 防抖 / 确认框崩溃 / pending-delete 并发 /
               列表弹窗状态 / HWND 校验 / 删除时资源清理
  v4.2 新增   : 锁定按钮移至左下角(hover显示) / 工具栏常驻 / 任务可换行
               托盘图标内嵌 / 任务栏隐藏 / 边缘自动收缩
  v4.5 新增   : Apple iOS 样式滑块开关（边缘收缩 / 开机自启）
               开机自动启动选项（写入注册表 Run 键）
               修复托盘图标按 SM_CXSMICON 精确加载
               清理死代码（未使用弹窗属性、常量、pill_frame）
  跨平台      : Windows (Win32 原生) / macOS (pystray + socket IPC)
"""
_VERSION = "4.5"
import colorsys
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkFont
import atexit, ctypes, json, os, sys, threading

_IS_WIN = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"

if _IS_WIN:
    from ctypes import wintypes

# ── 路径（兼容 PyInstaller）────────────────────────────────────────
if getattr(sys, "frozen", False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(_BASE, "notes_data.json")

# ════════════════════════════════════════════════════════════════════
# 单实例 + IPC（平台分支）
# ════════════════════════════════════════════════════════════════════

# ── Windows：Mutex + Named Event ──────────────────────────────────
_MUTEX        = "StickyNoteApp_v3_SingleInstance"
_SHOW_EVENT   = "StickyNoteApp_v3_ShowAll"
_MUTEX_HANDLE: int = 0

def _single_instance() -> bool:
    global _MUTEX_HANDLE
    _MUTEX_HANDLE = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX)
    if ctypes.windll.kernel32.GetLastError() == 183:
        ev = ctypes.windll.kernel32.OpenEventW(0x0002, False, _SHOW_EVENT)
        if ev:
            ctypes.windll.kernel32.SetEvent(ev)
            ctypes.windll.kernel32.CloseHandle(ev)
        return False
    return True

def _release_mutex():
    if _MUTEX_HANDLE:
        ctypes.windll.kernel32.CloseHandle(_MUTEX_HANDLE)

if _IS_WIN:
    atexit.register(_release_mutex)

# ── macOS / Linux：Unix socket IPC ────────────────────────────────
_MAC_SOCK_PATH = "/tmp/sheepnote_v4_1.sock"
_mac_server_sock = None          # 主实例持有的监听 socket

def _single_instance_mac() -> bool:
    """返回 True 表示当前是第一个实例。"""
    global _mac_server_sock
    import socket as _sock_mod

    # 先尝试连接已有实例
    try:
        s = _sock_mod.socket(_sock_mod.AF_UNIX, _sock_mod.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(_MAC_SOCK_PATH)
        s.sendall(b"show")
        s.close()
        return False                 # 另一个实例已在运行
    except OSError:
        pass                         # 没有实例在监听

    # 清理残留 socket 文件
    try:
        os.unlink(_MAC_SOCK_PATH)
    except OSError:
        pass

    # 启动监听
    try:
        _mac_server_sock = _sock_mod.socket(_sock_mod.AF_UNIX, _sock_mod.SOCK_STREAM)
        _mac_server_sock.bind(_MAC_SOCK_PATH)
        _mac_server_sock.listen(1)
        _mac_server_sock.setblocking(False)
    except OSError:
        pass   # 无法创建 socket，宽松处理：允许启动
    return True

def _cleanup_mac_ipc():
    global _mac_server_sock
    if _mac_server_sock:
        try: _mac_server_sock.close()
        except OSError: pass
        _mac_server_sock = None
    try:
        os.unlink(_MAC_SOCK_PATH)
    except OSError:
        pass

if not _IS_WIN:
    atexit.register(_cleanup_mac_ipc)

# ════════════════════════════════════════════════════════════════════
# 多语言字符串
# ════════════════════════════════════════════════════════════════════
_LANG = ["zh"]

STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "pin": "置顶", "placeholder": "添加新任务…",
        "note_count": "{n} 个", "note_default": "便签 {n}",
        "note_tasks": "{t} 个任务 · ✓{d}", "no_tasks": "暂无任务",
        "new_note": "＋  新建便签", "list_title": "便签列表",
        "settings": "当前便签设置", "color": "颜色",
        "font_size": "字号", "opacity": "透明度", "language": "语言",
        "hide": "隐藏", "show": "显示", "delete_note_btn": "🗑",
        "toast_deleted": "已删除：{text}", "toast_cleared": "已清除 {n} 条已完成",
        "undo": "撤销", "tray_show": "显示所有便签", "tray_exit": "退出 SheepNote",
        "confirm_delete": "确定要删除这张便签吗？\n此操作不可撤销。",
        "confirm_ok": "删除", "cancel": "取消",
        "menu_clear": "🗑  清除已完成", "menu_del_note": "🗑  删除此便签",
        "menu_del_task": "🗑  删除此任务", "color_picker": "选择颜色",
    },
    "en": {
        "pin": "Pin", "placeholder": "Add a task…",
        "note_count": "{n}", "note_default": "Note {n}",
        "note_tasks": "{t} tasks · ✓{d}", "no_tasks": "No tasks",
        "new_note": "＋  New note", "list_title": "Notes",
        "settings": "Note settings", "color": "Color",
        "font_size": "Font size", "opacity": "Opacity", "language": "Language",
        "hide": "Hide", "show": "Show", "delete_note_btn": "🗑",
        "toast_deleted": "Deleted: {text}", "toast_cleared": "Cleared {n} done",
        "undo": "Undo", "tray_show": "Show all notes", "tray_exit": "Quit SheepNote",
        "confirm_delete": "Delete this note?\nThis cannot be undone.",
        "confirm_ok": "Delete", "cancel": "Cancel",
        "menu_clear": "🗑  Clear done", "menu_del_note": "🗑  Delete note",
        "menu_del_task": "🗑  Delete task", "color_picker": "Pick color",
    },
    "ja": {
        "pin": "固定", "placeholder": "タスクを追加…",
        "note_count": "{n} 件", "note_default": "メモ {n}",
        "note_tasks": "{t} 件 · ✓{d}", "no_tasks": "タスクなし",
        "new_note": "＋  新しいメモ", "list_title": "メモ一覧",
        "settings": "このメモの設定", "color": "カラー",
        "font_size": "文字サイズ", "opacity": "不透明度", "language": "言語",
        "hide": "非表示", "show": "表示", "delete_note_btn": "🗑",
        "toast_deleted": "削除済み：{text}", "toast_cleared": "{n} 件の完了を削除",
        "undo": "元に戻す", "tray_show": "全メモを表示", "tray_exit": "SheepNote を終了",
        "confirm_delete": "このメモを削除しますか？\nこの操作は取り消せません。",
        "confirm_ok": "削除", "cancel": "キャンセル",
        "menu_clear": "🗑  完了済みを削除", "menu_del_note": "🗑  このメモを削除",
        "menu_del_task": "🗑  このタスクを削除", "color_picker": "色を選択",
    },
    "de": {
        "pin": "Anpinnen", "placeholder": "Aufgabe hinzufügen…",
        "note_count": "{n}", "note_default": "Notiz {n}",
        "note_tasks": "{t} Aufgaben · ✓{d}", "no_tasks": "Keine Aufgaben",
        "new_note": "＋  Neue Notiz", "list_title": "Notizen",
        "settings": "Notizeinstellungen", "color": "Farbe",
        "font_size": "Schriftgröße", "opacity": "Transparenz", "language": "Sprache",
        "hide": "Ausblenden", "show": "Einblenden", "delete_note_btn": "🗑",
        "toast_deleted": "Gelöscht: {text}", "toast_cleared": "{n} erledigt gelöscht",
        "undo": "Rückgängig", "tray_show": "Alle Notizen anzeigen",
        "tray_exit": "SheepNote beenden",
        "confirm_delete": "Diese Notiz löschen?\nDies kann nicht rückgängig gemacht werden.",
        "confirm_ok": "Löschen", "cancel": "Abbrechen",
        "menu_clear": "🗑  Erledigte löschen", "menu_del_note": "🗑  Notiz löschen",
        "menu_del_task": "🗑  Aufgabe löschen", "color_picker": "Farbe wählen",
    },
    "fr": {
        "pin": "Épingler", "placeholder": "Ajouter une tâche…",
        "note_count": "{n}", "note_default": "Note {n}",
        "note_tasks": "{t} tâches · ✓{d}", "no_tasks": "Aucune tâche",
        "new_note": "＋  Nouvelle note", "list_title": "Notes",
        "settings": "Paramètres", "color": "Couleur",
        "font_size": "Taille", "opacity": "Opacité", "language": "Langue",
        "hide": "Masquer", "show": "Afficher", "delete_note_btn": "🗑",
        "toast_deleted": "Supprimé : {text}", "toast_cleared": "{n} terminé(s) supprimé(s)",
        "undo": "Annuler", "tray_show": "Afficher toutes les notes",
        "tray_exit": "Quitter SheepNote",
        "confirm_delete": "Supprimer cette note ?\nCette action est irréversible.",
        "confirm_ok": "Supprimer", "cancel": "Annuler",
        "menu_clear": "🗑  Effacer terminés", "menu_del_note": "🗑  Supprimer la note",
        "menu_del_task": "🗑  Supprimer la tâche", "color_picker": "Choisir couleur",
    },
    "es": {
        "pin": "Fijar", "placeholder": "Añadir tarea…",
        "note_count": "{n}", "note_default": "Nota {n}",
        "note_tasks": "{t} tareas · ✓{d}", "no_tasks": "Sin tareas",
        "new_note": "＋  Nueva nota", "list_title": "Notas",
        "settings": "Configuración", "color": "Color",
        "font_size": "Tamaño", "opacity": "Opacidad", "language": "Idioma",
        "hide": "Ocultar", "show": "Mostrar", "delete_note_btn": "🗑",
        "toast_deleted": "Eliminado: {text}", "toast_cleared": "{n} hecho(s) eliminado(s)",
        "undo": "Deshacer", "tray_show": "Mostrar todas las notas",
        "tray_exit": "Salir de SheepNote",
        "confirm_delete": "¿Eliminar esta nota?\nEsta acción no se puede deshacer.",
        "confirm_ok": "Eliminar", "cancel": "Cancelar",
        "menu_clear": "🗑  Borrar completadas", "menu_del_note": "🗑  Eliminar nota",
        "menu_del_task": "🗑  Eliminar tarea", "color_picker": "Elegir color",
    },
}

def T(key: str, **kw) -> str:
    s = STRINGS.get(_LANG[0], STRINGS["zh"]).get(key, key)
    return s.format(**kw) if kw else s

# ════════════════════════════════════════════════════════════════════
# P1: 统一颜色 Token
# ════════════════════════════════════════════════════════════════════
BG_NOTE      = "#FFF9C4"
FG_TASK      = "#2D2D2D"
FG_DONE      = "#AAAAAA"
FG_HINT      = "#999999"      # 修复：原 #CCCCCC 对比度 1.7:1 不达 WCAG AA
ACCENT       = "#3949AB"
ACCENT_LIGHT = "#7986CB"      # Undo 按钮用
COLOR_DANGER = "#E53935"
COLOR_SUCCESS= "#43A047"

# P1: 统一字体 Token（平台分支）
if _IS_MAC:
    FONT_BODY      = ("PingFang SC", 13)
    FONT_SMALL     = ("PingFang SC", 11)
    FONT_TITLE     = ("PingFang SC", 14, "bold")
    FONT_POPUP_VAL = ("PingFang SC", 24, "bold")
    FONT_CB        = ("Apple Color Emoji", 16)
else:
    FONT_BODY      = ("Microsoft YaHei", 11)
    FONT_SMALL     = ("Microsoft YaHei", 9)
    FONT_TITLE     = ("Microsoft YaHei", 12, "bold")
    FONT_POPUP_VAL = ("Microsoft YaHei", 24, "bold")
    FONT_CB        = ("Segoe UI Symbol", 14)

# P1: 统一间距 Token（4px 网格）
SP1, SP2, SP3, SP4 = 4, 8, 12, 16

FS_DEF, FS_MIN, FS_MAX = 11, 9, 18
AL_DEF, AL_MIN          = 1.0, 0.3

# Popup 专用色彩 Token
ROW_HID_BG   = "#F8F8F8"   # 隐藏便签行背景
ROW_VIS_HOV  = "#F0F4FF"   # 可见便签行 hover（淡蓝）
ROW_HID_HOV  = "#EEEEEE"   # 隐藏便签行 hover
DIVIDER      = "#EBEBEB"   # 分隔线
TAG_BG       = "#F0F0F2"   # 未选中 chip 背景
TAG_HOV      = "#E0E0E6"   # chip hover
DANGER_TINT  = "#FFF0F0"   # 删除按钮 hover 底色

# K: 时间/尺寸 Token
TB_HEIGHT      = 34    # 工具栏展开高度 px
TB_HIDE_DELAY  = 600   # 工具栏隐藏延迟 ms
SB_HIDE_DELAY  = 2500  # 滚动条隐藏延迟 ms
TOAST_DURATION = 3000  # Undo Toast 显示时长 ms

EDGE_THRESHOLD  = 8    # px：距屏幕边缘多近触发收缩
EDGE_STRIP_WIDTH = 16  # Apple 样式可见条宽度（px）
EDGE_ANIM_STEPS  = 10  # 滑动动画帧数
EDGE_ANIM_MS     = 16  # 每帧间隔（ms，共 ~160ms）

# ── 便签预设颜色 + 对应工具栏色 ──────────────────────────────────
NOTE_COLORS = [
    ("#FFF9C4", "暖黄"),
    ("#DBEAFE", "天蓝"),
    ("#DCFCE7", "薄荷"),
    ("#FFE4E8", "樱粉"),
    ("#F3E8FF", "薰衣草"),
]
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

        if _IS_WIN:
            self._show_ev     = ctypes.windll.kernel32.CreateEventW(
                None, False, False, _SHOW_EVENT)
            self._tray_hwnd:  int | None      = None
            self._tray_ready: threading.Event = threading.Event()
        else:
            self._pystray_icon = None          # macOS pystray 实例

        data      = self._read()
        self.lang = data.get("lang", "zh")
        _LANG[0]  = self.lang
        note_list = data.get("notes", [])
        for nd in (note_list or [{}]):
            self._open(nd)

        atexit.register(self.save)
        self._poll_show_event()
        self._setup_tray()

    def _poll_show_event(self):
        if _IS_WIN:
            if ctypes.windll.kernel32.WaitForSingleObject(self._show_ev, 0) == 0:
                self.show_all()
        else:
            # 非阻塞检查 Unix socket，收到 show 消息就唤醒所有便签
            if _mac_server_sock:
                import select
                try:
                    r, _, _ = select.select([_mac_server_sock], [], [], 0)
                    if r:
                        conn, _ = _mac_server_sock.accept()
                        try:
                            if conn.recv(16) == b"show":
                                self.show_all()
                        finally:
                            conn.close()
                except OSError:
                    pass
        self.root.after(500, self._poll_show_event)

    def _open(self, data: dict = None):
        is_new = not data or ("x" not in data and "y" not in data)
        offset = len(self.notes) * 28 if is_new else 0
        note   = StickyNote(self.root, data or {}, self, offset)
        self.notes.append(note)

    def new_note(self):
        self._close_list_popups()
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

    def hide_note(self, note: "StickyNote"):
        note.win.withdraw()
        self.save()

    def delete_note(self, note: "StickyNote"):
        self._close_list_popups()
        note._cleanup()                 # M: 取消 after 任务、关闭子弹窗
        if note in self.notes:
            self.notes.remove(note)
        self.save()
        note.win.destroy()
        if not self.notes:
            self.root.destroy()

    def _close_list_popups(self):
        for note in self.notes:
            p = getattr(note, "_list_popup", None)
            if p:
                try:
                    if p.winfo_exists():
                        p.destroy()
                except Exception:
                    pass

    # ── 托盘图标 ──────────────────────────────────────────────────
    def _setup_tray(self):
        if _IS_WIN:
            t = threading.Thread(target=self._tray_loop, daemon=True)
            t.start()
        else:
            self._setup_pystray()

    def _setup_pystray(self):
        """macOS / Linux 托盘（pystray + Pillow）。"""
        try:
            import pystray
            from PIL import Image as _PILImage
            icon_path = os.path.join(_BASE, "sheep.ico")
            try:
                img = _PILImage.open(icon_path).convert("RGBA")
            except Exception:
                img = _PILImage.new("RGBA", (64, 64), (87, 111, 176, 255))
            self._pystray_icon = pystray.Icon(
                "SheepNote", img, menu=self._build_pystray_menu())
            self._pystray_icon.run_detached()
        except Exception:
            pass   # pystray / Pillow 未安装，静默跳过

    def _build_pystray_menu(self):
        import pystray
        return pystray.Menu(
            pystray.MenuItem(T("tray_show"),
                             lambda *_: self.root.after(0, self.show_all)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(T("tray_exit"),
                             lambda *_: self.root.after(0, self._quit)),
        )

    def _tray_loop(self):
        WM_APP       = 0x8000
        TRAY_MSG     = WM_APP + 1
        NIM_ADD      = 0
        NIM_DELETE   = 2
        NIF_MESSAGE  = 0x1
        NIF_ICON     = 0x2
        NIF_TIP      = 0x4
        WM_LBUTTONUP      = 0x0202
        WM_LBUTTONDBLCLK  = 0x0203
        WM_RBUTTONUP      = 0x0205

        class NOTIFYICONDATA(ctypes.Structure):
            _fields_ = [
                ("cbSize",           wintypes.DWORD),
                ("hWnd",             wintypes.HWND),
                ("uID",              wintypes.UINT),
                ("uFlags",           wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon",            wintypes.HICON),
                ("szTip",            wintypes.WCHAR * 128),
            ]

        WNDPROC_TYPE = ctypes.WINFUNCTYPE(
            ctypes.c_long, wintypes.HWND, wintypes.UINT,
            wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSEX(ctypes.Structure):
            _fields_ = [
                ("cbSize",        wintypes.UINT),
                ("style",         wintypes.UINT),
                ("lpfnWndProc",   WNDPROC_TYPE),
                ("cbClsExtra",    ctypes.c_int),
                ("cbWndExtra",    ctypes.c_int),
                ("hInstance",     wintypes.HINSTANCE),
                ("hIcon",         wintypes.HICON),
                ("hCursor",       wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName",  wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm",       wintypes.HICON),
            ]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd",    wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam",  wintypes.WPARAM),
                ("lParam",  wintypes.LPARAM),
                ("time",    wintypes.DWORD),
                ("pt",      ctypes.c_long * 2),
            ]

        user32    = ctypes.windll.user32
        shell32   = ctypes.windll.shell32
        kernel32  = ctypes.windll.kernel32
        hinstance = kernel32.GetModuleHandleW(None)

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == TRAY_MSG:
                if lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self.root.after(0, self.show_all)
                elif lparam == WM_RBUTTONUP:
                    self.root.after(0, self._show_tray_menu)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_func = WNDPROC_TYPE(wndproc)
        class_name   = "SheepNoteTrayWnd"
        wc = WNDCLASSEX()
        wc.cbSize        = ctypes.sizeof(WNDCLASSEX)
        wc.lpfnWndProc   = wndproc_func
        wc.hInstance     = hinstance
        wc.lpszClassName = class_name
        user32.RegisterClassExW(ctypes.byref(wc))

        hwnd = user32.CreateWindowExW(
            0, class_name, "SheepNoteTray", 0,
            0, 0, 0, 0, None, None, hinstance, None)
        user32.ShowWindow(hwnd, 0)
        self._tray_hwnd = hwnd
        self._tray_ready.set()          # D: 通知主线程 hwnd 已就绪

        icon_path = os.path.join(_BASE, "sheep.ico")
        if os.path.exists(icon_path):
            cx    = user32.GetSystemMetrics(49)   # SM_CXSMICON
            cy    = user32.GetSystemMetrics(50)   # SM_CYSMICON
            hicon = user32.LoadImageW(None, icon_path, 1, cx, cy, 0x10)
            if not hicon:
                hicon = self._create_fallback_icon()
        else:
            hicon = self._create_fallback_icon()

        nid = NOTIFYICONDATA()
        nid.cbSize           = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd             = hwnd
        nid.uID              = 1
        nid.uFlags           = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = TRAY_MSG
        nid.hIcon            = hicon
        nid.szTip            = "SheepNote"
        self._tray_nid = nid

        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        try:
            msg = MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    def _show_tray_menu(self):
        user32 = ctypes.windll.user32

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        hmenu = user32.CreatePopupMenu()
        user32.AppendMenuW(hmenu, 0,     1001, T("tray_show"))
        user32.AppendMenuW(hmenu, 0x800, 0,    None)
        user32.AppendMenuW(hmenu, 0,     1002, T("tray_exit"))

        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        root_hwnd = self.root.winfo_id()
        user32.SetForegroundWindow(root_hwnd)
        cmd = user32.TrackPopupMenu(
            hmenu, 0x100 | 0x80 | 0x20,
            pt.x, pt.y, 0, root_hwnd, None)
        user32.DestroyMenu(hmenu)

        if cmd == 1001:
            self.show_all()
        elif cmd == 1002:
            self._quit()

    @staticmethod
    def _create_fallback_icon() -> int:
        """用 Win32 API 生成 32×32 蓝色方块图标（无需 ico 文件）。"""
        try:
            SIZE = 32
            r, g, b = 87, 111, 176   # ACCENT 蓝
            pixels   = bytes([b, g, r, 0] * SIZE * SIZE)  # BGRA × 像素数
            hbm_color = ctypes.windll.gdi32.CreateBitmap(
                SIZE, SIZE, 1, 32, ctypes.c_char_p(pixels))
            hbm_mask  = ctypes.windll.gdi32.CreateBitmap(SIZE, SIZE, 1, 1, None)

            class ICONINFO(ctypes.Structure):
                _fields_ = [("fIcon",    wintypes.BOOL),
                            ("xHotspot", wintypes.DWORD),
                            ("yHotspot", wintypes.DWORD),
                            ("hbmMask",  wintypes.HANDLE),
                            ("hbmColor", wintypes.HANDLE)]

            ii = ICONINFO()
            ii.fIcon    = True
            ii.hbmMask  = hbm_mask
            ii.hbmColor = hbm_color
            hicon = ctypes.windll.user32.CreateIconIndirect(ctypes.byref(ii))
            ctypes.windll.gdi32.DeleteObject(hbm_color)
            ctypes.windll.gdi32.DeleteObject(hbm_mask)
            return hicon or ctypes.windll.user32.LoadIconW(None, 32512)
        except Exception:
            return ctypes.windll.user32.LoadIconW(None, 32512)

    @staticmethod
    def _autostart_enabled() -> bool:
        if not _IS_WIN:
            return False
        import winreg
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Run",
                               0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(k, "SheepNote")
                return True
            except OSError:
                return False
            finally:
                winreg.CloseKey(k)
        except OSError:
            return False

    @staticmethod
    def _set_autostart(on: bool):
        if not _IS_WIN:
            return
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path,
                               0, winreg.KEY_SET_VALUE)
            if on:
                if getattr(sys, "frozen", False):
                    exe = f'"{sys.executable}"'
                else:
                    exe = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
                winreg.SetValueEx(k, "SheepNote", 0, winreg.REG_SZ, exe)
            else:
                try:
                    winreg.DeleteValue(k, "SheepNote")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(k)
        except OSError:
            pass

    def _quit(self):
        if _IS_WIN:
            try:
                self._tray_ready.wait(timeout=2.0)
                hwnd = self._tray_hwnd
                if hwnd:
                    ctypes.windll.user32.PostMessageW(hwnd, 0x0012, 0, 0)
            except Exception:
                pass
        else:
            if self._pystray_icon:
                try:
                    self._pystray_icon.stop()
                except Exception:
                    pass
        self.save()
        self.root.quit()

    def save(self):
        data = {"version": _VERSION, "lang": self.lang,
                "notes": [n.snapshot() for n in self.notes]}
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _apply_lang(self, new_lang: str):
        if new_lang == self.lang:
            return
        self.lang = new_lang
        _LANG[0]  = new_lang
        self.save()
        self._close_list_popups()
        # 非 Win32：重建 pystray 菜单让语言即时生效
        if not _IS_WIN and self._pystray_icon:
            try:
                self._pystray_icon.menu = self._build_pystray_menu()
            except Exception:
                pass
        for note in self.notes:
            try:
                note.pin_btn.config(text=T("pin"))
            except Exception:
                pass
            try:
                note._ctx.entryconfig(0, label=T("menu_clear"))
                note._ctx.entryconfig(2, label=T("menu_del_note"))
            except Exception:
                pass
            note._refresh()

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
class _TbBtn(tk.Canvas):
    """Toolbar button rendered on a Canvas.

    Text is drawn via create_text at (w//2, TB_HEIGHT//2) with
    anchor="center", giving pixel-exact vertical centering regardless
    of font ascender/descender metrics or emoji rendering quirks.
    """
    def __init__(self, parent, text, tbg, tbfg, font_spec, hover, cmd,
                 tb_widgets, *, is_sep=False):
        fnt  = tkFont.Font(font=font_spec)
        padx = 6
        tw   = fnt.measure(text)
        w    = max(tw + padx * 2, 14)
        super().__init__(parent, bg=tbg, width=w, height=TB_HEIGHT,
                         highlightthickness=0, bd=0,
                         cursor="hand2" if (cmd and not is_sep) else "arrow")
        self._tbg       = tbg
        self._hv        = hover or "#F0C060"
        self._text      = text
        self._font_spec = font_spec
        self._padx      = padx
        self._tid  = self.create_text(w // 2, TB_HEIGHT // 2, text=text,
                                      font=font_spec, fill=tbfg, anchor="center")
        if cmd and not is_sep:
            def _enter(e, s=self): s._on_hover(True)
            def _leave(e, s=self): s._on_hover(False)
            self.bind("<Enter>",    _enter)
            self.bind("<Leave>",    _leave)
            self.bind("<Button-1>", lambda e: cmd())
        tb_widgets.append(self)

    def _on_hover(self, on: bool):
        bg = self._hv if on else self._tbg
        tk.Canvas.configure(self, bg=bg)

    def cget(self, key):
        if key == "text": return self._text
        if key == "fg":   return self.itemcget(self._tid, "fill")
        return super().cget(key)

    def config(self, **kwargs):
        text = kwargs.pop("text", None)
        bg   = kwargs.pop("bg",   None)
        fg   = kwargs.pop("fg",   None)
        if text is not None:
            self._text = text
            self.itemconfig(self._tid, text=text)
            fnt = tkFont.Font(font=self._font_spec)
            w   = max(fnt.measure(text) + self._padx * 2, 14)
            tk.Canvas.configure(self, width=w)
            self.coords(self._tid, w // 2, TB_HEIGHT // 2)
        if bg is not None:
            self._tbg = bg
            tk.Canvas.configure(self, bg=bg)
        if fg is not None:
            self.itemconfig(self._tid, fill=fg)
        if kwargs:
            tk.Canvas.configure(self, **kwargs)

    configure = config


# ════════════════════════════════════════════════════════════════════
class _AppleToggle(tk.Canvas):
    """iOS-style toggle switch drawn on a Canvas."""
    W, H = 44, 26
    OFF_BG, ON_BG = "#D1D1D6", "#34C759"

    def __init__(self, parent, value: bool, command, bg="#FFFFFF"):
        super().__init__(parent, width=self.W, height=self.H,
                         bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self._val     = value
        self._cmd     = command
        self._anim_id = None
        self._phase   = 1.0 if value else 0.0
        self._draw()
        self.bind("<Button-1>", lambda e: self._toggle())
        self.bind("<Destroy>",  lambda e: self._cancel_anim())

    def _lerp_color(self, t: float) -> str:
        def h2rgb(h): return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))
        r0, g0, b0 = h2rgb(self.OFF_BG)
        r1, g1, b1 = h2rgb(self.ON_BG)
        return "#{:02x}{:02x}{:02x}".format(
            int(r0 + (r1 - r0) * t),
            int(g0 + (g1 - g0) * t),
            int(b0 + (b1 - b0) * t))

    def _draw(self):
        self.delete("all")
        t   = self._phase
        bg  = self._lerp_color(t)
        r   = self.H // 2
        # pill background
        self.create_oval(0, 0, self.H, self.H, fill=bg, outline="")
        self.create_rectangle(r, 0, self.W - r, self.H, fill=bg, outline="")
        self.create_oval(self.W - self.H, 0, self.W, self.H, fill=bg, outline="")
        # thumb
        m  = 2
        tx = int(m + t * (self.W - self.H))
        self.create_oval(tx, m, tx + self.H - m * 2, self.H - m,
                         fill="#FFFFFF", outline="")

    def _toggle(self):
        self._val = not self._val
        if self._anim_id:
            self.after_cancel(self._anim_id)
        self._animate()
        if self._cmd:
            self._cmd(self._val)

    def _cancel_anim(self):
        if self._anim_id:
            try:
                self.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None

    def _animate(self):
        target = 1.0 if self._val else 0.0
        diff   = target - self._phase
        if abs(diff) < 0.04:
            self._phase = target
            try:
                self._draw()
            except tk.TclError:
                pass
            return
        self._phase += diff * 0.35
        try:
            self._draw()
            self._anim_id = self.after(12, self._animate)
        except tk.TclError:
            pass

    def set(self, value: bool):
        self._val   = value
        self._phase = 1.0 if value else 0.0
        self._draw()


# ════════════════════════════════════════════════════════════════════
class StickyNote:
    """单个便签窗口（tk.Toplevel）。"""

    def __init__(self, master: tk.Tk, data: dict, app: App, offset: int = 0):
        self.app  = app
        self.win  = tk.Toplevel(master)
        self.win.title("SheepNote")
        self.win.overrideredirect(True)
        if _IS_WIN:
            self.win.after(120, self._hide_from_taskbar)

        self._dx = self._dy = 0
        self._rsx = self._rsy = self._rsw = self._rsh = 0
        self._pending_delete_ids: dict[int, str] = {}   # G: per-idx，避免并发覆盖
        self._round_after:        str | None = None
        self._toast_after:        str | None = None
        self._toast_frame:        tk.Frame | None = None
        self._toast_type:         str | None = None     # C: "delete" | "clear"
        self._deleted_task:       tuple | None = None
        self._cleared_done_tasks: list | None = None
        self._refresh_id:         str | None = None     # E: 防抖调度 ID
        self._refresh_focus_new:  bool = False          # E: 防抖期间积累 focus_new
        self._wheel_bound:        bool = False          # A: 防止重复 bind_all

        self.tasks:    list[dict] = data.get("tasks",    [])
        self._topmost: bool  = data.get("topmost",  False)
        self._fs:      int   = data.get("font_size", FS_DEF)
        self._alpha:   float = data.get("alpha",     AL_DEF)
        self._bg:      str   = data.get("color",     BG_NOTE)
        self._locked:  bool  = False
        self._edge_snap:      bool       = data.get("edge_snap", False)
        self._edge_collapsed: bool       = False
        self._pre_edge_geo:   tuple|None = None
        self._edge_side:      str|None   = None
        self._edge_poll_id:   str|None   = None
        self._edge_peeking:   bool       = False
        self._edge_delay_cnt: int        = 0
        self._edge_cooldown:  bool       = False   # 收缩后冷却期，防止立即 peek
        self._edge_leave_id:  str|None   = None    # peek 离开后的延迟收缩 timer
        self._edge_anim_id:   str|None   = None    # 当前滑动动画 after ID
        self._saved_geo = data
        self._offset    = offset

        self._bghv = self._tbg = self._tbfg = self._tbsep = ""
        self._compute_derived_colors()

        self._tb_widgets: list[tk.Widget] = []
        self._new_entry:   tk.Entry    | None = None
        self._new_cb:      tk.Label    | None = None
        self._new_outer:   tk.Frame    | None = None
        self._list_popup:  tk.Toplevel | None = None

        self.win.configure(bg=self._bg)
        self.win.attributes("-topmost", self._topmost)
        self.win.attributes("-alpha",   self._alpha)

        self._build()
        self._refresh()
        self._apply_geo()

    # ── 颜色计算 ──────────────────────────────────────────────────
    def _compute_derived_colors(self):
        h  = self._bg.lstrip('#')
        r8, g8, b8 = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        self._bghv = "#{:02x}{:02x}{:02x}".format(
            max(0, int(r8 * 0.90)), max(0, int(g8 * 0.90)), max(0, int(b8 * 0.90)))

        lookup = _PRESET_TB.get(self._bg.lower())
        if lookup:
            self._tbg = lookup
        else:
            hue, sat, val = colorsys.rgb_to_hsv(r8/255, g8/255, b8/255)
            nr, ng, nb = colorsys.hsv_to_rgb(
                hue, min(1.0, sat * 3.2 + 0.40), max(0.45, val * 0.64))
            self._tbg = "#{:02x}{:02x}{:02x}".format(
                int(nr*255), int(ng*255), int(nb*255))

        th = self._tbg.lstrip('#')
        tr, tg, tb = int(th[0:2], 16), int(th[2:4], 16), int(th[4:6], 16)
        self._tbfg  = "#FFFFFF" if (tr*299 + tg*587 + tb*114)/1000 < 155 else "#3E2723"
        self._tbsep = "#{:02x}{:02x}{:02x}".format(
            min(255, int(tr * 1.25)), min(255, int(tg * 1.25)), min(255, int(tb * 1.25)))

    def _apply_tb_color(self):
        if self._tb_h > 0:
            self._set_tb_content_visible(True)
        self._rsz_canvas.itemconfig(self._rsz_tri, fill=self._tbg)
        self._lock_strip.config(bg=ACCENT if self._locked else self._bg)

    def _apply_color(self, color: str):
        """仅更新视觉颜色，不触发 refresh/save（用于悬停实时预览）。"""
        self._bg = color
        self._compute_derived_colors()
        self._apply_tb_color()
        for w in (self.win, self._list_outer, self.canvas,
                  self.sf, self._rsz_canvas, self._sb_canvas):
            try:
                w.configure(bg=color)
            except Exception:
                pass

    def _set_color(self, color: str):
        self._apply_color(color)
        self._refresh()
        self.app.save()

    # ════════════════════════════════════════════════════════════════
    # P0: Apple-style 确认对话框
    # ════════════════════════════════════════════════════════════════
    def _ask_confirm(self, message: str, action_label: str = "删除") -> bool:
        answered = [False]
        dlg = tk.Toplevel(self.win)
        dlg.withdraw()                    # 先隐藏，防止左上角闪现
        dlg.overrideredirect(True)
        dlg.attributes("-topmost", True)
        dlg.configure(bg="#E8E8E8")

        card = tk.Frame(dlg, bg="#FFFFFF", padx=SP4, pady=SP3)
        card.pack(padx=1, pady=1)

        tk.Label(card, text=message, bg="#FFFFFF", fg=FG_TASK,
                 font=FONT_BODY, wraplength=220, justify=tk.CENTER).pack(pady=(0, SP3))

        row = tk.Frame(card, bg="#FFFFFF")
        row.pack(fill=tk.X)

        def _cancel():
            dlg.destroy()

        def _confirm():
            answered[0] = True
            dlg.destroy()

        btn_cancel = tk.Label(row, text=T("cancel"), bg="#EEEEEE", fg=FG_TASK,
                              font=FONT_SMALL, padx=SP3, pady=SP2, cursor="hand2")
        btn_cancel.pack(side=tk.LEFT, padx=(0, SP2))
        btn_cancel.bind("<Button-1>", lambda e: _cancel())
        btn_cancel.bind("<Enter>", lambda e: btn_cancel.config(bg="#E0E0E0"))
        btn_cancel.bind("<Leave>", lambda e: btn_cancel.config(bg="#EEEEEE"))

        btn_ok = tk.Label(row, text=action_label, bg=COLOR_DANGER, fg="#FFFFFF",
                          font=FONT_SMALL, padx=SP3, pady=SP2, cursor="hand2")
        btn_ok.pack(side=tk.LEFT)
        btn_ok.bind("<Button-1>", lambda e: _confirm())
        btn_ok.bind("<Enter>", lambda e: btn_ok.config(bg="#C62828"))
        btn_ok.bind("<Leave>", lambda e: btn_ok.config(bg=COLOR_DANGER))

        dlg.update_idletasks()
        dw = dlg.winfo_reqwidth()
        dh = dlg.winfo_reqheight()
        wx = self.win.winfo_x() + self.win.winfo_width() // 2 - dw // 2
        wy = self.win.winfo_y() + self.win.winfo_height() // 2 - dh // 2
        dlg.geometry(f"{dw}x{dh}+{wx}+{wy}")
        dlg.deiconify()         # 定位完成后显示
        dlg.bind("<Escape>", lambda e: _cancel())
        dlg.grab_set()
        try:
            dlg.wait_window()       # F: 父窗口销毁时安全退出
        except tk.TclError:
            pass
        return answered[0]

    def _confirm_delete_note(self):
        if self._ask_confirm(T("confirm_delete"), T("confirm_ok")):
            self.app.delete_note(self)

    def _confirm_clear_done(self):
        done_tasks = [(i, self.tasks[i]) for i in range(len(self.tasks))
                      if self.tasks[i]["done"]]
        if not done_tasks:
            return
        self._clear_done()
        self._show_clear_undo_toast(done_tasks)

    # ════════════════════════════════════════════════════════════════
    # P0: Undo Toast（任务删除后 3 秒撤销）
    # ════════════════════════════════════════════════════════════════
    def _show_undo_toast(self, task: dict, idx: int):
        self._dismiss_toast()
        self._deleted_task = (task, idx)
        self._toast_type   = "delete"   # C: 标记类型

        frame = tk.Frame(self.win, bg="#323232")
        frame.pack(side=tk.BOTTOM, fill=tk.X)
        frame.lift()
        self._toast_frame = frame

        tk.Label(frame, text=T("toast_deleted", text=task['text'][:18]),
                 bg="#323232", fg="#FFFFFF", font=FONT_SMALL,
                 padx=SP3, pady=SP2).pack(side=tk.LEFT)

        undo = tk.Label(frame, text=T("undo"), bg="#323232", fg=ACCENT_LIGHT,
                        font=("Microsoft YaHei", 9, "bold"),
                        padx=SP3, pady=SP2, cursor="hand2")
        undo.pack(side=tk.RIGHT)
        undo.bind("<Button-1>", lambda e: self._undo_delete())
        undo.bind("<Enter>", lambda e: undo.config(fg="#FFFFFF"))
        undo.bind("<Leave>", lambda e: undo.config(fg=ACCENT_LIGHT))

        self._toast_after = self.win.after(TOAST_DURATION, self._dismiss_toast)

    def _undo_delete(self):
        if self._deleted_task:
            task, idx = self._deleted_task
            self._deleted_task = None
            self.tasks.insert(min(idx, len(self.tasks)), task)
            self.app.save()
            if self._refresh_id:
                self.win.after_cancel(self._refresh_id)
                self._refresh_id = None
            self._do_refresh()
        self._dismiss_toast()

    def _show_clear_undo_toast(self, done_tasks: list):
        self._dismiss_toast()
        self._cleared_done_tasks = done_tasks
        self._toast_type         = "clear"      # C: 标记类型
        count = len(done_tasks)

        frame = tk.Frame(self.win, bg="#323232")
        frame.pack(side=tk.BOTTOM, fill=tk.X)
        frame.lift()
        self._toast_frame = frame

        tk.Label(frame, text=T("toast_cleared", n=count),
                 bg="#323232", fg="#FFFFFF", font=FONT_SMALL,
                 padx=SP3, pady=SP2).pack(side=tk.LEFT)

        undo = tk.Label(frame, text=T("undo"), bg="#323232", fg=ACCENT_LIGHT,
                        font=("Microsoft YaHei", 9, "bold"),
                        padx=SP3, pady=SP2, cursor="hand2")
        undo.pack(side=tk.RIGHT)
        undo.bind("<Button-1>", lambda e: self._undo_clear_done())
        undo.bind("<Enter>",    lambda e: undo.config(fg="#FFFFFF"))
        undo.bind("<Leave>",    lambda e: undo.config(fg=ACCENT_LIGHT))

        self._toast_after = self.win.after(TOAST_DURATION, self._dismiss_toast)

    def _undo_clear_done(self):
        if self._cleared_done_tasks:
            for orig_idx, task in sorted(self._cleared_done_tasks, key=lambda x: x[0]):
                self.tasks.insert(min(orig_idx, len(self.tasks)), task)
            self._cleared_done_tasks = None
            self.app.save()
            if self._refresh_id:
                self.win.after_cancel(self._refresh_id)
                self._refresh_id = None
            self._do_refresh()
        self._dismiss_toast()

    def _dismiss_toast(self):
        if self._toast_after:
            self.win.after_cancel(self._toast_after)
            self._toast_after = None
        if self._toast_frame:
            try:
                self._toast_frame.destroy()
            except Exception:
                pass
            self._toast_frame = None
        # C: 只清除当前 Toast 类型对应的数据，不互相干扰
        if self._toast_type == "delete":
            self._deleted_task = None
        elif self._toast_type == "clear":
            self._cleared_done_tasks = None
        self._toast_type = None

    def _ctrl_z(self):
        """Ctrl+Z：撤销当前 Toast 对应的操作。"""
        if self._toast_type == "delete" and self._deleted_task:
            self._undo_delete()
        elif self._toast_type == "clear" and self._cleared_done_tasks:
            self._undo_clear_done()

    # ════════════════════════════════════════════════════════════════
    # P2: 圆角 + DWM 投影（Windows only；macOS 原生自带）
    # ════════════════════════════════════════════════════════════════
    def _get_hwnd(self) -> int:
        if not _IS_WIN:
            return 0
        inner = self.win.winfo_id()
        outer = ctypes.windll.user32.GetParent(inner)
        if outer and ctypes.windll.user32.IsWindow(outer):
            return outer
        return inner

    def _apply_rounded(self, radius: int = 10):
        if not _IS_WIN:
            return   # macOS 窗口自带圆角，无需处理
        try:
            hwnd = self._get_hwnd()
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(ctypes.c_int(3)), 4)
            if res != 0:
                self.win.update_idletasks()
                w = self.win.winfo_width()
                h = self.win.winfo_height()
                if w < 4 or h < 4:
                    return
                rgn = ctypes.windll.gdi32.CreateRoundRectRgn(
                    0, 0, w + 1, h + 1, radius * 2, radius * 2)
                ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
        except Exception:
            pass

    def _apply_shadow(self):
        if not _IS_WIN:
            return   # macOS 窗口自带投影
        try:
            hwnd = self._get_hwnd()
            policy = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 2, ctypes.byref(policy), ctypes.sizeof(policy))
        except Exception:
            pass

    def _schedule_round(self, _e=None):
        if self._round_after:
            self.win.after_cancel(self._round_after)
        self._round_after = self.win.after(40, self._apply_rounded)

    # ════════════════════════════════════════════════════════════════
    # UI 构建
    # ════════════════════════════════════════════════════════════════
    def _build(self):
        # P2: 锁定状态左侧色条（3px，常驻，默认透明）
        self._lock_strip = tk.Frame(self.win, width=3, bg=self._bg)
        self._lock_strip.place(relx=0, rely=0, relheight=1.0, anchor="nw")

        # 锁定状态左下角锁定按钮（hover 时出现，低存在感灰色）
        self._lock_icon_btn = tk.Label(
            self.win, text="🔒", bg="#888888", fg="#EEEEEE",
            font=("Segoe UI Emoji", 11), cursor="hand2", padx=4, pady=2)
        self._lock_icon_btn.place_forget()
        self._lock_icon_btn.bind("<Button-1>", lambda e: self._toggle_lock())
        self._lock_icon_btn.bind("<Enter>",    lambda e: self._lock_icon_btn.config(bg="#AAAAAA"))
        self._lock_icon_btn.bind("<Leave>",    lambda e: self._lock_icon_btn.config(bg="#888888"))

        # ── 工具栏 ─────────────────────────────────────────────────
        self.tb = tk.Frame(self.win, bg=self._tbg, height=0)
        self.tb.pack(fill=tk.X)
        self.tb.pack_propagate(False)
        self._tb_h       = 0
        self._tb_anim_id = None
        self._tb_hide_id = None

        self.title_lbl = tk.Label(
            self.tb, text="⠿  SheepNote",
            bg=self._tbg, fg=self._tbfg, font=("Microsoft YaHei", 11, "bold"),
            cursor="fleur", anchor="center")
        self.title_lbl.pack(side=tk.LEFT, padx=(SP2, SP1), fill=tk.Y)
        self._tb_widgets.append(self.title_lbl)

        self.list_btn = self._tbtn("📋", self._toggle_list_popup, hover="#E65100")
        self.list_btn.pack(side=tk.LEFT, padx=SP1)

        nb = self._tbtn("＋", self.app.new_note, hover=COLOR_SUCCESS,
                        font=("Microsoft YaHei", 11))
        nb.pack(side=tk.LEFT, padx=SP1)

        self.rbar = tk.Frame(self.tb, bg=self._tbg)
        self.rbar.pack(side=tk.RIGHT, padx=SP1)

        self._tbtn("×", lambda: self.app.hide_note(self),
                   hover=COLOR_DANGER, parent=self.rbar).pack(side=tk.RIGHT, padx=1)

        self.lock_btn = self._tbtn("🔒", self._toggle_lock,
                                   hover=ACCENT, parent=self.rbar)
        self.lock_btn.pack(side=tk.RIGHT, padx=1)

        self.pin_btn = self._tbtn(T("pin"), self._toggle_topmost,
                                  hover="#F57F17", parent=self.rbar)
        if self._topmost:
            self.pin_btn.config(bg=ACCENT, fg="#FFFFFF")
        self.pin_btn.pack(side=tk.RIGHT, padx=1)


        for w in (self.tb, self.title_lbl):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>",     self._drag_move)

        # ── 任务区 ─────────────────────────────────────────────────
        self._list_outer = tk.Frame(self.win, bg=self._bg)
        self._list_outer.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self._list_outer, bg=self._bg, highlightthickness=0)
        self.sf = tk.Frame(self.canvas, bg=self._bg)

        self.sf.bind("<Configure>",
                     lambda e: self.canvas.configure(
                         scrollregion=self.canvas.bbox("all")))
        self._cwin = self.canvas.create_window((0, 0), window=self.sf, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_yscroll)
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._cwin, width=e.width))
        self.canvas.bind("<Configure>", lambda e: self._refresh(), add="+")

        def _on_wheel(e):
            cx, cy = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            if cx <= e.x_root <= cx + cw and cy <= e.y_root <= cy + ch:
                self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        # A: 用 _wheel_bound 防止重复 bind_all；不 unbind_all（避免多窗口互相禁用）
        def _bind_wheel(e=None):
            if not self._wheel_bound:
                self.canvas.bind_all("<MouseWheel>", _on_wheel, add="+")
                self._wheel_bound = True

        self.canvas.bind("<Enter>", _bind_wheel)

        # 点击空白区域移焦，触发 Entry FocusOut 保存编辑中的任务
        self.canvas.bind("<Button-1>", lambda e: self.win.focus_set(), add="+")
        self.sf.bind("<Button-1>",     lambda e: self.win.focus_set(), add="+")

        # P0: 确认项改为调用 _confirm_* 方法
        self._ctx = tk.Menu(self.win, tearoff=0)
        self._ctx.add_command(label=T("menu_clear"), command=self._confirm_clear_done)
        self._ctx.add_separator()
        self._ctx.add_command(label=T("menu_del_note"), command=self._confirm_delete_note)
        self.canvas.bind("<Button-3>",
                         lambda e: (None if self._locked else self._ctx.tk_popup(e.x_root, e.y_root)))
        self.sf.bind("<Button-3>",
                     lambda e: (None if self._locked else self._ctx.tk_popup(e.x_root, e.y_root)))

        self.canvas.pack(fill=tk.BOTH, expand=True)

        self._sb_canvas = tk.Canvas(
            self._list_outer, width=10, bg=self._bg, highlightthickness=0, bd=0)
        self._sb_hide_id: str | None = None

        self._rsz_canvas = tk.Canvas(
            self.win, width=26, height=26,
            bg=self._bg, highlightthickness=0, bd=0, cursor="sizing")
        self._rsz_canvas.place(relx=1.0, rely=1.0, anchor="se")
        self._rsz_tri = self._rsz_canvas.create_polygon(
            0, 26, 26, 26, 26, 0, fill=self._tbg, outline="", stipple="gray50")
        self._rsz_canvas.bind("<ButtonPress-1>", self._resize_start)
        self._rsz_canvas.bind("<B1-Motion>",     self._resize_move)

        # P1: 快捷键
        self.win.bind("<Control-n>", lambda e: self.app.new_note())
        self.win.bind("<Control-z>", lambda e: self._ctrl_z())
        # 点击窗口外（失焦）时保存编辑中的任务
        self.win.bind("<FocusOut>",
                      lambda e: self._commit_editing() if e.widget is self.win else None,
                      add="+")

        self._bind_hover()
        # 工具栏常驻，不依赖 hover
        self._tb_h = TB_HEIGHT
        self.tb.config(height=TB_HEIGHT)
        self._set_tb_content_visible(True)

    # ── 工具栏按钮工厂 ────────────────────────────────────────────
    def _tbtn(self, text, cmd, hover=None, parent=None, font=None) -> _TbBtn:
        p = parent if parent is not None else self.tb
        return _TbBtn(p, text, self._tbg, self._tbfg,
                      font or FONT_SMALL, hover, cmd, self._tb_widgets)

    def _sep(self):
        btn = _TbBtn(self.rbar, "│", self._tbg, self._tbsep,
                     FONT_SMALL, None, None, self._tb_widgets, is_sep=True)
        btn.pack(side=tk.RIGHT, padx=SP1, fill=tk.Y)

    # ── Apple 风格滚动条 ──────────────────────────────────────────
    def _on_yscroll(self, first: str, last: str):
        first, last = float(first), float(last)
        if first <= 0.0 and last >= 1.0:
            self._hide_scrollbar()
        else:
            self._draw_scrollbar(first, last)

    def _draw_scrollbar(self, first: float, last: float):
        sc = self._sb_canvas
        sc.delete("all")
        h = sc.winfo_height() or self.canvas.winfo_height()
        if h < 4:
            return
        sc.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne", x=-2)
        sc.lift()
        thumb_h = max(24, int(h * (last - first)))
        thumb_y = int(h * first)
        w = 5
        x1, x2 = 2, 2 + w
        y1, y2  = thumb_y + 2, thumb_y + thumb_h - 2
        r = w // 2
        c = "#555555"
        if y2 - y1 > 2 * r:
            sc.create_oval(x1, y1,        x2, y1 + 2*r, fill=c, outline="")
            sc.create_rectangle(x1, y1+r, x2, y2-r,     fill=c, outline="")
            sc.create_oval(x1, y2 - 2*r,  x2, y2,       fill=c, outline="")
        else:
            sc.create_oval(x1, y1, x2, max(y2, y1 + 2*r), fill=c, outline="")
        if self._sb_hide_id:
            sc.after_cancel(self._sb_hide_id)
        self._sb_hide_id = sc.after(SB_HIDE_DELAY, self._hide_scrollbar)

    def _hide_scrollbar(self):
        self._sb_canvas.place_forget()
        self._sb_hide_id = None

    # ── 工具栏 hover 显示 / 隐藏 ─────────────────────────────────
    def _bind_hover(self):
        """工具栏常驻，仅处理锁定时锁定按钮的 hover 显隐。"""
        def on_enter(e):
            if self._locked:
                self._lock_icon_btn.place(relx=0, rely=1.0, anchor="sw", x=6, y=-6)
                self._lock_icon_btn.lift()

        def on_leave(e):
            if not self._locked:
                return
            try:
                wx = self.win.winfo_rootx()
                wy = self.win.winfo_rooty()
                ww = self.win.winfo_width()
                wh = self.win.winfo_height()
                if wx <= e.x_root <= wx + ww and wy <= e.y_root <= wy + wh:
                    return
            except Exception:
                return
            self._lock_icon_btn.place_forget()

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
        if self._tb_anim_id:
            self.win.after_cancel(self._tb_anim_id)
            self._tb_anim_id = None
        target = TB_HEIGHT if show else 0
        if self._tb_h == target:
            return
        if show:
            self._show_new_row()
        else:
            self._hide_new_row()
            self._set_tb_content_visible(False)
        self._tb_step(target)

    def _show_new_row(self):
        try:
            if self._new_outer and self._new_outer.winfo_exists():
                self._new_outer.pack(fill=tk.X)
        except tk.TclError:
            pass

    def _hide_new_row(self):
        if self._new_entry:
            try:
                if self.win.focus_get() == self._new_entry:
                    return
            except Exception:
                pass
        try:
            if self._new_outer and self._new_outer.winfo_exists():
                self._new_outer.pack_forget()
        except tk.TclError:
            pass

    def _tb_step(self, target: int):
        was_zero = (self._tb_h == 0)
        # P2: ease-out — 步长为剩余距离的 35%，最小 2px
        diff = target - self._tb_h
        step = max(2, abs(diff) * 35 // 100)
        if diff > 0:
            self._tb_h = min(target, self._tb_h + step)
            if was_zero:
                self._set_tb_content_visible(True)
        else:
            self._tb_h = max(target, self._tb_h - step)
        try:
            self.tb.config(height=self._tb_h)
        except Exception:
            return
        if self._tb_h != target:
            self._tb_anim_id = self.win.after(16, lambda: self._tb_step(target))

    def _set_tb_content_visible(self, visible: bool):
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
            if self._topmost:
                self.pin_btn.config(bg=ACCENT, fg="#FFFFFF")
            if self._locked:
                self.lock_btn.config(bg=ACCENT)
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
        if _IS_WIN:
            try:
                class RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
                class MONITORINFO(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_ulong),
                                ("rcMonitor", RECT), ("rcWork", RECT),
                                ("dwFlags", ctypes.c_ulong)]
                hwnd = self.win.winfo_id()
                hm   = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)
                mi   = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                ctypes.windll.user32.GetMonitorInfoW(hm, ctypes.byref(mi))
                r = mi.rcWork
                return r.left, r.top, r.right, r.bottom
            except Exception:
                pass
        # macOS / fallback: use tkinter screen dimensions; leave 25px for macOS menubar
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        top_offset = 25 if _IS_MAC else 0
        return (0, top_offset, sw, sh)

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
        popup.withdraw()                  # 先隐藏，防止出现在屏幕左上角
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg="#C8C8C8")
        setattr(self, attr, popup)

        def _on_destroy(e):
            if getattr(self, attr, None) is popup:
                setattr(self, attr, None)
        popup.bind("<Destroy>", _on_destroy)

        card = tk.Frame(popup, bg="#FFFFFF", padx=SP3, pady=SP2)
        card.pack(padx=1, pady=1, fill=tk.BOTH, expand=True)
        build_fn(card)

        if _IS_WIN:
            u32 = ctypes.windll.user32
            vx = u32.GetSystemMetrics(76)
            vy = u32.GetSystemMetrics(77)
            vw = u32.GetSystemMetrics(78)
            vh = u32.GetSystemMetrics(79)
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

            overlay.bind("<Button-1>", lambda *_: _close())
            popup.bind("<Destroy>",
                       lambda *_: overlay.destroy() if overlay.winfo_exists() else None,
                       add="+")
        else:
            def _close():
                try:
                    if popup.winfo_exists(): popup.destroy()
                except Exception: pass

        # P1: Escape 关闭弹窗
        popup.bind("<Escape>",  lambda *_: _close())
        if _IS_WIN:
            overlay.bind("<Escape>", lambda *_: _close())

        popup.update_idletasks()
        pw = popup.winfo_reqwidth()
        ph = popup.winfo_reqheight()
        bx = anchor.winfo_rootx()
        by = anchor.winfo_rooty() + anchor.winfo_height() + SP1
        ml, mt, mr, mb = self._monitor_workarea()
        bx = max(ml, min(bx, mr - pw - 6))
        by = max(mt, min(by, mb - ph - 6))
        popup.geometry(f"{pw}x{ph}+{bx}+{by}")
        popup.deiconify()       # 定位完成后再显示
        popup.lift()
        if _IS_WIN:
            try:
                hwnd = popup.winfo_id()
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 33, ctypes.byref(ctypes.c_int(3)), 4)
            except Exception:
                pass

    # ── 便签列表 + 设置 综合弹出 ──────────────────────────────────
    @staticmethod
    def _note_label(idx: int, note: "StickyNote") -> str:
        for t in note.tasks:
            text = t["text"].strip()
            if text:
                return text[:20] + ("…" if len(text) > 20 else "")
        return T("note_default", n=idx + 1)

    def _toggle_list_popup(self):
        def build(card):
            BG = "#FFFFFF"
            notes = self.app.notes

            # ── 标题行 ────────────────────────────────────────────────
            hdr = tk.Frame(card, bg=BG)
            hdr.pack(fill=tk.X, pady=(0, SP2))
            tk.Label(hdr, text=T("list_title"), bg=BG, fg=FG_TASK,
                     font=FONT_TITLE).pack(side=tk.LEFT)
            # 便签数量角标
            cnt_f = tk.Frame(hdr, bg="#EEF2FF")
            cnt_f.pack(side=tk.RIGHT, anchor="center")
            tk.Label(cnt_f, text=T("note_count", n=len(notes)),
                     bg="#EEF2FF", fg=ACCENT, font=FONT_SMALL,
                     padx=SP1 + 2, pady=1).pack()

            # ── 便签行（自带顶部 divider） ────────────────────────────
            for i, note in enumerate(notes):
                self._list_row(card, i, note)

            # ── 新建便签 ──────────────────────────────────────────────
            tk.Frame(card, bg=DIVIDER, height=1).pack(fill=tk.X, pady=(SP1, 0))
            new_f = tk.Frame(card, bg=BG, cursor="hand2")
            new_f.pack(fill=tk.X)
            new_lbl = tk.Label(new_f, text=T("new_note"), bg=BG,
                               fg=COLOR_SUCCESS, font=FONT_SMALL, pady=SP2)
            new_lbl.pack()

            def _hov_new(on):
                c = "#F0FDF4" if on else BG
                new_f.config(bg=c); new_lbl.config(bg=c)

            for w in (new_f, new_lbl):
                w.bind("<Button-1>", lambda e: self.app.new_note())
                w.bind("<Enter>",    lambda e: _hov_new(True))
                w.bind("<Leave>",    lambda e: _hov_new(False))

            # ── 当前便签设置 ──────────────────────────────────────────
            tk.Frame(card, bg=DIVIDER, height=1).pack(fill=tk.X, pady=(0, SP2))
            tk.Label(card, text=T("settings"), bg=BG, fg=FG_HINT,
                     font=FONT_SMALL).pack(anchor="w", pady=(0, SP2))

            # 颜色
            color_row = tk.Frame(card, bg=BG)
            color_row.pack(fill=tk.X, pady=(0, SP2))
            tk.Label(color_row, text=T("color"), bg=BG, fg=FG_TASK,
                     font=FONT_SMALL).pack(side=tk.LEFT)
            swatches_f = tk.Frame(color_row, bg=BG)
            swatches_f.pack(side=tk.RIGHT)
            _orig_bg = [self._bg]
            for hex_col, _ in NOTE_COLORS:
                selected = self._bg.lower() == hex_col.lower()
                ring = tk.Frame(swatches_f,
                                bg=ACCENT if selected else "#E0E0E0",
                                padx=2, pady=2, cursor="hand2")
                ring.pack(side=tk.LEFT, padx=(0, SP1))
                sw = tk.Label(ring, bg=hex_col, width=3, height=1, cursor="hand2")
                sw.pack()

                def _pick(e, c=hex_col):
                    _orig_bg[0] = c
                    self._set_color(c)

                for w in (sw, ring):
                    w.bind("<Button-1>", _pick)
                sw.bind("<Enter>", lambda e, r=ring, c=hex_col: (
                    r.config(bg=ACCENT), self._apply_color(c)))
                sw.bind("<Leave>",
                        lambda e, r=ring, sel=selected: (
                        r.config(bg=ACCENT if sel else "#E0E0E0"),
                        self._apply_color(_orig_bg[0])))

            cust = tk.Label(swatches_f, text="…", bg=TAG_BG, fg=FG_HINT,
                            font=FONT_SMALL, padx=SP2, pady=2, cursor="hand2")
            cust.pack(side=tk.LEFT)

            def _open_picker():
                from tkinter.colorchooser import askcolor
                orig = self._bg
                r = askcolor(color=self._bg, title=T("color_picker"), parent=self.win)
                if r[1]:
                    _orig_bg[0] = r[1]
                    self._set_color(r[1])
                else:
                    self._apply_color(orig)

            cust.bind("<Button-1>", lambda e: _open_picker())
            cust.bind("<Enter>",    lambda e: cust.config(bg=TAG_HOV))
            cust.bind("<Leave>",    lambda e: cust.config(bg=TAG_BG))

            # 弹窗关闭时（Escape、点击遮罩等），若鼠标仍悬停则 <Leave> 不触发，
            # 在此兜底还原到最后一次确认的颜色。
            _popup = card.winfo_toplevel()
            def _restore_on_popup_close(e):
                if e.widget is _popup:
                    self._apply_color(_orig_bg[0])
            _popup.bind("<Destroy>", _restore_on_popup_close, add="+")

            tk.Frame(card, bg="#F0F0F0", height=1).pack(fill=tk.X, pady=(0, SP2))

            # 字号 + 透明度 滑块
            def _slider(label, var, fmt):
                sec = tk.Frame(card, bg=BG)
                sec.pack(fill=tk.X, pady=(0, SP1))
                top = tk.Frame(sec, bg=BG)
                top.pack(fill=tk.X)
                tk.Label(top, text=label, bg=BG, fg=FG_TASK,
                         font=FONT_SMALL).pack(side=tk.LEFT)
                val_lbl = tk.Label(top, text=fmt(var.get()), bg=BG,
                                   fg=ACCENT, font=("Microsoft YaHei", 9, "bold"))
                val_lbl.pack(side=tk.RIGHT)
                return sec, val_lbl

            fs_var = tk.IntVar(value=self._fs)
            fs_sec, fs_val = _slider(T("font_size"), fs_var, lambda v: f"{v}pt")

            def _on_fs(v):
                nv = int(float(v))
                fs_val.config(text=f"{nv}pt")
                if nv != self._fs:
                    self._fs = nv; self._refresh(); self.app.save()

            ttk.Scale(fs_sec, from_=FS_MIN, to=FS_MAX, orient=tk.HORIZONTAL,
                      variable=fs_var, command=_on_fs).pack(fill=tk.X, pady=(SP1, 0))

            al_var = tk.IntVar(value=int(self._alpha * 100))
            al_sec, al_val = _slider(T("opacity"), al_var, lambda v: f"{v}%")

            def _on_al(v):
                nv_pct = int(float(v))
                al_val.config(text=f"{nv_pct}%")
                nv = max(AL_MIN, round(nv_pct / 100, 2))
                if nv != self._alpha:
                    self._alpha = nv
                    self.win.attributes("-alpha", nv)
                    self.app.save()

            ttk.Scale(al_sec, from_=int(AL_MIN * 100), to=100,
                      orient=tk.HORIZONTAL, variable=al_var,
                      command=_on_al).pack(fill=tk.X, pady=(SP1, 0))

            # ── 语言选择器 ────────────────────────────────────────────
            tk.Frame(card, bg="#F0F0F0", height=1).pack(fill=tk.X, pady=(SP1, SP2))
            lang_row = tk.Frame(card, bg=BG)
            lang_row.pack(fill=tk.X)
            tk.Label(lang_row, text=T("language"), bg=BG, fg=FG_TASK,
                     font=FONT_SMALL).pack(side=tk.LEFT)
            langs_f = tk.Frame(lang_row, bg=BG)
            langs_f.pack(side=tk.RIGHT)
            for _lc, _abbr in [("zh","中"),("en","EN"),("ja","日"),
                                ("de","DE"),("fr","FR"),("es","ES")]:
                _sel = self.app.lang == _lc
                _lb  = tk.Label(langs_f, text=_abbr,
                                bg=ACCENT    if _sel else TAG_BG,
                                fg="#FFFFFF" if _sel else FG_HINT,
                                font=FONT_SMALL, padx=SP2, pady=SP1,
                                cursor="arrow" if _sel else "hand2")
                _lb.pack(side=tk.LEFT, padx=(0, SP1 // 2))
                if not _sel:
                    _lb.bind("<Button-1>", lambda e, c=_lc: self.app._apply_lang(c))
                    _lb.bind("<Enter>",    lambda e, b=_lb: b.config(bg=TAG_HOV))
                    _lb.bind("<Leave>",    lambda e, b=_lb: b.config(bg=TAG_BG))

            # ── 边缘收缩开关 ──────────────────────────────────────────
            tk.Frame(card, bg="#F0F0F0", height=1).pack(fill=tk.X, pady=(SP1, SP2))
            snap_row = tk.Frame(card, bg=BG)
            snap_row.pack(fill=tk.X, pady=(0, SP1))
            tk.Label(snap_row, text="边缘自动收缩", bg=BG, fg=FG_TASK,
                     font=FONT_SMALL).pack(side=tk.LEFT)
            _AppleToggle(snap_row, self._edge_snap,
                         lambda v: self._set_edge_snap(v),
                         bg=BG).pack(side=tk.RIGHT)

            # ── 开机自动启动（Windows only）──────────────────────────
            if _IS_WIN:
                tk.Frame(card, bg="#F0F0F0", height=1).pack(fill=tk.X, pady=(SP1, SP2))
                auto_row = tk.Frame(card, bg=BG)
                auto_row.pack(fill=tk.X, pady=(0, SP1))
                tk.Label(auto_row, text="开机自动启动", bg=BG, fg=FG_TASK,
                         font=FONT_SMALL).pack(side=tk.LEFT)
                _AppleToggle(auto_row, App._autostart_enabled(),
                             lambda v: App._set_autostart(v),
                             bg=BG).pack(side=tk.RIGHT)

        self._open_popup(self.list_btn, "_list_popup", build)

    def _list_row(self, parent, idx: int, note: "StickyNote"):
        visible    = note.win.state() != "withdrawn"
        task_count = len(note.tasks)
        done_count = sum(1 for t in note.tasks if t["done"])
        label_text = self._note_label(idx, note)
        count_text = (T("note_tasks", t=task_count, d=done_count)
                      if task_count else T("no_tasks"))
        BG     = "#FFFFFF" if visible else ROW_HID_BG
        BG_HOV = ROW_VIS_HOV if visible else ROW_HID_HOV

        row = tk.Frame(parent, bg=BG)
        row.pack(fill=tk.X)
        # 顶部细分隔线（row 之间）
        tk.Frame(row, bg=DIVIDER, height=1).pack(fill=tk.X, side=tk.TOP)

        body = tk.Frame(row, bg=BG)
        body.pack(fill=tk.X)

        stripe = tk.Frame(body, bg=note._tbg if visible else FG_HINT, width=3)
        stripe.pack(side=tk.LEFT, fill=tk.Y)
        inner = tk.Frame(body, bg=BG, padx=SP2, pady=SP1)
        inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        name_fg = FG_TASK if visible else FG_HINT
        tk.Label(inner, text=label_text, bg=BG, fg=name_fg,
                 font=FONT_BODY, anchor="w").pack(anchor="w")
        tk.Label(inner, text=count_text, bg=BG, fg=FG_HINT,
                 font=FONT_SMALL, anchor="w").pack(anchor="w")

        # ── 操作按钮区 ──────────────────────────────────────────
        btns = tk.Frame(body, bg=BG)
        btns.pack(side=tk.RIGHT, padx=SP1, pady=SP1)

        BTN_BG = note._tbg if visible else "#E0E0E0"
        BTN_FG = note._tbfg if visible else FG_HINT
        tog = tk.Label(btns, text=T("hide") if visible else T("show"),
                       bg=BTN_BG, fg=BTN_FG,
                       font=FONT_SMALL, padx=SP2, pady=SP1, cursor="hand2")
        tog.pack(side=tk.LEFT, padx=(0, SP1))

        is_last = len(self.app.notes) <= 1
        del_btn = tk.Label(btns, text="×",
                           bg=BG, fg=FG_HINT if is_last else COLOR_DANGER,
                           font=FONT_BODY, padx=SP1 + 2, pady=0,
                           cursor="arrow" if is_last else "hand2")
        del_btn.pack(side=tk.LEFT)

        _vis = [visible]

        def _apply(v):
            bg = "#FFFFFF" if v else ROW_HID_BG
            stripe.config(bg=note._tbg if v else FG_HINT)
            for w in (row, body, inner, btns, del_btn): w.config(bg=bg)
            for ch in inner.winfo_children(): ch.config(bg=bg)
            tog.config(text=T("hide") if v else T("show"),
                       bg=note._tbg if v else "#E0E0E0",
                       fg=note._tbfg if v else FG_HINT)

        def toggle_vis():
            now = note.win.state() != "withdrawn"
            if now:
                note.win.withdraw(); _vis[0] = False
            else:
                note.win.deiconify(); _vis[0] = True
            _apply(_vis[0]); self.app.save()

        tog.bind("<Button-1>", lambda e: toggle_vis())
        tog.bind("<Enter>", lambda e, t=tog, v=_vis:
                 t.config(bg=ACCENT if v[0] else "#B0B0B0"))
        tog.bind("<Leave>", lambda e, t=tog, v=_vis:
                 t.config(bg=note._tbg if v[0] else "#E0E0E0"))

        if not is_last:
            del_btn.bind("<Button-1>", lambda e, n=note: n._confirm_delete_note())
            del_btn.bind("<Enter>",    lambda e: del_btn.config(bg=DANGER_TINT))
            del_btn.bind("<Leave>",    lambda e: del_btn.config(
                bg="#FFFFFF" if _vis[0] else ROW_HID_BG))

        all_w = [row, body, inner, btns]

        def hl_on(e):
            for w in all_w: w.config(bg=BG_HOV)
            for ch in inner.winfo_children(): ch.config(bg=BG_HOV)
            if is_last: del_btn.config(bg=BG_HOV)

        def hl_off(e):
            ox = body.winfo_rootx(); oy = body.winfo_rooty()
            if not (ox <= e.x_root < ox + body.winfo_width() and
                    oy <= e.y_root < oy + body.winfo_height()):
                cur = "#FFFFFF" if _vis[0] else ROW_HID_BG
                for w in all_w: w.config(bg=cur)
                for ch in inner.winfo_children(): ch.config(bg=cur)
                if is_last: del_btn.config(bg=cur)

        for w in all_w:
            w.bind("<Enter>", hl_on); w.bind("<Leave>", hl_off)

        ctx = tk.Menu(parent, tearoff=0)
        ctx.add_command(label=T("menu_del_note"),
                        command=lambda n=note: n._confirm_delete_note())

        def _list_ctx(e):
            ctx.tk_popup(e.x_root, e.y_root)
            cur = "#FFFFFF" if _vis[0] else ROW_HID_BG
            try:
                for w in all_w: w.config(bg=cur)
                for ch in inner.winfo_children(): ch.config(bg=cur)
            except Exception:
                pass
        for w in (body, inner):
            w.bind("<Button-3>", _list_ctx)

    # ════════════════════════════════════════════════════════════════
    # 任务列表渲染
    # ════════════════════════════════════════════════════════════════
    def _f(self)      -> tuple: return ("Microsoft YaHei", self._fs)
    def _f_done(self) -> tuple: return ("Microsoft YaHei", self._fs, "overstrike")

    def _flush_entries(self):
        rows = [w for w in self.sf.winfo_children() if isinstance(w, tk.Frame)]
        for i, outer in enumerate(rows):
            if i >= len(self.tasks):
                break
            for inner in outer.winfo_children():
                if not isinstance(inner, tk.Frame):
                    continue
                for w in inner.winfo_children():
                    if isinstance(w, tk.Entry):
                        try:
                            text = w.get().strip()
                            if text and text != T("placeholder"):
                                self.tasks[i]["text"] = text
                        except tk.TclError:
                            pass

    def _commit_editing(self):
        self._flush_entries()
        self.app.save()

    def _refresh(self, focus_new=False):
        # E: 防抖 — 16ms 内多次调用合并为一次，保留最宽松的 focus_new
        self._refresh_focus_new = self._refresh_focus_new or focus_new
        if self._refresh_id:
            self.win.after_cancel(self._refresh_id)
        self._refresh_id = self.win.after(16, self._do_refresh)

    def _do_refresh(self):
        focus_new = self._refresh_focus_new
        self._refresh_id        = None
        self._refresh_focus_new = False

        pending_new = ""
        if self._new_entry:
            try:
                val = self._new_entry.get()
                if val and val != T("placeholder"):
                    pending_new = val
            except tk.TclError:
                pass

        self._flush_entries()
        for w in self.sf.winfo_children():
            w.destroy()
        self._new_entry = self._new_cb = None
        for i, task in enumerate(self.tasks):
            self._make_row(i, task)
        if not self._locked:
            self._new_entry = self._make_new_row()
            if pending_new and self._new_entry:
                self._new_entry.delete(0, tk.END)
                self._new_entry.insert(0, pending_new)
                self._new_entry.config(fg=FG_TASK)
                if self._new_cb:
                    self._new_cb.config(fg="#AAAAAA")
        if focus_new and self._new_entry:
            self.win.after(30, self._new_entry.focus_set)

    def _make_row(self, idx: int, task: dict):
        done     = task["done"]
        can_edit = not self._locked   # 编辑/删除/hover高亮仅非锁定时可用
        bg, bghv = self._bg, self._bghv

        outer = tk.Frame(self.sf, bg=bg); outer.pack(fill=tk.X)
        inner = tk.Frame(outer, bg=bg, pady=SP1); inner.pack(fill=tk.X, padx=SP2)

        _hvw = [outer, inner]

        def hl_on(e):
            for w in _hvw: w.config(bg=bghv)

        def hl_off(e):
            ox = outer.winfo_rootx(); oy = outer.winfo_rooty()
            if not (ox <= e.x_root < ox + outer.winfo_width() and
                    oy <= e.y_root < oy + outer.winfo_height()):
                for w in _hvw: w.config(bg=bg)

        cb_text = "☑" if done else "☐"
        cb_fg   = COLOR_SUCCESS if done else "#AAAAAA"
        cb = tk.Label(inner, text=cb_text, fg=cb_fg, bg=bg, font=FONT_CB,
                      cursor="hand2")   # 始终可点击
        cb.pack(side=tk.LEFT, padx=(0, SP1+1))
        _hvw.append(cb)
        cb.bind("<ButtonRelease-1>", lambda e, i=idx: self._toggle(i))   # 锁定也可 check
        if can_edit:
            cb.bind("<Enter>", hl_on); cb.bind("<Leave>", hl_off)

        use_label = done or not can_edit
        if use_label:
            font = self._f_done() if done else self._f()
            fg   = FG_DONE if done else FG_TASK
            display_text = self._wrap_text(task["text"])
            lbl  = tk.Label(inner, text=display_text, bg=bg, fg=fg,
                            font=font, anchor="w", justify=tk.LEFT)
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            _hvw.append(lbl)
            if can_edit:
                lbl.bind("<ButtonRelease-1>", lambda e, i=idx: self._toggle(i))
                lbl.bind("<Enter>", hl_on); lbl.bind("<Leave>", hl_off)
        else:
            ent = tk.Entry(inner, font=self._f(), bg=bg, relief="flat",
                           fg=FG_TASK, highlightthickness=0, bd=0,
                           insertbackground=FG_TASK)
            ent.insert(0, task["text"])
            ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
            _hvw.append(ent)
            ent.bind("<FocusOut>", lambda e, i=idx: self._save_text(i, e.widget))
            ent.bind("<Return>",   lambda e: self._focus_new())
            ent.bind("<KeyRelease>", lambda e, i=idx: self._live_save(i, e.widget))
            ent.bind("<Enter>", hl_on); ent.bind("<Leave>", hl_off)

        if can_edit:
            d = tk.Label(inner, text="×", bg=bg, fg="#DDDDDD",
                         font=("Microsoft YaHei", 11), cursor="hand2")
            d.pack(side=tk.RIGHT)
            _hvw.append(d)
            d.bind("<Button-1>", lambda e, i=idx: self._delete(i))
            d.bind("<Enter>", lambda e, b=d: (hl_on(e), b.config(fg=COLOR_DANGER)))
            d.bind("<Leave>", lambda e, b=d: (hl_off(e), b.config(fg="#DDDDDD")))

        if can_edit:
            inner.bind("<Enter>", hl_on); inner.bind("<Leave>", hl_off)

        def _row_ctx(e, i=idx):
            if self._locked: return
            m = tk.Menu(self.win, tearoff=0)
            m.add_command(label=T("menu_del_task"), command=lambda: self._delete(i))
            m.tk_popup(e.x_root, e.y_root)
            try:
                for w in _hvw: w.config(bg=bg)
            except Exception:
                pass
        for w in (outer, inner, cb):
            w.bind("<Button-3>", _row_ctx)
        if use_label:
            lbl.bind("<Button-3>", _row_ctx)
        else:
            ent.bind("<Button-3>", _row_ctx)

    def _make_new_row(self) -> tk.Entry:
        bg = self._bg
        outer = tk.Frame(self.sf, bg=bg); outer.pack(fill=tk.X)
        inner = tk.Frame(outer, bg=bg, pady=SP1); inner.pack(fill=tk.X, padx=SP2)
        self._new_outer = outer

        self._new_cb = tk.Label(inner, text="☐", bg=bg, fg=FG_HINT, font=FONT_CB)
        self._new_cb.pack(side=tk.LEFT, padx=(0, SP1+1))

        ent = tk.Entry(inner, font=self._f(), bg=bg, relief="flat",
                       fg=FG_HINT, highlightthickness=0, bd=0,
                       insertbackground=FG_TASK)
        ent.insert(0, T("placeholder"))
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ent.bind("<FocusIn>",  lambda e: self._new_in(ent))
        ent.bind("<FocusOut>", lambda e: self._new_out(ent))
        ent.bind("<Return>",   lambda e: self._add(ent))
        return ent

    def _wrap_text(self, text: str, max_lines: int = 5) -> str:
        """按当前 canvas 宽度换行，超过 max_lines 行截断加 '……'"""
        font    = tkFont.Font(family="Microsoft YaHei", size=self._fs)
        raw_w   = self.canvas.winfo_width()
        if raw_w <= 1:                         # 首次渲染前 winfo_width 返回 1
            raw_w = self._saved_geo.get("w", 290)
        avail_w = max(80, raw_w - SP2 * 4 - 40)
        ellipsis = "……"
        lines, current = [], ""
        for char in text:
            test = current + char
            if font.measure(test) > avail_w:
                lines.append(current)
                if len(lines) >= max_lines:
                    last = lines[-1]
                    while last and font.measure(last + ellipsis) > avail_w:
                        last = last[:-1]
                    lines[-1] = last + ellipsis
                    return "\n".join(lines)
                current = char
            else:
                current = test
        if current:
            lines.append(current)
        return "\n".join(lines) if lines else text

    def _hide_from_taskbar(self):
        if not _IS_WIN: return
        try:
            GWL_EXSTYLE      = -20
            WS_EX_TOOLWINDOW = 0x00000080
            hwnd  = self._get_hwnd()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                                style | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def _new_in(self, e: tk.Entry):
        if e.get() == T("placeholder"):
            e.delete(0, tk.END)
        e.config(fg=FG_TASK)
        if self._new_cb: self._new_cb.config(fg="#AAAAAA")

    def _new_out(self, e: tk.Entry):
        text = e.get().strip()
        if text and text != T("placeholder"):
            self.tasks.append({"text": text, "done": False})
            self.app.save()
            try:
                e.delete(0, tk.END)   # 清空后 _refresh 不会把内容放回新输入框
            except tk.TclError:
                pass
            self._refresh(focus_new=False)
        elif not text:
            e.delete(0, tk.END); e.insert(0, T("placeholder")); e.config(fg=FG_HINT)
            if self._new_cb: self._new_cb.config(fg=FG_HINT)

    def _focus_new(self):
        if self._new_entry: self._new_entry.focus_set()

    # ════════════════════════════════════════════════════════════════
    # 任务操作
    # ════════════════════════════════════════════════════════════════
    def _add(self, ent: tk.Entry):
        text = ent.get().strip()
        if not text or text == T("placeholder"): return
        try:
            ent.delete(0, tk.END)
        except tk.TclError:
            pass
        self.tasks.append({"text": text, "done": False})
        self.app.save(); self._refresh(focus_new=True)

    def _live_save(self, idx: int, ent: tk.Entry):
        if idx >= len(self.tasks): return
        try:
            text = ent.get().strip()
        except tk.TclError:
            return
        if text:
            self.tasks[idx]["text"] = text

    def _save_text(self, idx: int, ent: tk.Entry):
        if idx >= len(self.tasks): return
        try: text = ent.get().strip()
        except tk.TclError: return
        if text:
            if self.tasks[idx]["text"] != text:
                self.tasks[idx]["text"] = text; self.app.save()
            # G: 若该行曾挂起删除，取消它
            aid = self._pending_delete_ids.pop(idx, None)
            if aid:
                self.win.after_cancel(aid)
        else:
            # G: 每个 idx 独立管理，不互相覆盖
            aid = self._pending_delete_ids.get(idx)
            if aid:
                self.win.after_cancel(aid)
            self._pending_delete_ids[idx] = self.win.after(
                0, lambda: self._deferred_delete(idx))

    def _deferred_delete(self, idx: int):
        self._pending_delete_ids.pop(idx, None)   # G: 精准移除
        if idx < len(self.tasks):
            self._delete(idx)

    def _toggle(self, idx: int):
        if idx >= len(self.tasks): return
        # G: 取消该行的挂起删除
        aid = self._pending_delete_ids.pop(idx, None)
        if aid:
            self.win.after_cancel(aid)
        self.tasks[idx]["done"] = not self.tasks[idx]["done"]
        self.app.save(); self._refresh()

    def _delete(self, idx: int):
        if idx < len(self.tasks):
            for aid in list(self._pending_delete_ids.values()):
                self.win.after_cancel(aid)
            self._pending_delete_ids.clear()
            task = self.tasks.pop(idx)
            self.app.save()
            # 直接同步重建 DOM，保证 toast 在布局稳定后显示
            if self._refresh_id:
                self.win.after_cancel(self._refresh_id)
                self._refresh_id = None
                self._refresh_focus_new = False
            self._do_refresh()
            self._show_undo_toast(task, idx)

    def _clear_done(self):
        self.tasks = [t for t in self.tasks if not t["done"]]
        self.app.save()
        # 同步重建，配合 _confirm_clear_done 里的 _show_clear_undo_toast
        if self._refresh_id:
            self.win.after_cancel(self._refresh_id)
            self._refresh_id = None
            self._refresh_focus_new = False
        self._do_refresh()

    # ════════════════════════════════════════════════════════════════
    # 锁定
    # ════════════════════════════════════════════════════════════════
    def _toggle_lock(self):
        self._locked = not self._locked
        if self._locked:
            self.lock_btn.config(bg=ACCENT)
            self._rsz_canvas.config(cursor="arrow")
            self._lock_strip.config(bg=ACCENT)
            # 按钮不立即显示，等鼠标 hover 时再浮现
            self._animate_tb(False)   # 立即收起工具栏
        else:
            self.lock_btn.config(bg=self._tbg)
            self._rsz_canvas.config(cursor="sizing")
            self._lock_strip.config(bg=self._bg)
            self._lock_icon_btn.place_forget()
            self._animate_tb(True)   # 解锁后恢复工具栏
        self._refresh()

    # ════════════════════════════════════════════════════════════════
    # 置顶 / 拖拽 / 缩放
    # ════════════════════════════════════════════════════════════════
    def _toggle_topmost(self):
        self._topmost = not self._topmost
        self.win.attributes("-topmost", self._topmost)
        self.pin_btn.config(
            bg=ACCENT if self._topmost else self._tbg,
            fg="#FFFFFF" if self._topmost else self._tbfg)
        self.app.save()

    def _drag_start(self, e):
        if self._locked: return
        self._dx, self._dy = e.x, e.y

    def _drag_move(self, e):
        if self._locked: return
        x = self.win.winfo_x() + e.x - self._dx
        y = self.win.winfo_y() + e.y - self._dy
        self.win.geometry(f"+{x}+{y}")

    def _resize_start(self, e):
        if self._locked: return
        self._rsx, self._rsy = e.x_root, e.y_root
        self._rsw, self._rsh = self.win.winfo_width(), self.win.winfo_height()

    def _resize_move(self, e):
        if self._locked: return
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
        x  = d.get("x", sw - w - 20 + self._offset)
        y  = d.get("y", 60 + self._offset)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        # P2: 圆角 + 投影
        self.win.after(80, self._apply_rounded)
        self.win.after(80, self._apply_shadow)
        self.win.after(500, self._poll_edge)

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
            "edge_snap": self._edge_snap,
        }

    # ════════════════════════════════════════════════════════════════
    # 屏幕边缘自动收缩
    # ════════════════════════════════════════════════════════════════
    def _set_edge_snap(self, on: bool):
        self._edge_snap = on
        if not on and self._edge_collapsed:
            self._restore_from_edge()
        self.app.save()

    def _poll_edge(self):
        if not self._edge_snap or self.win.state() == "withdrawn":
            self._edge_poll_id = self.win.after(300, self._poll_edge)
            return
        try:
            wx, wy = self.win.winfo_x(), self.win.winfo_y()
            ww, wh = self.win.winfo_width(), self.win.winfo_height()
            if self._edge_collapsed and not self._edge_peeking and self._pre_edge_geo:
                ox, oy, ow, oh = self._pre_edge_geo
                check_x, check_y, check_w, check_h = ox, oy, ow, oh
            else:
                check_x, check_y, check_w, check_h = wx, wy, ww, wh
            ml, mt, mr, mb = self._monitor_workarea()
            at_left   = check_x <= ml + EDGE_THRESHOLD
            at_right  = check_x + check_w >= mr - EDGE_THRESHOLD
            at_top    = check_y <= mt + EDGE_THRESHOLD
            at_bottom = check_y + check_h >= mb - EDGE_THRESHOLD
            at_edge   = at_left or at_right or at_top or at_bottom

            if at_edge and not self._edge_collapsed:
                self._edge_delay_cnt += 1
                if self._edge_delay_cnt >= 3:
                    self._edge_side = ("left"   if at_left  else
                                       "right"  if at_right else
                                       "top"    if at_top   else "bottom")
                    self._collapse_to_edge()
                    self._edge_delay_cnt = 0
            elif not at_edge:
                self._edge_delay_cnt = 0
                if self._edge_collapsed:
                    self._restore_from_edge()
            else:
                self._edge_delay_cnt = 0
                # peeking 状态下的收缩由 <Leave> timer 驱动，poll 不干预
        except Exception:
            pass
        self._edge_poll_id = self.win.after(300, self._poll_edge)

    def _animate_edge_slide(self, sx, sy, tx, ty, w, h, step):
        t = step / EDGE_ANIM_STEPS
        e = 1 - (1 - t) ** 3
        cx = int(sx + (tx - sx) * e)
        cy = int(sy + (ty - sy) * e)
        self.win.geometry(f"{w}x{h}+{cx}+{cy}")
        if step < EDGE_ANIM_STEPS:
            self._edge_anim_id = self.win.after(
                EDGE_ANIM_MS,
                lambda: self._animate_edge_slide(sx, sy, tx, ty, w, h, step + 1))
        else:
            self._edge_anim_id = None

    def _collapse_to_edge(self):
        if self._edge_leave_id:
            self.win.after_cancel(self._edge_leave_id)
            self._edge_leave_id = None
        if not self._pre_edge_geo:
            self._pre_edge_geo = (self.win.winfo_x(), self.win.winfo_y(),
                                  self.win.winfo_width(), self.win.winfo_height())
        self._edge_collapsed = True
        self._edge_peeking   = False

        x, y, w, h = self._pre_edge_geo
        ml, mt, mr, mb = self._monitor_workarea()
        side = self._edge_side

        # Apple 样式：滑出屏幕，仅保留 EDGE_STRIP_WIDTH px 可见
        if side == "left":
            tx, ty = ml - (w - EDGE_STRIP_WIDTH), y
        elif side == "right":
            tx, ty = mr - EDGE_STRIP_WIDTH, y
        elif side == "top":
            tx, ty = x, mt - (h - EDGE_STRIP_WIDTH)
        else:
            tx, ty = x, mb - EDGE_STRIP_WIDTH

        if self._edge_anim_id:
            self.win.after_cancel(self._edge_anim_id)
        cx, cy = self.win.winfo_x(), self.win.winfo_y()
        self._animate_edge_slide(cx, cy, tx, ty, w, h, 0)
        self.win.after(30, self._apply_rounded)

        self._edge_cooldown = True
        self.win.after(600, lambda: setattr(self, "_edge_cooldown", False))
        self.win.bind("<Enter>", lambda e: self._edge_peek(), add="+")

    def _edge_peek(self):
        if not self._edge_collapsed or self._edge_peeking: return
        if self._edge_cooldown: return
        self._edge_peeking = True
        if self._pre_edge_geo:
            ox, oy, ow, oh = self._pre_edge_geo
            if self._edge_anim_id:
                self.win.after_cancel(self._edge_anim_id)
            cx, cy = self.win.winfo_x(), self.win.winfo_y()
            self._animate_edge_slide(cx, cy, ox, oy, ow, oh, 0)
        self.win.after(30, self._apply_rounded)
        self.win.bind("<Leave>", self._edge_on_leave, add="+")

    def _edge_on_leave(self, e):
        if not self._edge_peeking: return
        try:
            wx = self.win.winfo_rootx(); wy = self.win.winfo_rooty()
            ww = self.win.winfo_width(); wh = self.win.winfo_height()
            if wx <= e.x_root <= wx + ww and wy <= e.y_root <= wy + wh:
                return
        except Exception:
            return
        if self._edge_leave_id:
            self.win.after_cancel(self._edge_leave_id)
        self._edge_leave_id = self.win.after(1000, self._edge_collapse_after_leave)

    def _edge_collapse_after_leave(self):
        self._edge_leave_id = None
        if self._edge_peeking:
            self._edge_peeking = False
            self._collapse_to_edge()

    def _restore_from_edge(self):
        if not self._edge_collapsed: return
        if self._edge_anim_id:
            self.win.after_cancel(self._edge_anim_id)
            self._edge_anim_id = None
        self._edge_collapsed = False
        self._edge_peeking   = False
        if self._pre_edge_geo:
            ox, oy, ow, oh = self._pre_edge_geo
            self.win.geometry(f"{ow}x{oh}+{ox}+{oy}")
            self._pre_edge_geo = None
        self._edge_side = None
        self.win.after(30, self._apply_rounded)

    def _cleanup(self):
        """M: 删除便签前取消所有 after 任务、关闭子弹窗，防止内存泄漏。"""
        p = self._list_popup
        if p:
            try:
                if p.winfo_exists():
                    p.destroy()
            except Exception:
                pass
        for attr in ("_round_after", "_tb_anim_id", "_tb_hide_id",
                     "_toast_after", "_sb_hide_id", "_refresh_id",
                     "_edge_poll_id", "_edge_leave_id", "_edge_anim_id"):
            aid = getattr(self, attr, None)
            if aid:
                try:
                    self.win.after_cancel(aid)
                except Exception:
                    pass
        for aid in list(self._pending_delete_ids.values()):
            try:
                self.win.after_cancel(aid)
            except Exception:
                pass
        self._pending_delete_ids.clear()


# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if _IS_WIN:
        if not _single_instance():
            sys.exit(0)
    else:
        if not _single_instance_mac():
            sys.exit(0)
    App().run()
