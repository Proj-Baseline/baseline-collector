"""Foreground window identity, via Win32 through ctypes. Zero dependencies.

Returns the active process's executable name and window title. The engine
only ever uses the process name (see engine/categorize.py); the title is
captured because AGENTS.md §5 and the landing page's capture list both say
it is, and it is there for future per-project attribution.

Titles are the single most sensitive thing the collector records — a browser
title carries the page you are reading, an editor title carries the file you
are writing. They never leave the machine, but if a user is uncomfortable
capturing them at all, `--no-titles` drops them at the source and costs
nothing that exists today.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_MAX_TITLE = 512
_MAX_PATH_LONG = 32768  # long paths; QueryFullProcessImageNameW writes into this


@dataclass(frozen=True)
class ActiveWindow:
    process: str | None
    title: str | None


try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # Explicit signatures. Without argtypes/restype, ctypes assumes C int for
    # handles, which silently truncates 64-bit HWNDs and HANDLEs.
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    _WIN32 = True
except (OSError, AttributeError):  # pragma: no cover - non-Windows
    _WIN32 = False


def available() -> bool:
    return _WIN32


def _process_name(pid: int) -> str | None:
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Elevated or protected processes refuse to open. That is normal, not
        # an error: the span still counts as active time, it just has no
        # attributable app. engine/ maps a None process to DEFAULT_CATEGORY.
        return None
    try:
        size = wintypes.DWORD(_MAX_PATH_LONG)
        buf = ctypes.create_unicode_buffer(_MAX_PATH_LONG)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        # Basename only. The full path can expose usernames and directory
        # layout, and nothing downstream uses more than the executable name.
        return buf.value.rsplit("\\", 1)[-1] or None
    finally:
        _kernel32.CloseHandle(handle)


def active_window(capture_title: bool = True) -> ActiveWindow:
    """Current foreground window. Never raises — a failed probe returns
    (None, None), which the caller treats as 'unknown app', because a
    transient Win32 failure must not take down a long-running collector."""
    if not _WIN32:
        return ActiveWindow(None, None)
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            # No foreground window: lock screen, alt-tab overlay, or a moment
            # between two windows taking focus.
            return ActiveWindow(None, None)

        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = _process_name(pid.value) if pid.value else None

        title = None
        if capture_title:
            buf = ctypes.create_unicode_buffer(_MAX_TITLE)
            if _user32.GetWindowTextW(hwnd, buf, _MAX_TITLE) > 0:
                title = buf.value or None

        return ActiveWindow(process, title)
    except Exception:
        return ActiveWindow(None, None)
