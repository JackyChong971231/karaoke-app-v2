"""Everything this process starts ends with it.

On Windows, the process joins a job object that Windows kills when its last handle closes. Only this process
holds the handle, so when the app ends for any reason (its terminal window closed, Ctrl+C, a crash), Windows
ends every process the app started after joining: the TV and control page Edge windows, and any song
preparation still running. Children join the job automatically, so there is no window in which a fast-spawning
child escapes. Elsewhere this does nothing.
"""

from __future__ import annotations

import sys

_job: int | None = None
"""The job handle. Kept open, never closed: closing it is what ends the children, so it lives as long as we do."""


def tie_children_to_this_process() -> bool:
    """Idempotent. Returns whether the tie is in place."""
    global _job
    if _job is not None:
        return True
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes",
                                                    "OtherBytes")]

    class _Extended(ctypes.Structure):
        _fields_ = [("Basic", _Basic), ("Io", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kill_on_job_close = 0x2000
    extended_limit_information = 9
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    job = k32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = _Extended()
    info.Basic.LimitFlags = kill_on_job_close
    if not k32.SetInformationJobObject(job, extended_limit_information, ctypes.byref(info), ctypes.sizeof(info)):
        k32.CloseHandle(job)
        return False
    # Fails only on Windows 7 when already inside another job (nested jobs came in Windows 8).
    if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
        k32.CloseHandle(job)
        return False
    _job = int(job)
    return True
