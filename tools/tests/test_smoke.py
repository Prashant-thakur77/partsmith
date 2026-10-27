from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from services.agent import providers
from services.agent.providers import clients
from tools import smoke

KEYS = (
    "PROVIDER_MODE", "MODEL_API_KEY", "BASETEN_API_KEY", "FIREWORKS_API_KEY", "TOGETHER_API_KEY", "GLIMMER_BASE_URL",
    "GLIMMER_API_KEY", "SAM3_OPEN_URL", "SAM3_OPEN_API_KEY", "SPARK_OPEN_MODEL", "OPEN_WEIGHTS_ONLY",
)  # fmt: skip


@pytest.fixture(autouse=True)
def zero_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PARTSMITH_ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.setenv("PARTSMITH_HOME", str(tmp_path / "home"))
    providers.reset_state()

    def no_network(*a: Any) -> Any:
        raise AssertionError("smoke test must not build a real client")

    clients.set_client_factory(no_network)
    yield
    providers.reset_state()


def test_zero_keys_all_warnings_exit_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert smoke.main([]) == 0
    out = capsys.readouterr().out
    rows = [line for line in out.splitlines() if line[:1] in ("✅", "❌", "⚠")]
    assert len(rows) == len(smoke.checks()) and all(line.startswith("⚠️") for line in rows)
    for env in ("MODEL_API_KEY", "BASETEN_API_KEY", "GLIMMER_BASE_URL", "SAM3_OPEN_URL", "FIREWORKS_API_KEY"):
        assert env in out
    assert "Stage routing (overall mode: mock)" in out
    assert "0 live ✅ · 12 missing ⚠️ (mock) · 0 failed ❌" in out


class _Err(Exception):
    status_code = 401


def test_live_success_and_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-secret-1")

    class Responses:
        def create(self, **kw: Any) -> Any:
            if kw["model"] == "muse-wonder-1.0":
                raise _Err("denied for k-meta-secret-1")
            if kw["model"] == "muse-spark-1.3":
                return [
                    {
                        "type": "response.output_text.delta",
                        "item_id": "a",
                        "output_index": 0,
                        "content_index": 0,
                        "delta": "OK",
                    },
                    {"type": "response.completed", "response": {"usage": {"input_tokens": 9, "output_tokens": 1}}},
                ]
            raise _Err("not in this test")

    class Client:
        responses = Responses()

    clients.set_client_factory(lambda *a: Client())
    results = {r.name: r for r in smoke.run_checks(smoke.checks()[:2])}
    assert results["Meta · muse-spark-1.3"].status == "ok"
    assert "'OK'" in results["Meta · muse-spark-1.3"].detail and "9+1 tok" in results["Meta · muse-spark-1.3"].detail
    wonder = results["Meta · muse-wonder-1.0"]
    assert wonder.status == "fail" and "HTTP 401" in wonder.detail and "secret" not in wonder.detail


def test_exit_code_one_on_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-secret-1")
    clients.set_client_factory(lambda *a: (_ for _ in ()).throw(_Err("nope")))
    assert smoke.main(["--no-status"]) == 1
    out = capsys.readouterr().out
    assert "❌ Meta · muse-spark-1.3" in out and "Stage routing" not in out
