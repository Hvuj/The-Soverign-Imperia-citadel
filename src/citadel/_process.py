"""Portable process-liveness checks that never signal the target process."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path


def pid_is_alive(pid: int) -> bool:
    """Return whether *pid* is running without changing process state.

    ``os.kill(pid, 0)`` is the conventional POSIX probe, but it is unsafe on
    Windows: signal value ``0`` is ``CTRL_C_EVENT`` there.  Sending it to one
    of Citadel's console process groups can interrupt the foreground
    ``citadel up`` process.  Query the process handle on Windows instead.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_pid_is_alive(pid: int) -> bool:
    """Query a Windows process handle without delivering a console event."""
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        # Access denied still proves that the PID exists; other failures (most
        # commonly ERROR_INVALID_PARAMETER for a stale PID) mean it does not.
        return ctypes.get_last_error() == error_access_denied
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def process_command_line(pid: int) -> str | None:
    """Return *pid*'s command line when it can be inspected safely."""
    if pid <= 0:
        return None
    if sys.platform == "win32":
        return _windows_process_command_line(pid)
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace")
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            timeout=2,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def iter_process_command_lines() -> Iterator[tuple[int, str]]:
    """Yield inspectable ``(pid, command_line)`` pairs."""
    if sys.platform == "win32":
        for pid in _windows_process_ids():
            command_line = _windows_process_command_line(pid)
            if command_line:
                yield pid, command_line
        return

    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,args="],
            capture_output=True,
            timeout=5,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    for line in result.stdout.splitlines():
        try:
            pid_text, command_line = line.strip().split(maxsplit=1)
            yield int(pid_text), command_line
        except ValueError:
            continue


def _windows_process_command_line(pid: int) -> str | None:
    """Read a Windows process command line without signaling the process."""
    import ctypes
    from ctypes import wintypes

    class _UnicodeString(ctypes.Structure):
        _fields_ = (
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", ctypes.c_void_p),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    ntdll.NtQueryInformationProcess.argtypes = (
        wintypes.HANDLE,
        wintypes.ULONG,
        wintypes.LPVOID,
        wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    )
    ntdll.NtQueryInformationProcess.restype = wintypes.LONG

    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        size = wintypes.ULONG()
        ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(size))
        if not size.value:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        status = ntdll.NtQueryInformationProcess(handle, 60, buffer, size.value, ctypes.byref(size))
        if status != 0:
            return None
        value = _UnicodeString.from_buffer(buffer)
        if not value.Buffer or not value.Length:
            return ""
        return ctypes.wstring_at(value.Buffer, value.Length // ctypes.sizeof(ctypes.c_wchar))
    finally:
        kernel32.CloseHandle(handle)


def _windows_process_ids() -> list[int]:
    """Enumerate Windows process IDs through the native PSAPI."""
    import ctypes
    from ctypes import wintypes

    psapi = ctypes.WinDLL("psapi")
    psapi.EnumProcesses.argtypes = (
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    psapi.EnumProcesses.restype = wintypes.BOOL

    capacity = 1024
    while capacity <= 65536:
        values = (wintypes.DWORD * capacity)()
        needed = wintypes.DWORD()
        if not psapi.EnumProcesses(values, ctypes.sizeof(values), ctypes.byref(needed)):
            return []
        count = needed.value // ctypes.sizeof(wintypes.DWORD)
        if count < capacity:
            return [int(values[index]) for index in range(count) if values[index]]
        capacity *= 2
    return []
