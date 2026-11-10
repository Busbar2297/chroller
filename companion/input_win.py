"""Real mouse and keyboard input on Windows. No DevTools Protocol."""

import ctypes
import sys
import time
from ctypes import wintypes

class FocusError(RuntimeError):
    pass


MODIFIERS = {
    "control": 0x11,
    "ctrl": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "meta": 0x5B,
    "win": 0x5B,
    "command": 0x5B,
}

NAMED_KEYS = {
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "arrowup": 0x26,
    "arrowdown": 0x28,
    "arrowleft": 0x25,
    "arrowright": 0x27,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "space": 0x20,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
}

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

_DPI_READY = False


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]


def absolute_from_physical(px, py, origin_x, origin_y, width, height):
    span_x = max(int(width) - 1, 1)
    span_y = max(int(height) - 1, 1)
    ax = int(round((px - origin_x) * 65535 / span_x))
    ay = int(round((py - origin_y) * 65535 / span_y))
    return max(0, min(65535, ax)), max(0, min(65535, ay))


def parse_key(combo):
    parts = [part.strip().lower() for part in str(combo).split("+") if part.strip()]
    if not parts:
        raise FocusError("Key is empty.")
    mods = []
    for part in parts[:-1]:
        if part not in MODIFIERS:
            raise FocusError("Unknown modifier.")
        mods.append(MODIFIERS[part])
    key = parts[-1]
    if key in NAMED_KEYS:
        vk = NAMED_KEYS[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise FocusError("Unknown key.")
    return mods, vk


def _enable_dpi():
    global _DPI_READY
    if _DPI_READY or sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                return
    _DPI_READY = True


def _send(inputs):
    count = len(inputs)
    array = (INPUT * count)(*inputs)
    sent = ctypes.windll.user32.SendInput(count, array, ctypes.sizeof(INPUT))
    if sent != count:
        raise FocusError("Windows did not accept the input event.")


def _mouse(flags, x=0, y=0):
    event = INPUT(type=INPUT_MOUSE)
    event.union.mi.dx = x
    event.union.mi.dy = y
    event.union.mi.dwFlags = flags
    return event


def _key(vk=0, scan=0, flags=0):
    event = INPUT(type=INPUT_KEYBOARD)
    event.union.ki.wVk = vk
    event.union.ki.wScan = scan
    event.union.ki.dwFlags = flags
    return event


def _virtual_metrics():
    user32 = ctypes.windll.user32
    return (
        user32.GetSystemMetrics(76),
        user32.GetSystemMetrics(77),
        user32.GetSystemMetrics(78),
        user32.GetSystemMetrics(79),
    )


def _foreground_is(hwnd):
    user32 = ctypes.windll.user32
    current = user32.GetForegroundWindow()
    while current:
        if current == hwnd:
            return True
        current = user32.GetParent(current)
    return False


def _find_hwnd(window, dpr):
    user32 = ctypes.windll.user32
    left = int(round(window["left"] * dpr))
    top = int(round(window["top"] * dpr))
    right = int(round((window["left"] + window["width"]) * dpr))
    bottom = int(round((window["top"] + window["height"]) * dpr))
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        class_name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, class_name, 64)
        if class_name.value != "Chrome_WidgetWin_1":
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        overlap_w = min(rect.right, right) - max(rect.left, left)
        overlap_h = min(rect.bottom, bottom) - max(rect.top, top)
        if overlap_w > 40 and overlap_h > 40:
            found.append((overlap_w * overlap_h, hwnd))
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        return None
    found.sort(reverse=True)
    return found[0][1]


def focus_window(hwnd):
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if _foreground_is(hwnd) and not user32.IsIconic(hwnd):
        return
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    foreground = user32.GetForegroundWindow()
    current = kernel32.GetCurrentThreadId()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    attached_foreground = False
    attached_target = False
    if foreground_thread and foreground_thread != current:
        attached_foreground = bool(user32.AttachThreadInput(current, foreground_thread, True))
    if target_thread and target_thread != current:
        attached_target = bool(user32.AttachThreadInput(current, target_thread, True))
    user32.ShowWindow(hwnd, 5)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    if attached_target:
        user32.AttachThreadInput(current, target_thread, False)
    if attached_foreground:
        user32.AttachThreadInput(current, foreground_thread, False)
    deadline = time.time() + 0.4
    while time.time() < deadline:
        if _foreground_is(hwnd):
            return
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.03)
    raise FocusError("Chrome did not take focus. Click the Chrome window once and retry.")


def _focus_from_payload(payload):
    window = payload.get("window") or {}
    if not {"left", "top", "width", "height"} <= set(window):
        raise FocusError("Chrome window bounds were missing.")
    dpr = float(payload.get("dpr") or 1)
    hwnd = _find_hwnd(window, dpr)
    if not hwnd:
        raise FocusError("Chrome window was not found.")
    focus_window(hwnd)


def click_inside_page(payload):
    window = payload.get("window") or {}
    try:
        x = float(payload["x"])
        y = float(payload["y"])
        left = float(window["left"])
        top = float(window["top"])
        right = left + float(window["width"])
        bottom = top + float(window["height"])
    except (KeyError, TypeError, ValueError):
        return False
    if y < top + 48 and x > right - 180:
        return False
    return left + 4 < x < right - 4 and top + 48 < y < bottom - 4


def click_at(css_x, css_y, dpr, button="left"):
    px = int(round(float(css_x) * float(dpr)))
    py = int(round(float(css_y) * float(dpr)))
    origin_x, origin_y, width, height = _virtual_metrics()
    ax, ay = absolute_from_physical(px, py, origin_x, origin_y, width, height)
    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    down = MOUSEEVENTF_LEFTDOWN if button != "right" else MOUSEEVENTF_RIGHTDOWN
    up = MOUSEEVENTF_LEFTUP if button != "right" else MOUSEEVENTF_RIGHTUP
    _send([_mouse(flags, ax, ay)])
    time.sleep(0.04)
    _send([_mouse(flags | down, ax, ay)])
    time.sleep(0.04)
    _send([_mouse(flags | up, ax, ay)])


def type_text(text):
    events = []
    for char in text:
        if char in ("\r", "\n"):
            events.append(_key(vk=0x0D))
            events.append(_key(vk=0x0D, flags=KEYEVENTF_KEYUP))
            continue
        code = ord(char)
        events.append(_key(scan=code, flags=KEYEVENTF_UNICODE))
        events.append(_key(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    if events:
        _send(events)


def press_key(combo):
    mods, vk = parse_key(combo)
    events = [_key(vk=mod) for mod in mods]
    events.append(_key(vk=vk))
    events.append(_key(vk=vk, flags=KEYEVENTF_KEYUP))
    events.extend(_key(vk=mod, flags=KEYEVENTF_KEYUP) for mod in reversed(mods))
    _send(events)


def perform(payload):
    if sys.platform != "win32":
        raise FocusError("OS input is only implemented on Windows.")
    _enable_dpi()
    kind = payload.get("kind")
    _focus_from_payload(payload)
    if kind == "click":
        raise FocusError("OS click is disabled.")
    if kind == "type":
        type_text(payload.get("text") or "")
        return
    if kind == "key":
        press_key(payload.get("key") or "")
        return
    raise FocusError("Unknown input kind.")
