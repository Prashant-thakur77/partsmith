from partsmith_schemas import ArtifactEvent, JobInput

from services.agent import mock_brain, orchestrator, providers, service
from services.agent.jobs import JobManager


def test_reply_for_a_stale_state_is_discarded(tmp_path):
    m = JobManager(root=tmp_path)
    job = m.create("fix", JobInput())
    run = orchestrator.FixRun(job, orchestrator.RunOptions())
    job.ctx = "ctx-before"

    def plan_that_outlives_its_state(req):
        job.ctx = "ctx-after"  # the user edited the part while the model was thinking
        return {"strategy": "template", "template": "spacer", "why": "test"}

    providers.register_mock("plan", plan_that_outlives_its_state)
    req = providers.ModelRequest(messages=[{"role": "user", "content": "x"}], json_schema=orchestrator.PLAN_SCHEMA)
    assert run.call("plan", req) is None
    assert any(e.t == "log" and "discarded" in e.msg for e in job.events)
    calls = [e for e in job.events if e.t == "model_call"]
    assert calls and calls[0].ctx == "ctx-before" and calls[0].mode == "mock"
    # a current reply is kept
    mock_brain.install(replace=True)
    out = run.call(
        "plan",
        providers.ModelRequest(
            messages=[], json_schema=orchestrator.PLAN_SCHEMA, mock_context={"partspec": {"template_hint": "spacer"}}
        ),
    )
    assert out is not None and out.json["template"] == "spacer"
    m.shutdown()


def test_job_detail_hides_previews_of_an_older_state(tmp_path):
    m = JobManager(root=tmp_path)
    job = m.create("fix", JobInput())
    job.write_json("state.json", {"ctx": "new"})
    job.emit(ArtifactEvent(job="", kind="preview", sha="a" * 64, url="/old", ctx="old"))
    job.emit(ArtifactEvent(job="", kind="stl", sha="b" * 64, url="/stl", ctx="old"))
    d = service.detail_of(job)
    assert "preview" not in d["artifacts"] and d["artifacts"]["stl"] == "/stl"
    job.emit(ArtifactEvent(job="", kind="preview", sha="c" * 64, url="/new", ctx="new"))
    assert service.detail_of(job)["artifacts"]["preview"] == "/new"
    m.shutdown()
