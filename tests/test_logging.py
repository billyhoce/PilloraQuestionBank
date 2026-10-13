import io
import json
import logging

from fastapi.testclient import TestClient
from question_extractor.logcontext import log_context

from app.log_context import ContextFilter
from app.logging_setup import JsonFormatter
from app.main import app


def _logger(stream):
    h = logging.StreamHandler(stream)
    h.setFormatter(JsonFormatter())
    h.addFilter(ContextFilter())
    lg = logging.getLogger("test.logging.ctx")
    lg.handlers = [h]
    lg.propagate = False
    lg.setLevel(logging.DEBUG)
    return lg


def test_records_inside_a_context_carry_it_and_outside_do_not():
    buf = io.StringIO()
    lg = _logger(buf)
    with log_context(job_id="j1", section="q1", stage="locate", task_attempt=2):
        lg.info("inside")
        with log_context(stage="render"):
            lg.info("nested")
    lg.info("outside")
    inside, nested, outside = (json.loads(x) for x in buf.getvalue().splitlines())
    assert (inside["job_id"], inside["section"], inside["stage"], inside["task_attempt"]) == ("j1", "q1", "locate", 2)
    assert nested["stage"] == "render" and nested["job_id"] == "j1"
    assert outside["job_id"] is None and outside["stage"] is None
    assert {"ts", "level", "logger", "msg", "request_id", "user_id"} <= set(inside)


def test_structured_fields_and_exceptions_are_json():
    buf = io.StringIO()
    lg = _logger(buf)
    from app.logger import log_event

    log_event("x", "step", seconds=1.5)
    try:
        1 / 0
    except ZeroDivisionError:
        lg.exception("boom")
    assert "ZeroDivisionError" in json.loads(buf.getvalue())["exc"]


def test_runner_stamps_task_context_on_stage_logs(tmp_path):
    """The pipeline runner opens the context around each claimed task."""
    import pipeline.runner as runner_mod
    from question_extractor.logcontext import current_context

    seen = []

    class Fake(runner_mod.Runner):
        def __init__(self):
            pass

        def _run_claimed(self, task):
            seen.append(dict(current_context()))

    class Store:
        def reset_stale(self, _):
            return []

        def claim_ready(self, _):
            return type("T", (), {"job_id": "J", "section": "q1", "stage": "locate", "attempts": 1})()

    r = Fake()
    r.store = Store()
    r.config = type("C", (), {"retry_limit": 1, "lease_seconds": 1})()
    r.run_one()
    assert seen == [{"job_id": "J", "section": "q1", "stage": "locate", "task_attempt": 1}]
    assert "job_id" not in current_context()


def test_request_id_generated_and_echoed():
    client = TestClient(app)
    r = client.get("/api/health")
    assert len(r.headers["X-Request-ID"]) >= 16
    r2 = client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert r2.headers["X-Request-ID"] == "abc-123"


def test_request_id_reaches_records():
    buf = io.StringIO()
    lg = _logger(buf)

    @app.get("/api/_test_log")
    def _t():
        lg.info("in request")
        return {}

    TestClient(app).get("/api/_test_log", headers={"X-Request-ID": "rid-9"})
    assert json.loads(buf.getvalue())["request_id"] == "rid-9"
