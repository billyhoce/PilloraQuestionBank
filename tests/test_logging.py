import io
import logging

from fastapi.testclient import TestClient
from question_extractor.logcontext import log_context

from app.log_context import ContextFilter
from app.logging_setup import QUIET_LOGGERS, TextFormatter, configure_logging
from app.main import app

JOB = "139b2f78-3adf-4f7a-bdc6-d82f82e87662"


def _logger(stream):
    h = logging.StreamHandler(stream)
    h.setFormatter(TextFormatter())
    h.addFilter(ContextFilter())
    lg = logging.getLogger("test.logging.ctx")
    lg.handlers = [h]
    lg.propagate = False
    lg.setLevel(logging.DEBUG)
    return lg


def test_a_line_names_its_context_once_and_outside_one_has_none():
    buf = io.StringIO()
    lg = _logger(buf)
    with log_context(job_id=JOB, section="q1", stage="locate", task_attempt=1):
        lg.warning("page 9: something")
        with log_context(stage="render", task_attempt=2):
            lg.info("nested")
    lg.info("outside")
    inside, nested, outside = buf.getvalue().splitlines()
    assert inside.endswith(f"WARNING [job {JOB} q1 locate] page 9: something")
    assert nested.endswith(f"INFO    [job {JOB} q1 render attempt 2] nested")  # attempt shown past the first
    assert outside.endswith("INFO    outside")
    assert inside.count(JOB) == 1


def test_fields_follow_the_message_and_a_traceback_keeps_the_line_head():
    buf = io.StringIO()
    lg = _logger(buf)
    lg.info("%s", "event", extra={"fields": {"pages": 3, "name": "a b", "skipped": None}})
    with log_context(job_id=JOB):
        try:
            1 / 0
        except ZeroDivisionError:
            lg.exception("boom")
    first, *trace = buf.getvalue().splitlines()
    assert first.endswith('event pages=3 name="a b"')
    assert "ZeroDivisionError" in trace[-1]
    assert all(f"[job {JOB}] " in line for line in trace)  # grep by job id finds the whole traceback


def test_log_event_and_job_event_read_as_sentences(caplog):
    from app.logger import log_event, log_job_event

    with caplog.at_level(logging.INFO, logger="pillora"):
        log_event("thing happened", seconds=1.5)
        log_job_event(JOB, "job cancelled (was queued)")
    plain, job_line = caplog.records
    assert plain.getMessage() == "thing happened" and plain.fields == {"seconds": 1.5}
    assert job_line.getMessage() == "job cancelled (was queued)" and job_line.job_id == JOB


def test_claude_call_is_one_line_with_tokens_cost_request_id_and_reply(caplog):
    from app.logger import MAX_REPLY_CHARS, log_claude_call

    usage = type("U", (), {"input_tokens": 41853, "output_tokens": 1847, "cache_read_input_tokens": 0})()
    with caplog.at_level(logging.INFO, logger="pillora"):
        fields = log_claude_call(
            "read paper metadata from the cover", "claude-haiku-4-5", usage, "req_1",
            reply={"school": "Raffles"}, seconds=1.87, stop_reason="tool_use",
        )
        log_claude_call("x", "claude-haiku-4-5", usage, reply="a\nb" + "c" * MAX_REPLY_CHARS, stop_reason="max_tokens")
    first, second = (r.getMessage() for r in caplog.records)
    assert first == (
        "Claude call (read paper metadata from the cover): claude-haiku-4-5, 1.9s, 41,853 in / 1,847 out tokens,"
        ' $0.0511, req_1. Reply: {"school": "Raffles"}'
    )
    assert fields["input_tokens"] == 41853 and fields["cost_usd"] == 0.051088
    # The reply's newline is escaped onto the line (2 chars), so it overruns the cap by 4.
    assert "stopped on max_tokens" in second and "\n" not in second and second.endswith("(4 more chars)")


def test_chatty_libraries_log_warnings_only():
    configure_logging()
    assert all(logging.getLogger(name).level == logging.WARNING for name in QUIET_LOGGERS)


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
    assert "[req rid-9] in request" in buf.getvalue()
