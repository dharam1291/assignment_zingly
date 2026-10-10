import asyncio

from zingly_core import IdentityLevel
from zingly_policy import BreakerConfig, CountingBreaker, Lane, LaneAdmission, LanesConfig, LevelGuard


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_guard_is_an_allow_list():
    guard = LevelGuard.from_config({"tool_min_level": {"rebook": "verified", "flight_status": "unknown"}})
    assert guard.check("flight_status", IdentityLevel.UNKNOWN).allowed
    assert not guard.check("rebook", IdentityLevel.LIKELY).allowed
    assert guard.check("rebook", IdentityLevel.VERIFIED).allowed
    assert not guard.check("refund", IdentityLevel.STRONGLY_VERIFIED).allowed


def test_lane_rejects_when_empty_and_budget_is_zero():
    clock = FakeClock()
    cfg = LanesConfig.from_config({"lanes": {"parent_rps": 4, "borrow": False, "wait_s": {"P3": 0}}})
    adm = LaneAdmission(cfg, clock)
    assert asyncio.run(adm.acquire(Lane.P3)) is True   # burst token
    assert asyncio.run(adm.acquire(Lane.P3)) is False  # empty, no wait budget
    clock.now += 1 / (4 * 0.1)                          # P3 refills at 0.4/s
    assert asyncio.run(adm.acquire(Lane.P3)) is True


def test_higher_lane_borrows_from_idle_lower_lane_but_not_reverse():
    clock = FakeClock()
    cfg = LanesConfig.from_config({"lanes": {"parent_rps": 100, "parent_burst": 10,
                                             "wait_s": {"P0": 0, "P3": 0}}})
    adm = LaneAdmission(cfg, clock)
    results = [asyncio.run(adm.acquire(Lane.P0)) for _ in range(4)]
    assert results == [True, True, True, True]  # own token + P1, P2, P3 lent theirs
    assert asyncio.run(adm.acquire(Lane.P3)) is False
    assert adm.stats()["P0.borrowed_from_P3"] == 1


def test_lower_lane_cannot_borrow_from_higher_lane():
    cfg = LanesConfig.from_config({"lanes": {"parent_rps": 100, "parent_burst": 10, "wait_s": {"P1": 0}}})
    adm = LaneAdmission(cfg)
    admitted = sum(asyncio.run(adm.acquire(Lane.P1)) for _ in range(10))
    assert admitted == 3  # its own token + P2 + P3, never P0's


def test_parent_caps_total_rate_in_real_time():
    cfg = LanesConfig.from_config({"lanes": {"parent_rps": 20, "wait_s": {"P0": 1.0}}})
    adm = LaneAdmission(cfg)

    async def burst():
        loop = asyncio.get_running_loop()
        start = loop.time()
        ok = await asyncio.gather(*(adm.acquire(Lane.P0) for _ in range(40)))
        return sum(ok), loop.time() - start

    admitted, elapsed = asyncio.run(burst())
    # P0 may borrow every lane, so only the parent caps it: 1 burst + 20/s for ~1 s, never 40
    assert 15 <= admitted <= 23, admitted


def test_breaker_opens_and_half_opens():
    clock = FakeClock()
    br = CountingBreaker(BreakerConfig(failure_threshold=2, open_seconds=5), clock)
    br.record_failure(); br.record_failure()
    assert br.state == "open" and not br.allow()
    clock.now += 5
    assert br.state == "half_open" and br.allow()
    br.record_success()
    assert br.state == "closed"
