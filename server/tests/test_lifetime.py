"""The app's children end when the app ends, however it ends."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

_PARENT = """
import subprocess, sys, time
from karaoke.shell.lifetime import tie_children_to_this_process
assert tie_children_to_this_process()
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(child.pid, flush=True)
time.sleep(120)
"""


def _alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


@pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows only")
def test_children_end_when_the_app_is_killed() -> None:
    parent = subprocess.Popen([sys.executable, "-c", _PARENT], stdout=subprocess.PIPE, text=True)
    assert parent.stdout is not None
    child = int(parent.stdout.readline())
    assert _alive(child)
    parent.kill()  # TerminateProcess: no clean-up code runs, as when the terminal window is closed
    parent.wait()
    deadline = time.monotonic() + 5
    while _alive(child) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _alive(child), "the child outlived the app"
