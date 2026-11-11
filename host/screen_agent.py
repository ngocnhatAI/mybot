"""Chạy TRỰC TIẾP trên Windows (ngoài Docker) để bot bật/tắt màn hình máy này.

    python host/screen_agent.py

Đọc SCREEN_TOKEN (bắt buộc) và SCREEN_PORT (mặc định 8765) từ .env hoặc biến môi trường.
Chỉ nhận kết nối khi kèm đúng token. Mặc định nghe ở 127.0.0.1 (Docker Desktop chuyển
host.docker.internal vào đây); đặt SCREEN_BIND=0.0.0.0 nếu cần.
"""

import ctypes
import hmac
import json
import os
import sys
import threading
import time
import uuid
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER = 0xFFFF, 0x0112, 0xF170
MONITOR_OFF = 2
SMTO_ABORTIFHUNG = 0x0002
MOUSEEVENTF_MOVE = 0x0001
VK_SHIFT, KEYEVENTF_KEYUP = 0x10, 0x0002


_own_hwnd = 0  # cửa sổ ẩn của script (tạo trong _watch_display_state)


def _broadcast_monitor_off() -> None:
    # Dự phòng khi chưa có cửa sổ riêng. Không dùng SendMessageW: quảng bá sẽ treo nếu có cửa sổ
    # không phản hồi; thời gian chờ tính cho TỪNG cửa sổ nên có thể lâu vài giây.
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_OFF,
                                             SMTO_ABORTIFHUNG, 500, None)


def _monitor_off() -> None:
    # Gửi vào cửa sổ ẩn của chính script: tắt tức thì, không chờ cửa sổ khác, nên không thể
    # đến muộn và đè lên lệnh bật.
    if _own_hwnd:
        post = ctypes.windll.user32.PostMessageW
        post.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        post(_own_hwnd, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_OFF)
    else:
        threading.Thread(target=_broadcast_monitor_off, daemon=True).start()


def _wake_monitor() -> None:
    # Windows không có lệnh "bật" trực tiếp: giả lập chuột nhúc nhích + nhấn Shift để đánh thức màn hình.
    # (Chỉ nhúc nhích 1px thì không đủ đánh thức.) Shift không gõ ra ký tự nào.
    user32 = ctypes.windll.user32
    user32.mouse_event(MOUSEEVENTF_MOVE, 5, 5, 0, 0)
    time.sleep(0.1)
    user32.mouse_event(MOUSEEVENTF_MOVE, -5, -5, 0, 0)
    user32.keybd_event(VK_SHIFT, 0, 0, 0)
    user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)


# ---------- khóa chuột và bàn phím ----------
# Dùng hook bàn phím/chuột mức thấp (không cần quyền admin): khi khóa, mọi thao tác bị nuốt,
# trừ tổ hợp Ctrl+Shift+N để mở khóa. Ctrl+Alt+Del luôn đi qua (Windows không cho chặn).
# Hook chỉ tồn tại khi đang khóa, và mất ngay khi script dừng, nên không thể khóa máy vĩnh viễn.
WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP, WM_QUIT = 0x0100, 0x0101, 0x0104, 0x0105, 0x0012
CTRL_KEYS, SHIFT_KEYS, VK_N = {0x11, 0xA2, 0xA3}, {0x10, 0xA0, 0xA1}, 0x4E

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class _KbdLLHook(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class InputLock:
    def __init__(self) -> None:
        self.locked = False
        self.on_hotkey = lambda: None  # gọi khi bấm Ctrl+Shift+N lúc đang khóa
        self._guard = threading.Lock()
        self._thread_id = 0
        self._held: set[int] = set()

    def lock(self) -> None:
        with self._guard:
            if self.locked:
                return
            self.locked, self._held = True, set()
            ready = threading.Event()
            threading.Thread(target=self._run, args=(ready,), daemon=True).start()
            ready.wait(2)

    def unlock(self) -> None:
        with self._guard:
            if not self.locked:
                return
            self.locked = False
            if self._thread_id:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _run(self, ready: threading.Event) -> None:
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

        def on_key(code, wparam, lparam):
            if code < 0 or not self.locked:
                return user32.CallNextHookEx(None, code, wparam, lparam)
            vk = ctypes.cast(lparam, ctypes.POINTER(_KbdLLHook)).contents.vkCode
            if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                self._held.add(vk)
                if vk == VK_N and self._held & CTRL_KEYS and self._held & SHIFT_KEYS:
                    # không làm việc nặng trong hook (Windows gỡ hook nếu trả lời chậm)
                    threading.Thread(target=self.on_hotkey, daemon=True).start()
            elif wparam in (WM_KEYUP, WM_SYSKEYUP):
                self._held.discard(vk)
            return 1  # nuốt phím

        def on_mouse(code, wparam, lparam):
            if code < 0 or not self.locked:
                return user32.CallNextHookEx(None, code, wparam, lparam)
            return 1  # nuốt mọi di chuyển / bấm / cuộn chuột

        self._thread_id = kernel32.GetCurrentThreadId()
        key_proc, mouse_proc = HOOKPROC(on_key), HOOKPROC(on_mouse)  # giữ tham chiếu, tránh bị thu gom
        hinst = kernel32.GetModuleHandleW(None)
        hooks = [user32.SetWindowsHookExW(WH_KEYBOARD_LL, key_proc, hinst, 0),
                 user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, hinst, 0)]
        ready.set()
        msg = wintypes.MSG()
        while self.locked and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        for h in hooks:
            if h:
                user32.UnhookWindowsHookEx(h)
        self._thread_id = 0


input_lock = InputLock()


def screen_off() -> None:
    """Tắt màn hình và khóa chuột, bàn phím (mở bằng Ctrl+Shift+N hoặc /screen on)."""
    input_lock.lock()
    _monitor_off()


def screen_on() -> None:
    input_lock.unlock()
    _wake_monitor()


input_lock.on_hotkey = screen_on


# ---------- theo dõi trạng thái màn hình ----------
# Windows báo mỗi khi màn hình đổi trạng thái (kể cả khi bạn lắc chuột bật lại), nên không đoán mò.
WM_POWERBROADCAST, PBT_POWERSETTINGCHANGE = 0x0218, 0x8013
DISPLAY_STATE_NAMES = {0: "off", 1: "on", 2: "dimmed"}
display_state = "unknown"


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class _PowerBroadcastSetting(ctypes.Structure):
    _fields_ = [("PowerSetting", _GUID), ("DataLength", wintypes.DWORD), ("Data", ctypes.c_ubyte * 1)]


def _guid(text: str) -> _GUID:
    u = uuid.UUID(text)
    return _GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


def _watch_display_state() -> None:
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t

    def proc(hwnd, msg, wparam, lparam):
        global display_state
        if msg == WM_POWERBROADCAST and wparam == PBT_POWERSETTINGCHANGE:
            setting = ctypes.cast(lparam, ctypes.POINTER(_PowerBroadcastSetting)).contents
            display_state = DISPLAY_STATE_NAMES.get(setting.Data[0], "unknown")
            if display_state == "on" and input_lock.locked:
                _monitor_off()  # đang khóa mà màn hình bị đánh thức (chuột rung...): tắt lại
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.RegisterPowerSettingNotification.argtypes = [wintypes.HANDLE, ctypes.POINTER(_GUID), wintypes.DWORD]
    user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASS()
    wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = WNDPROC(proc), hinst, "MybotScreenWatcher"
    user32.RegisterClassW(ctypes.byref(wc))
    # Cửa sổ thường nhưng không hiện (không gọi ShowWindow): nhận được WM_SYSCOMMAND tắt màn hình.
    hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "mybot", 0, 0, 0, 0, 0, None, None, hinst, None)
    global _own_hwnd
    _own_hwnd = hwnd or 0
    guid = _guid("6fe69556-704a-47a0-8f24-c28d936fda47")  # GUID_CONSOLE_DISPLAY_STATE
    user32.RegisterPowerSettingNotification(hwnd, ctypes.byref(guid), 0)  # 0 = DEVICE_NOTIFY_WINDOW_HANDLE
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


ACTIONS = {"off": screen_off, "on": screen_on}


# ---------- UltraViewer ----------
# ID và mật khẩu đọc thẳng từ cửa sổ UltraViewer: 2 ô chỉ-đọc ở cột trái (ID ở trên, mật khẩu ở dưới).
# Đọc được cả khi cửa sổ đang thu nhỏ xuống khay hệ thống.
ULTRAVIEWER_EXE = os.environ.get("ULTRAVIEWER_EXE", r"C:\Program Files (x86)\UltraViewer\UltraViewer_Desktop.exe")
WM_GETTEXT, WM_GETTEXTLENGTH, ES_READONLY = 0x000D, 0x000E, 0x0800
_ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _win_text(h) -> str:
    user32 = ctypes.windll.user32
    user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                           wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    n = ctypes.c_size_t()
    if not user32.SendMessageTimeoutW(h, WM_GETTEXTLENGTH, 0, 0, SMTO_ABORTIFHUNG, 1000, ctypes.byref(n)):
        return ""
    buf = ctypes.create_unicode_buffer(n.value + 1)
    user32.SendMessageTimeoutW(h, WM_GETTEXT, n.value + 1, ctypes.cast(buf, ctypes.c_void_p).value,
                               SMTO_ABORTIFHUNG, 1000, ctypes.byref(n))
    return buf.value


def _win_class(h) -> str:
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(h, buf, 256)
    return buf.value


def _children(h) -> list:
    out = []
    ctypes.windll.user32.EnumChildWindows(h, _ENUMPROC(lambda c, _: out.append(c) or True), 0)
    return out


def ultraviewer_credentials() -> tuple[str, str] | None:
    """(ID, mật khẩu) đang hiện trên UltraViewer, hoặc None nếu chưa chạy / chưa có ID."""
    user32 = ctypes.windll.user32
    user32.GetWindowLongW.restype = ctypes.c_long
    forms = []
    user32.EnumWindows(_ENUMPROC(lambda h, _: forms.append(h) or True), 0)
    for form in forms:
        if _win_class(form) != "ThunderRT6FormDC" or not _win_text(form).startswith("UltraViewer "):
            continue
        boxes = []
        for c in _children(form):
            if "EDIT" in _win_class(c).upper() and user32.GetWindowLongW(c, -16) & ES_READONLY:
                text = _win_text(c).strip()
                if text:
                    r = wintypes.RECT()
                    user32.GetWindowRect(c, ctypes.byref(r))
                    boxes.append((r.top, r.left, text))
        boxes.sort()
        if len(boxes) >= 2 and boxes[0][2].replace(" ", "").isdigit():
            return boxes[0][2], boxes[1][2]
    return None


def ultraviewer_start_and_read(timeout: float = 45) -> dict:
    """Chưa chạy thì mở UltraViewer, rồi chờ tới khi có ID (cần kết nối máy chủ UltraViewer)."""
    creds = ultraviewer_credentials()
    started = False
    if creds is None:
        if not os.path.exists(ULTRAVIEWER_EXE):
            return {"error": f"không thấy {ULTRAVIEWER_EXE}"}
        os.startfile(ULTRAVIEWER_EXE)  # nếu đã chạy mà chưa có ID, UltraViewer chỉ hiện lại cửa sổ
        started = True
        deadline = time.time() + timeout
        while creds is None and time.time() < deadline:
            time.sleep(1)
            creds = ultraviewer_credentials()
    if creds is None:
        return {"error": "UltraViewer chưa hiện ID (có thể chưa kết nối được máy chủ)", "started": started}
    return {"id": creds[0], "password": creds[1], "started": started}


def load_env() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Handler(BaseHTTPRequestHandler):
    token = ""

    def _authorized(self) -> bool:
        return hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {self.token}")

    def do_GET(self) -> None:
        if not self._authorized():
            return self._reply(401, "unauthorized")
        path = self.path.strip("/")
        if path == "ultraviewer":
            return self._reply(200, json.dumps(ultraviewer_start_and_read(), ensure_ascii=False))
        if path != "screen/status":
            return self._reply(404, "unknown action")
        self._reply(200, f"{display_state} locked" if input_lock.locked else display_state)

    def do_POST(self) -> None:
        if not self._authorized():
            return self._reply(401, "unauthorized")
        action = ACTIONS.get(self.path.strip("/").removeprefix("screen/"))
        if action is None:
            return self._reply(404, "unknown action")
        try:
            action()
        except Exception as e:  # noqa: BLE001
            return self._reply(500, f"error: {e}")
        self._reply(200, "ok")

    def _reply(self, code: int, body: str) -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args) -> None:
        pass


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Script này chỉ chạy trên Windows.")
    load_env()
    token = os.environ.get("SCREEN_TOKEN", "")
    if len(token) < 16:
        raise SystemExit("Thiếu SCREEN_TOKEN (>= 16 ký tự) trong .env")
    Handler.token = token
    threading.Thread(target=_watch_display_state, daemon=True).start()
    bind, port = os.environ.get("SCREEN_BIND", "127.0.0.1"), int(os.environ.get("SCREEN_PORT", "8765"))
    print(f"screen agent nghe ở {bind}:{port}")
    ThreadingHTTPServer((bind, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
