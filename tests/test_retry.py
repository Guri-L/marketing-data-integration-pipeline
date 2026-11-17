import pytest

from marketing_pipeline.exceptions import ExtractionError, TransientExtractionError
from marketing_pipeline.retry import retry


def test_retries_transient_errors_then_succeeds():
    calls = []

    @retry(attempts=3)
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise TransientExtractionError("503")
        return "ok"

    assert flaky() == "ok"
    assert len(calls) == 3


def test_gives_up_after_max_attempts():
    calls = []

    @retry(attempts=2)
    def always_down():
        calls.append(1)
        raise TransientExtractionError("503")

    with pytest.raises(TransientExtractionError):
        always_down()
    assert len(calls) == 2


def test_permanent_errors_are_not_retried():
    calls = []

    @retry(attempts=5)
    def unauthorized():
        calls.append(1)
        raise ExtractionError("401")

    with pytest.raises(ExtractionError):
        unauthorized()
    assert len(calls) == 1


def test_backoff_grows_and_is_capped():
    delays = []

    @retry(attempts=5, base_delay=2, max_delay=5, sleep=delays.append)
    def always_down():
        raise TransientExtractionError("503")

    with pytest.raises(TransientExtractionError):
        always_down()
    assert len(delays) == 4
    assert all(d <= 5 for d in delays)
    assert delays[2] >= delays[0]
