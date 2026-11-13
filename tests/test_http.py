import pytest

from enzyme_searcher.http import RateLimiter, with_retries


def test_retries_with_exponential_backoff():
    delays, calls = [], {"n": 0}

    @with_retries(attempts=4, base_delay=1, sleep=delays.append)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 4:
            raise IOError("down")
        return "ok"

    assert flaky() == "ok" and delays == [1, 2, 4]


def test_retries_exhausted():
    @with_retries(attempts=2, base_delay=0, sleep=lambda s: None)
    def broken():
        raise ValueError("x")

    with pytest.raises(ValueError):
        broken()


def test_rate_limiter_three_per_second():
    clock, slept = {"t": 0.0}, []

    def sleep(s):
        slept.append(round(s, 3))
        clock["t"] += s

    limiter = RateLimiter(3, clock=lambda: clock["t"], sleep=sleep)
    for _ in range(4):
        limiter.wait()
    assert slept == [0.333, 0.333, 0.333]
