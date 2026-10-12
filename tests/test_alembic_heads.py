# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Alembic history stays one straight line that Postgres can record.

``entrypoint.sh`` runs ``alembic upgrade head`` on every start of a Cloud
Edition container; if that fails, the container never starts.

- With two heads (two migrations naming the same ``down_revision``) the
  command refuses to run. This happens when two pull requests each add a
  migration on top of the same head: each is fine on its own, and both
  merge. The migration that merges second must point its
  ``down_revision`` at the first.
- ``alembic_version.version_num`` is ``VARCHAR(32)``. Postgres rejects a
  longer revision id when Alembic records it, and the whole run rolls
  back; SQLite does not enforce the length. This check needs no database.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_ROOT = Path(__file__).resolve().parent.parent


def _scripts() -> ScriptDirectory:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_alembic_history_has_a_single_head():
    heads = _scripts().get_heads()
    assert len(heads) == 1, (
        f"Alembic has {len(heads)} heads {sorted(heads)}: point the newer "
        "migration's down_revision at the other one"
    )


def test_revision_ids_fit_alembic_version_column():
    too_long = [s.revision for s in _scripts().walk_revisions() if len(s.revision) > 32]
    assert not too_long, f"revision ids longer than 32 characters: {too_long}"
