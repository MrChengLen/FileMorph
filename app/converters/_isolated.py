# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run a conversion step in a child process with memory, time and file size limits.

``run_isolated`` starts

``python -m app.converters._isolated <step> <memory-bytes> <seconds> <file-bytes> <json-kwargs>``

with a time limit and stops it when it runs over. On Linux the child also caps
its address space, its CPU time and the size of each file it writes, gains no
privileges through setuid programs, ends when the process that started it ends
and, without root privileges, starts no processes or threads of its own
(``limit_resources``). It prints one JSON line on stdout, the step's result or
the error it raised, and the parent raises that error again. A child that runs
out of memory or time, or writes a file past its limit, becomes a
``TooComplexError`` with the caller's message. Its temporary files go to the
request's own temp folder, so they are cleaned up with it.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

# The environment variable in which spawn tells the child its parent's PID,
# the same one run_ffmpeg sets for _limited_exec.py.
from app.converters._limited_exec import PARENT_PID_ENV as _PARENT_PID_ENV
from app.converters.base import (
    EncryptedPdfError,
    InvalidInputError,
    OutputTooLargeError,
    UnsupportedPdfEncryptionError,
)

logger = logging.getLogger(__name__)

_APP_ROOT = Path(__file__).resolve().parents[2]  # the directory holding the ``app`` package
_GIB = 1024 * 1024 * 1024

# What a child may run: step → (module, function, memory limit, time limit in
# s, size limit of each file it writes). 90 s stays under the 100 s a CDN in
# front of the app may wait for an answer, so the caller gets the 400 that
# names the next step, not a gateway timeout.
_STEPS: dict[str, tuple[str, str, int, float, int]] = {
    # 2 GiB per file: CSV → XLSX writes its sheet as XML before zipping it,
    # and sheets of close to 1 GiB finish within the 90 s. The other
    # conversions stop at the output cap (at most 500 MB, app/core/quotas.py).
    "convert": ("app.converters._isolated", "_convert", _GIB, 90, 2 * _GIB),
    # 3 GiB: at its decode limit (500 megapixels) compress_pdf_to_target holds
    # about 2.2 GB, the decoded images and the document. 1 GiB per file: it
    # writes only the output, at most about the size of the upload.
    "pdf-compress": ("app.compressors.pdf", "compress_pdf_to_target", 3 * _GIB, 90, _GIB),
    # pypdf reads both PDFs, clones one and merges the other in: seconds for
    # a real document; the limits bound any other.
    # 30 s: a Word file's LibreOffice run (up to 60 s) comes first, and both
    # together stay under the 100 s. 1 GiB per file: it writes only the
    # result, about both uploads together.
    "pdf-insert": ("app.converters.pdf_insert", "insert_pages", _GIB, 30, _GIB),
}


class TooComplexError(InvalidInputError):
    """The child ran out of memory or time, or wrote a file past its limit;
    the message is the caller's ``too_large``. ``/pdf/compress`` answers it
    with ``pdf_too_complex``, ``/convert`` like any other
    ``InvalidInputError``."""


def limit_resources(memory_bytes: int, cpu_seconds: int, file_bytes: int) -> None:
    """Cap this process's address space, CPU time and the size of each file
    it writes and turn off its core dump and, without root privileges, its
    starting of processes and threads (Linux), as hard limits it can't raise
    again; keep it from gaining privileges through setuid programs; end it
    when its parent ends; and make it the first process the kernel stops when
    the host runs short of memory. A write past the file size limit ends the
    process, as running out of CPU time does."""
    if sys.platform != "linux":
        return
    import resource
    import signal

    limits = (
        (resource.RLIMIT_AS, memory_bytes),
        (resource.RLIMIT_CPU, cpu_seconds),
        (resource.RLIMIT_FSIZE, file_bytes),
        (resource.RLIMIT_CORE, 0),  # a dump would copy the file's data to disk
        # No fork, no thread: the steps need neither, and nothing the child
        # starts can outlive it. The kernel counts every process of the user
        # against this limit, so only 0 means the same on every host; root
        # and holders of CAP_SYS_RESOURCE or CAP_SYS_ADMIN are exempt.
        (resource.RLIMIT_NPROC, 0),
    )
    for limit, value in limits:
        hard = resource.getrlimit(limit)[1]
        cap = value if hard == resource.RLIM_INFINITY else min(hard, value)
        # Soft and hard limit alike: a process can raise its soft limit up to
        # the hard one, and the hard one only with privileges.
        resource.setrlimit(limit, (cap, cap))
    # Python ignores SIGXFSZ, which turns a write past RLIMIT_FSIZE into an
    # error, and not always an OSError (openpyxl writes through lxml, which
    # raises its own). With the default action the signal ends the process.
    signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
    try:
        Path("/proc/self/oom_score_adj").write_text("1000", encoding="utf-8")
    except OSError:
        pass
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)

    def prctl(option: int, value: int) -> None:
        # A setting the kernel refuses ends the child, rather than letting it
        # go on without the setting.
        if libc.prctl(option, value, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), f"prctl {option} failed")

    # A setuid or setgid program it runs gets no privileges from that, so
    # the hard limits stay out of reach too. Like them, this can't be undone.
    prctl(38, 1)  # PR_SET_NO_NEW_PRIVS
    # End with the parent, whether the child computes or waits. The signal
    # comes when the parent's thread that started the child ends; spawn waits
    # for the child in that thread. If the parent ended before this line, the
    # child has another one now.
    prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
    parent = os.environ.get(_PARENT_PID_ENV)
    if parent is not None and parent != str(os.getppid()):
        os._exit(1)
    # No core dump either where the kernel hands dumps to a program, which
    # ignores RLIMIT_CORE. Last: afterwards /proc/self belongs to root.
    prctl(4, 0)  # PR_SET_DUMPABLE


def spawn(args: list[str], *, timeout: float, tmp_dir: Path) -> subprocess.CompletedProcess:
    """Run ``python -m <args>`` from the app root, without app secrets in its
    environment and with its temporary files in ``tmp_dir``. Past ``timeout``
    the child is stopped and ``subprocess.TimeoutExpired`` raised."""
    from app.converters.document import _is_secret_env_name

    env = {k: v for k, v in os.environ.items() if not _is_secret_env_name(k)}
    env.update(TMPDIR=str(tmp_dir), TEMP=str(tmp_dir), TMP=str(tmp_dir))
    # glibc gives threads their own heap arenas, which under an address-space
    # cap can use it up before the work does.
    env["MALLOC_ARENA_MAX"] = "2"
    # The child can't start threads (limit_resources; root aside): tell
    # OpenBLAS, which openpyxl loads with numpy where numpy is installed, to
    # start no pool of them as it loads.
    env["OPENBLAS_NUM_THREADS"] = "1"
    env[_PARENT_PID_ENV] = str(os.getpid())  # the process the child ends with
    return subprocess.run(  # noqa: S603 — fixed module, our own arguments, no shell
        [sys.executable, "-m", *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        # The child's diagnostic output is discarded; it reports on stdout.
        stderr=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        cwd=_APP_ROOT,
        env=env,
    )


def run_isolated(step: str, *, too_large: str, tmp_dir: Path, **kwargs):
    """Run ``step`` with ``kwargs`` in a child process and return its result.

    The child's ``OutputTooLargeError``, ``EncryptedPdfError`` (and its
    subclass) and ``InvalidInputError`` are raised here again;
    ``TooComplexError(too_large)`` when it runs out of memory or time or
    writes a file past its limit, and a ``RuntimeError`` naming the exception
    class for anything else.
    """
    _, _, memory, seconds, file_bytes = _STEPS[step]
    limits = [str(memory), str(seconds), str(file_bytes)]
    args = [__name__, step, *limits, json.dumps(kwargs, default=str)]
    try:
        result = spawn(args, timeout=seconds, tmp_dir=tmp_dir)
    except subprocess.TimeoutExpired:
        logger.info("isolated %s: stopped after %s s", step, seconds)
        raise TooComplexError(too_large) from None
    try:
        outcome = json.loads((result.stdout.strip().splitlines() or ["{}"])[-1])
    except ValueError:
        outcome = {}
    if not isinstance(outcome, dict):
        outcome = {}
    if "result" in outcome:
        return outcome["result"]
    error = outcome.get("error")
    if error == "output_too_large":
        raise OutputTooLargeError
    if error == "unsupported_encryption":
        raise UnsupportedPdfEncryptionError()
    if error == "encrypted":
        raise EncryptedPdfError()
    if error == "invalid":
        raise InvalidInputError(str(outcome.get("message", "")))
    # Out of memory, or stopped by a limit (a signal: negative status): CPU
    # time, file size, or the kernel's OOM killer.
    if error == "out_of_memory" or result.returncode < 0:
        logger.info(
            "isolated %s: out of memory, CPU time or file size (status %s)",
            step,
            result.returncode,
        )
        raise TooComplexError(too_large)
    # A logged error shows its type and traceback, not its text: name the
    # child's error type here, and nothing that isn't a name.
    error_type = outcome.get("type")
    error_type = error_type if isinstance(error_type, str) and error_type.isidentifier() else "-"
    logger.warning("isolated %s failed (status %s): %s", step, result.returncode, error_type)
    raise RuntimeError(f"isolated {step} failed (status {result.returncode}): {error_type}")


def _convert(converter: str, input_path: Path, output_path: Path, **kwargs) -> None:
    """Run an ``isolated`` converter, named ``module:Class``, in this process."""
    module, _, name = converter.partition(":")
    cls = getattr(importlib.import_module(module), name)
    if not getattr(cls, "isolated", False):
        raise ValueError(f"{converter} doesn't run isolated")
    cls().convert(input_path, output_path, **kwargs)


def _main(argv: list[str]) -> dict:
    """The child's side: run the step and report its result or error."""
    step, memory, seconds, file_bytes, raw = argv
    module, function, *_ = _STEPS[step]
    limit_resources(int(memory), int(float(seconds)) + 5, int(file_bytes))
    from app.core.image_hardening import apply_hardening

    apply_hardening()  # the server applies it at startup; a child starts afresh
    kwargs = {k: Path(v) if k.endswith("_path") else v for k, v in json.loads(raw).items()}
    try:
        return {"result": getattr(importlib.import_module(module), function)(**kwargs)}
    except OutputTooLargeError:
        return {"error": "output_too_large"}
    except UnsupportedPdfEncryptionError:
        return {"error": "unsupported_encryption"}
    except EncryptedPdfError:
        return {"error": "encrypted"}
    except InvalidInputError as exc:  # its message is written for the user
        return {"error": "invalid", "message": str(exc)}
    except MemoryError:
        return {"error": "out_of_memory"}
    except Exception as exc:  # the parent logs the class only: messages can quote the file
        return {"error": "failed", "type": type(exc).__name__}


if __name__ == "__main__":
    import warnings

    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")  # apply_hardening's error filter still goes first
    print(json.dumps(_main(sys.argv[1:])))
