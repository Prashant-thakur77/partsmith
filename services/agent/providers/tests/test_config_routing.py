from __future__ import annotations

import logging
from pathlib import Path

import pytest

from services.agent import providers
from services.agent.providers import config, routing

STATUS_KEYS = {"stage", "role", "provider", "model", "mode", "key_env", "key_present", "open_weights", "where", "note"}


def test_parse_dotenv_handles_quotes_comments_and_export() -> None:
    text = """
# comment
export A=1
B = "two words"
C='single # not a comment'
D=value # trailing comment
E=
bad line
9X=nope
"""
    assert config.parse_dotenv(text) == {
        "A": "1",
        "B": "two words",
        "C": "single # not a comment",
        "D": "value",
        "E": "",
    }


def test_env_prefers_process_env_and_treats_empty_as_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MODEL_API_KEY=from-file\nBASETEN_API_KEY=\n")
    monkeypatch.setenv("PARTSMITH_ENV_FILE", str(env_file))
    assert config.env("MODEL_API_KEY") == "from-file"
    assert config.env("BASETEN_API_KEY") is None
    monkeypatch.setenv("MODEL_API_KEY", "from-env")
    assert config.env("MODEL_API_KEY") == "from-env"
    monkeypatch.setenv("MODEL_API_KEY", "")
    assert config.env("MODEL_API_KEY") == "from-file"


def test_redact_removes_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "sk-very-secret-123")
    msg = config.redact("failed with sk-very-secret-123 and Authorization: Bearer abc.def and LLM_12345678_secretpart")
    assert "sk-very-secret" not in msg and "abc.def" not in msg and "secretpart" not in msg


def test_zero_keys_every_stage_is_mock_and_status_matches_api_shape(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="partsmith.providers"):
        rows = providers.status()
        providers.status()  # warnings are logged once per stage, not per call
    assert [r["stage"] for r in rows] == list(routing.STAGES)
    assert all(set(r) == STATUS_KEYS for r in rows)
    assert all(r["mode"] == "mock" for r in rows)
    build = next(r for r in rows if r["stage"] == "build")
    assert build["provider"] == "baseten"
    assert build["role"] == "Builder"
    assert build["model"] == "meta-models/muse-spark-open"
    assert build["key_env"] == "BASETEN_API_KEY"
    assert build["key_present"] is False
    assert build["open_weights"] is True
    assert build["where"] == "Baseten"
    assert "BASETEN_API_KEY" in build["note"] and "deterministic mock" in build["note"]
    judge = next(r for r in rows if r["stage"] == "judge")
    assert judge["key_env"] == "GLIMMER_BASE_URL" and judge["provider"] == "modal_glimmer"
    warned = [r.message for r in caplog.records if "build" in r.message]
    assert len(warned) == 1
    assert providers.overall_mode() == "mock"
    assert any(w.startswith("understand:") for w in providers.warnings())


def test_meta_key_only_routes_builder_to_spark_13_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    rows = {r["stage"]: r for r in providers.status()}
    assert rows["understand"]["mode"] == "live" and rows["understand"]["model"] == "muse-spark-1.3"
    assert rows["build"]["mode"] == "live" and rows["build"]["provider"] == "meta"
    assert "BASETEN_API_KEY missing" in rows["build"]["note"]
    assert rows["judge"]["mode"] == "live" and rows["judge"]["model"] == "muse-spark-1.3"  # no Glimmer deployed
    assert rows["steer_plan"]["model"] == "muse-wonder-1.0"
    assert providers.overall_mode() == "mixed"


def test_provider_mode_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    monkeypatch.setenv("PROVIDER_MODE", "mock")
    assert providers.stage_mode("understand") == "mock"
    monkeypatch.setenv("PROVIDER_MODE", "replay")
    assert providers.overall_mode() == "replay"
    monkeypatch.setenv("PROVIDER_MODE", "bogus")
    assert providers.stage_mode("understand") == "live"


def test_open_weights_only_routes_to_open_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_WEIGHTS_ONLY", "1")
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    monkeypatch.setenv("BASETEN_API_KEY", "k-baseten-000")
    monkeypatch.setenv("GLIMMER_BASE_URL", "https://example--glimmer.modal.run")
    monkeypatch.setenv("SAM3_OPEN_URL", "https://example--sam3.modal.run")
    rows = {r["stage"]: r for r in providers.status()}
    assert rows["understand"]["provider"] == "modal_glimmer" and rows["understand"]["mode"] == "live"
    assert rows["voice_map"]["provider"] == "baseten"
    assert rows["steer_plan"]["provider"] == "baseten"
    assert rows["segment"]["provider"] == "modal_sam3" and rows["segment"]["open_weights"] is True
    assert rows["image"]["mode"] == "mock" and "no open-weight" in rows["image"]["note"]
    assert rows["transcribe"]["mode"] == "mock"
    assert all(r["open_weights"] for r in rows.values())


def test_product_judge_falls_back_to_spark_13(monkeypatch: pytest.MonkeyPatch) -> None:
    """Product path: Glimmer first, Spark 1.3 on the Meta API when Glimmer is not deployed. Open weights: Glimmer only."""
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    res = routing.resolve("judge")
    assert res.mode == "live" and [r.model for r in res.routes] == ["muse-spark-1.3"]
    monkeypatch.setenv("GLIMMER_BASE_URL", "https://example--glimmer.modal.run")
    assert [r.model for r in routing.resolve("judge").routes] == ["muse-glimmer", "muse-spark-1.3"]
    monkeypatch.delenv("GLIMMER_BASE_URL")
    monkeypatch.setenv("OPEN_WEIGHTS_ONLY", "1")
    assert routing.resolve("judge").mode == "mock"
    assert routing.resolve("review_rules").mode == "mock"  # the rule writer has no Glimmer either


def test_unknown_stage_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="unknown provider stage"):
        providers.complete("nope", providers.ModelRequest(messages=[]))
    with pytest.raises(ValueError, match="segment stage"):
        providers.complete("segment", providers.ModelRequest(messages=[]))
