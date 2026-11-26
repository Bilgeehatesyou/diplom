"""
Liveness (амьд эсэхийн) даалгавар — урьдчилан бичсэн видео / тогтмол зураг илгээх халдлагаас хамгаална.

Шалгалтын үеэр санамсаргүй цагт сервер оюутанд "толгойгоо хажуу тийш эргүүлээд буцаа" гэсэн даалгавар
илгээнэ. CHALLENGE_TIMEOUT_SEC дотор калибровктой baseline-аас толгой MIN_TURN_DEG-ээс их эргэвэл
амжилттай. Бичлэг/зураг санамсаргүй цагт ирэх даалгаварт хариу үйлдэл үзүүлэх боломжгүй.

Даалгавар идэвхтэй үед gaze_away бүртгэгдэхгүй (даалгаврыг биелүүлж байгаа оюутныг шийтгэхгүй).
"""
import os
import random

CHALLENGE_TIMEOUT_SEC = 8.0
MIN_TURN_DEG          = 20.0
FIRST_AFTER_SEC       = (60.0, 180.0)    # эхний даалгавар холбогдсоноос хойш
if os.getenv("LIVENESS_FIRST_AFTER"):    # демо/тест: эхний даалгаврыг тогтсон хугацааны дараа
    FIRST_AFTER_SEC = (float(os.environ["LIVENESS_FIRST_AFTER"]),) * 2
INTERVAL_SEC          = (240.0, 480.0)   # дараагийнх (4–8 мин)
RETRY_AFTER_FAIL_SEC  = (45.0, 90.0)     # биелүүлээгүй бол удахгүй дахин


def next_delay(first: bool, failed: bool, rng: random.Random = random) -> float:
    lo, hi = FIRST_AFTER_SEC if first else (RETRY_AFTER_FAIL_SEC if failed else INTERVAL_SEC)
    return rng.uniform(lo, hi)


def start(ctx: dict, challenge_id: int, now: float) -> dict:
    ctx["_liveness"] = {"id": challenge_id, "deadline": now + CHALLENGE_TIMEOUT_SEC, "max_turn": 0.0, "seen": 0}
    return ctx["_liveness"]


def observe(ctx: dict, d_yaw: float) -> None:
    """analyzer-аас кадр бүрд (калибровктой нүүр илэрсэн үед) дуудна."""
    ch = ctx.get("_liveness")
    if ch is not None:
        ch["max_turn"] = max(ch["max_turn"], abs(d_yaw))
        ch["seen"] += 1


def active(ctx: dict) -> bool:
    return ctx.get("_liveness") is not None


def evaluate(ctx: dict, now: float) -> str | None:
    """Хугацаа дуусаагүй бол None (амжилттай бол шууд "pass"), дууссан бол "pass" | "fail"."""
    ch = ctx.get("_liveness")
    if ch is None:
        return None
    if ch["max_turn"] >= MIN_TURN_DEG:
        ctx.pop("_liveness", None)
        return "pass"
    if now < ch["deadline"]:
        return None
    ctx.pop("_liveness", None)
    return "fail"
