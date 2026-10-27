"""README generator: every Meta tooling site is found in the code, and the generated blocks render."""

from __future__ import annotations

import pytest

from tools import readme


def test_every_meta_site_is_found() -> None:
    table = readme.meta_table()
    assert table.count("\n") == len(readme.USES) + 1
    for u in readme.USES:
        assert f"**{u.model}**" in table
        assert "|" not in u.role  # a pipe would split the markdown row


def test_evidence_block_names_its_sources() -> None:
    block = readme.evidence()
    assert block.startswith("| Check | Result | Source |")
    assert "Real repairs logged" in block


def test_render_only_touches_marked_blocks() -> None:
    text = "intro\n" + "".join(f"<!-- BEGIN:{n} -->\nold\n<!-- END:{n} -->\nkeep {n}\n" for n in readme.BLOCKS)
    out = readme.render(text)
    assert out.startswith("intro\n")
    assert all(f"keep {n}\n" in out for n in readme.BLOCKS)
    assert "old" not in out


def test_render_requires_every_block() -> None:
    with pytest.raises(LookupError):
        readme.render("no blocks here")
