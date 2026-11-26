"""Нэвтрэлтийн brute-force хамгаалалт ба liveness даалгаврын логик."""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ratelimit import LoginLimiter  # noqa: E402
from ai import liveness  # noqa: E402


# ── Rate limit ────────────────────────────────────────────────────────────────
def test_locks_after_five_failures_for_same_user():
    lim = LoginLimiter()
    for i in range(4):
        lim.fail("1.2.3.4", "student:B1", now=100 + i)
        assert lim.retry_after("1.2.3.4", "student:B1", now=100 + i) == 0
    lim.fail("1.2.3.4", "student:B1", now=104)
    assert lim.retry_after("1.2.3.4", "student:B1", now=105) > 0
    assert lim.retry_after("1.2.3.4", "student:B1", now=104 + 301) == 0      # түгжээ дуусна


def test_other_ip_not_affected():
    lim = LoginLimiter()
    for i in range(5):
        lim.fail("1.1.1.1", "student:B1", now=10 + i)
    assert lim.retry_after("2.2.2.2", "student:B1", now=20) == 0


def test_password_spraying_from_one_ip_is_locked():
    lim = LoginLimiter()
    for i in range(20):
        lim.fail("9.9.9.9", f"student:U{i}", now=50 + i * 0.1)
    assert lim.retry_after("9.9.9.9", "student:NEW", now=60) > 0


def test_old_failures_expire_and_success_resets():
    lim = LoginLimiter()
    for i in range(4):
        lim.fail("1.2.3.4", "teacher:T", now=i)
    lim.fail("1.2.3.4", "teacher:T", now=1000)          # эхний 4 нь цонхноос гарсан
    assert lim.retry_after("1.2.3.4", "teacher:T", now=1001) == 0
    lim.success("1.2.3.4", "teacher:T")
    for i in range(4):
        lim.fail("1.2.3.4", "teacher:T", now=1002 + i)
    assert lim.retry_after("1.2.3.4", "teacher:T", now=1010) == 0


# ── Liveness ──────────────────────────────────────────────────────────────────
def test_liveness_passes_on_head_turn():
    ctx = {}
    liveness.start(ctx, 1, now=0)
    assert liveness.active(ctx)
    liveness.observe(ctx, d_yaw=5)
    assert liveness.evaluate(ctx, now=2) is None
    liveness.observe(ctx, d_yaw=-27)                      # аль ч тал руу эргэж болно
    assert liveness.evaluate(ctx, now=3) == "pass"
    assert not liveness.active(ctx)


def test_liveness_fails_for_static_video():
    ctx = {}
    liveness.start(ctx, 1, now=0)
    for t in range(8):
        liveness.observe(ctx, d_yaw=3)                    # бичлэг/зураг: хөдөлгөөнгүй
    assert liveness.evaluate(ctx, now=7.9) is None
    assert liveness.evaluate(ctx, now=8.1) == "fail"


def test_liveness_schedule_ranges():
    rng = random.Random(1)
    assert all(60 <= liveness.next_delay(True, False, rng) <= 180 for _ in range(50))
    assert all(45 <= liveness.next_delay(False, True, rng) <= 90 for _ in range(50))
    assert all(240 <= liveness.next_delay(False, False, rng) <= 480 for _ in range(50))
