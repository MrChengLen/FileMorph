# SPDX-License-Identifier: AGPL-3.0-or-later
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
