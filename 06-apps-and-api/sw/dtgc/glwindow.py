"""A resizable window drawn by the PC's own graphics card, using only what Windows already includes.

Usage:
    from sw.dtgc.glwindow import Window
    window = Window("Title", 1280, 720)
    while window.poll():
        ...OpenGL calls through glwindow.gl...
        window.present()
    window.close()

Python's ctypes calls the Win32 and OpenGL libraries directly, so there is nothing to install. Only OpenGL 1.1
is used, which every Windows graphics driver has. F11 or double-click switches full screen, Esc leaves it.
"""
import ctypes
import sys
from ctypes import wintypes

if sys.platform != "win32":
    raise ImportError("the laptop window needs Windows; use `python -m sw.dtgc emulator --window` elsewhere")

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")
kernel32 = ctypes.WinDLL("kernel32")
gl = ctypes.WinDLL("opengl32")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_CLIPCHILDREN = 0x02000000
WS_CLIPSIBLINGS = 0x04000000
GWL_STYLE = -16
SWP_FRAMECHANGED = 0x0020
SWP_NOZORDER = 0x0004
SW_SHOW = 5
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_SIZE = 0x0005
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_LBUTTONDBLCLK = 0x0203
CS_OWNDC = 0x0020
CS_DBLCLKS = 0x0008
PM_REMOVE = 1
MONITOR_DEFAULTTONEAREST = 2
PFD_DRAW_TO_WINDOW, PFD_SUPPORT_OPENGL, PFD_DOUBLEBUFFER = 0x4, 0x20, 0x1
VK_NAMES = {0x26: "up", 0x57: "up", 0x28: "down", 0x53: "down", 0x25: "left", 0x41: "left", 0x27: "right", 0x44: "right",
            0x20: "fire", 0x0D: "fire", 0x58: "fire"}   # space, Enter, X: use the kart's item
VK_F11, VK_ESCAPE = 0x7A, 0x1B

# Asking the driver for smoothed edges. These come from the WGL_ARB_multisample extension.
WGL_DRAW_TO_WINDOW, WGL_SUPPORT_OPENGL, WGL_DOUBLE_BUFFER = 0x2001, 0x2010, 0x2011
WGL_PIXEL_TYPE, WGL_TYPE_RGBA, WGL_COLOR_BITS, WGL_DEPTH_BITS = 0x2013, 0x202B, 0x2014, 0x2022
WGL_SAMPLE_BUFFERS, WGL_SAMPLES = 0x2041, 0x2042

GL_VENDOR, GL_RENDERER, GL_VERSION = 0x1F00, 0x1F01, 0x1F02


class _WindowClass(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HANDLE), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class _PixelFormat(ctypes.Structure):
    _fields_ = [("nSize", wintypes.WORD), ("nVersion", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("iPixelType", ctypes.c_ubyte), ("cColorBits", ctypes.c_ubyte), ("middle", ctypes.c_ubyte * 13),
                ("cDepthBits", ctypes.c_ubyte), ("more", ctypes.c_ubyte * 4), ("tail", wintypes.DWORD * 3)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.LoadCursorW.restype = wintypes.HANDLE
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.RegisterClassW.argtypes = [ctypes.POINTER(_WindowClass)]
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
gdi32.ChoosePixelFormat.argtypes = [wintypes.HDC, ctypes.POINTER(_PixelFormat)]
gdi32.SetPixelFormat.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.POINTER(_PixelFormat)]
gdi32.DescribePixelFormat.argtypes = [wintypes.HDC, ctypes.c_int, wintypes.UINT, ctypes.POINTER(_PixelFormat)]
gdi32.SwapBuffers.argtypes = [wintypes.HDC]
gl.wglCreateContext.restype = ctypes.c_void_p
gl.wglCreateContext.argtypes = [wintypes.HDC]
gl.wglMakeCurrent.argtypes = [wintypes.HDC, ctypes.c_void_p]
gl.wglDeleteContext.argtypes = [ctypes.c_void_p]
gl.wglGetProcAddress.restype = ctypes.c_void_p
gl.wglGetProcAddress.argtypes = [ctypes.c_char_p]
gl.glGetString.restype = ctypes.c_char_p
gl.glGetString.argtypes = [ctypes.c_uint]

_CHOOSE_FORMAT = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HDC, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_float),
                                    wintypes.UINT, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(wintypes.UINT))
_SWAP_INTERVAL = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_int)
_CLASS_NAME = "DtgcLaptopWindow"


def _basic_format():
    return _PixelFormat(nSize=ctypes.sizeof(_PixelFormat), nVersion=1,
                        dwFlags=PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER, iPixelType=0, cColorBits=32, cDepthBits=24)


class Window:
    def __init__(self, title, width=1280, height=720, fullscreen=False, vsync=True, samples=4, visible=True):
        user32.SetProcessDPIAware()  # one real screen pixel per window pixel, so big screens stay sharp
        self.instance = kernel32.GetModuleHandleW(None)
        self.keys = set()
        self.open = True
        self.is_fullscreen = False
        self._saved = None
        self._procedure = WNDPROC(self._on_message)  # kept here so Python does not free it while Windows holds it
        window_class = _WindowClass(style=CS_OWNDC | CS_DBLCLKS, lpfnWndProc=self._procedure, hInstance=self.instance,
                                    hCursor=user32.LoadCursorW(None, ctypes.c_void_p(32512)), lpszClassName=_CLASS_NAME)
        user32.UnregisterClassW(_CLASS_NAME, self.instance)
        if not user32.RegisterClassW(ctypes.byref(window_class)):
            raise OSError(f"could not register the window class: {ctypes.get_last_error()}")
        self.samples = 0
        format_number = self._find_smooth_format(samples) if samples else 0
        style = WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN | WS_CLIPSIBLINGS | (WS_VISIBLE if visible else 0)
        self.hwnd = user32.CreateWindowExW(0, _CLASS_NAME, title, style, 60, 60, width, height, None, None, self.instance, None)
        if not self.hwnd:
            raise OSError(f"could not create the window: {ctypes.get_last_error()}")
        self.title = title
        self.hdc = user32.GetDC(self.hwnd)
        self.context = self._make_context(self.hdc, format_number)
        if not self.context:
            raise OSError("this PC's graphics driver gave no OpenGL context")
        self.renderer = gl.glGetString(GL_RENDERER).decode(errors="replace")
        self.gl_version = gl.glGetString(GL_VERSION).decode(errors="replace")
        self.vsync = self._set_vsync(vsync)
        if samples and self.samples:
            gl.glEnable(0x809D)  # GL_MULTISAMPLE
        if fullscreen:
            self.toggle_fullscreen()

    @staticmethod
    def _make_context(hdc, format_number):
        wanted = _basic_format()
        if format_number:
            gdi32.DescribePixelFormat(hdc, format_number, ctypes.sizeof(_PixelFormat), ctypes.byref(wanted))
        else:
            format_number = gdi32.ChoosePixelFormat(hdc, ctypes.byref(wanted))
        if not format_number or not gdi32.SetPixelFormat(hdc, format_number, ctypes.byref(wanted)):
            return None
        context = gl.wglCreateContext(hdc)
        if context:
            gl.wglMakeCurrent(hdc, context)
        return context

    def _find_smooth_format(self, samples):
        """The driver's list of smoothed formats can only be read from inside a throwaway window. 0 if there are none."""
        hwnd = user32.CreateWindowExW(0, _CLASS_NAME, "probe", WS_OVERLAPPEDWINDOW, 0, 0, 16, 16, None, None, self.instance, None)
        hdc = user32.GetDC(hwnd)
        found = 0
        context = self._make_context(hdc, 0)
        if context:
            address = gl.wglGetProcAddress(b"wglChoosePixelFormatARB")
            if address:
                choose = _CHOOSE_FORMAT(address)
                wanted = [WGL_DRAW_TO_WINDOW, 1, WGL_SUPPORT_OPENGL, 1, WGL_DOUBLE_BUFFER, 1, WGL_PIXEL_TYPE, WGL_TYPE_RGBA,
                          WGL_COLOR_BITS, 24, WGL_DEPTH_BITS, 24, WGL_SAMPLE_BUFFERS, 1, WGL_SAMPLES, samples, 0]
                values = (ctypes.c_int * len(wanted))(*wanted)
                number, count = ctypes.c_int(0), wintypes.UINT(0)
                if choose(hdc, values, None, 1, ctypes.byref(number), ctypes.byref(count)) and count.value:
                    found = number.value
                    self.samples = samples
            gl.wglMakeCurrent(None, None)
            gl.wglDeleteContext(context)
        user32.ReleaseDC(hwnd, hdc)
        user32.DestroyWindow(hwnd)
        self.open = True  # the throwaway window's closing message must not end this one
        return found

    @staticmethod
    def _set_vsync(on):
        address = gl.wglGetProcAddress(b"wglSwapIntervalEXT")
        if not address:
            return False
        _SWAP_INTERVAL(address)(1 if on else 0)
        return on

    def _on_message(self, hwnd, message, wparam, lparam):
        if message in (WM_CLOSE, WM_DESTROY):
            self.open = False
            return 0
        if message == WM_KEYDOWN:
            if wparam == VK_F11:
                self.toggle_fullscreen()
            elif wparam == VK_ESCAPE and self.is_fullscreen:
                self.toggle_fullscreen()
            elif wparam in VK_NAMES:
                self.keys.add(VK_NAMES[wparam])
            return 0
        if message == WM_KEYUP:
            self.keys.discard(VK_NAMES.get(wparam))
            return 0
        if message == WM_LBUTTONDBLCLK:
            self.toggle_fullscreen()
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def toggle_fullscreen(self):
        if self.is_fullscreen:
            style, rect = self._saved
            user32.SetWindowLongPtrW(self.hwnd, GWL_STYLE, style)
            user32.SetWindowPos(self.hwnd, None, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top,
                                SWP_FRAMECHANGED | SWP_NOZORDER)
        else:
            rect = wintypes.RECT()
            user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
            self._saved = (user32.GetWindowLongPtrW(self.hwnd, GWL_STYLE), rect)
            info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
            user32.GetMonitorInfoW(user32.MonitorFromWindow(self.hwnd, MONITOR_DEFAULTTONEAREST), ctypes.byref(info))
            screen = info.rcMonitor
            user32.SetWindowLongPtrW(self.hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE | WS_CLIPCHILDREN | WS_CLIPSIBLINGS)
            user32.SetWindowPos(self.hwnd, None, screen.left, screen.top, screen.right - screen.left, screen.bottom - screen.top,
                                SWP_FRAMECHANGED | SWP_NOZORDER)
        self.is_fullscreen = not self.is_fullscreen

    def poll(self):
        """Handles waiting window messages. False once the user has closed the window."""
        message = wintypes.MSG()
        while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        return self.open

    def size(self):
        rect = wintypes.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rect))
        return rect.right - rect.left, rect.bottom - rect.top

    def set_title(self, text):
        user32.SetWindowTextW(self.hwnd, text)

    def present(self):
        gdi32.SwapBuffers(self.hdc)

    def close(self):
        gl.wglMakeCurrent(None, None)
        gl.wglDeleteContext(self.context)
        user32.ReleaseDC(self.hwnd, self.hdc)
        user32.DestroyWindow(self.hwnd)
        self.poll()
        user32.UnregisterClassW(_CLASS_NAME, self.instance)
        self.open = False
