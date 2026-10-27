# SPDX-License-Identifier: AGPL-3.0-or-later
"""Start a program with memory, CPU time and file size limits (Linux).

``python -I -S _limited_exec.py <memory-bytes> <cpu-seconds> <file-bytes> <program> [<arg> ...]``

caps its own address space, CPU time and the size of each file it writes, as
hard limits it can't raise again, turns off its core dump, keeps itself from
gaining privileges through setuid programs, ends when the process that started
it ends and makes itself the first process the kernel stops when the host runs
short of memory. Then it replaces itself with ``program`` (``os.execv``),
which keeps all of that. ``run_ffmpeg`` in ``app/converters/_ffmpeg.py``
starts ffmpeg this way.

Unlike the Python children (``limit_resources`` in ``_isolated.py``), the
program may start threads: ffmpeg decodes and encodes with several. Only the
standard library is imported, so the program starts without the app being
loaded first.
"""

from __future__ import annotations

import os
import signal
import sys

# The environment variable in which the parent names its PID.
PARENT_PID_ENV = "FILEMORPH_PARENT_PID"


def limit(memory_bytes: int, cpu_seconds: int, file_bytes: int) -> None:
    """Apply the limits above to this process; the program it executes next
    keeps them."""
    import ctypes
    import resource

    for rlimit, value in (
        (resource.RLIMIT_AS, memory_bytes),
        (resource.RLIMIT_CPU, cpu_seconds),
        (resource.RLIMIT_FSIZE, file_bytes),
        # A dump would copy the file's data to disk. Unlike limit_resources,
        # no PR_SET_DUMPABLE: execve resets it, so this limit is what carries.
        (resource.RLIMIT_CORE, 0),
    ):
        hard = resource.getrlimit(rlimit)[1]
        cap = value if hard == resource.RLIM_INFINITY else min(hard, value)
        # Soft and hard limit alike: raising the hard one takes privileges.
        resource.setrlimit(rlimit, (cap, cap))
    try:
        with open("/proc/self/oom_score_adj", "w", encoding="utf-8") as f:
            f.write("1000")
    except OSError:
        pass
    libc = ctypes.CDLL(None, use_errno=True)
    # PR_SET_NO_NEW_PRIVS, then PR_SET_PDEATHSIG. A setting the kernel refuses
    # ends this process rather than letting the program run without it.
    for option, value in ((38, 1), (1, signal.SIGKILL)):
        if libc.prctl(option, value, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), f"prctl {option} failed")
    # The signal comes when the parent's thread that started this process
    # ends; run_ffmpeg waits for it in that thread. If the parent ended before
    # the prctl above, this process has another one now.
    parent = os.environ.get(PARENT_PID_ENV)
    if parent is not None and parent != str(os.getppid()):
        os._exit(1)
    # Python ignores SIGPIPE and SIGXFSZ, and a signal ignored here stays
    # ignored in the program. With the default action, a write past the file
    # size limit ends the program.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    signal.signal(signal.SIGXFSZ, signal.SIG_DFL)


if __name__ == "__main__":
    memory, cpu, file_bytes, program, *args = sys.argv[1:]
    limit(int(memory), int(cpu), int(file_bytes))
    os.execv(program, [program, *args])
