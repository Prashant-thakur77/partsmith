"""`make deploy-check` as a unit test: the deploy files under infra/deploy stay consistent with the code."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[3]


def _check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deploy_check", REPO / "infra" / "deploy" / "check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_deploy_files_pass_the_static_checks() -> None:
    rows = _check().run_checks(REPO)
    assert len(rows) >= 20
    assert [r for r in rows if r[1] is not None] == []


def test_dockerignore_rules_and_copy_parsing() -> None:
    c = _check()
    pats = ["*", "!services/", "!data/replays/", "**/tests/", "**/.env"]
    assert c.in_context("services/api/main.py", pats)
    assert c.in_context("data/replays/j_1/run.jsonl", pats)
    assert not c.in_context("services/api/tests/test_api.py", pats)
    assert not c.in_context(".env", pats) and not c.in_context("var/partsmith.db", pats)
    assert not c.in_context("data/real/x/top.jpg", pats)
    text = "FROM x AS deps\nCOPY --from=uv /uv /bin/uv\nCOPY a.toml \\\n  b.lock ./\nCOPY --chmod=755 e.sh /bin/e\n"
    assert c.dockerfile_copies(text) == ["a.toml", "b.lock", "e.sh"]
    assert c.dockerfile_env("ENV A=1 \\\n    PROVIDER_MODE=replay\n") == {"A": "1", "PROVIDER_MODE": "replay"}


def test_env_template_parser(tmp_path: Path) -> None:
    f = tmp_path / "x.env"
    f.write_text("# comment\nA=1\n\nB=\nC = two words\n")
    assert _check().parse_env(f) == {"A": "1", "B": "", "C": "two words"}
