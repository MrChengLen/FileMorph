# SPDX-License-Identifier: AGPL-3.0-or-later
"""The file response for a result built in a request's temp dir."""

from __future__ import annotations

import os
import shutil
from typing import Any

import anyio
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send


class TempDirFileResponse(FileResponse):
    """Send ``path``, then remove ``tmp_dir`` — the request's temp dir that
    holds the result and the upload — however the response ends.

    A ``background`` task runs only after a complete send: a send that fails
    (a server reporting the client gone) or is cancelled (a middleware or a
    shutdown stopping the response) would leave both on disk until the sweep.
    The removal sits in a ``finally`` instead, shielded so that a cancelled
    response still finishes it.
    """

    def __init__(
        self, path: str | os.PathLike[str], *, tmp_dir: str | os.PathLike[str], **kwargs: Any
    ) -> None:
        super().__init__(path, **kwargs)
        self.tmp_dir = tmp_dir

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(shutil.rmtree, self.tmp_dir, ignore_errors=True)
