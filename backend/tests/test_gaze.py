"""
Харцын модулийн unit test — MediaPipe шаардлагагүй.
3D нүүрийг мэдэгдэж буй yaw/pitch-ээр эргүүлж камерт проекцлоод, landmark болгон өгнө.

Ажиллуулах:  cd backend && python -m pytest tests/test_gaze.py -q
         эсвэл cd backend && python tests/test_gaze.py
"""
import math
import os
import sys
from types import SimpleNamespace

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai import gaze  # noqa: E402

W, H = 640, 360
CAM = np.array([[W, 0, W / 2], [0, W, H / 2], [0, 0, 1]], dtype=np.float64)

# Загварын цэгүүд + нүдний дотор булан, хүүхэн харааны төв (gaze._MODEL_POINTS-тэй ижил координат)
_POINTS = {
    1:   (0.0, 0.0, 0.0),
    152: (0.0, 330.0, 65.0),
    33:  (-225.0, -170.0, 135.0),
    263: (225.0, -170.0, 135.0),
    61:  (-150.0, 150.0, 125.0),
    291: (150.0, 150.0, 125.0),
    133: (-75.0, -170.0, 135.0),
    362: (75.0, -170.0, 135.0),
}


def make_landmarks(yaw_deg: float = 0.0, pitch_deg: float = 0.0, iris_shift: float = 0.0):
    """iris_shift: нүдний өргөний харьцаагаар хүүхэн харааг хэвтээ чиглэлд шилжүүлнэ."""
    rvec, _ = cv2.Rodrigues(cv2.Rodrigues(np.array([math.radians(pitch_deg), 0, 0]))[0]
                            @ cv2.Rodrigues(np.array([0, math.radians(yaw_deg), 0]))[0])
    ids = list(_POINTS)
    pts3 = np.array([_POINTS[i] for i in ids], dtype=np.float64)
    pts2, _ = cv2.projectPoints(pts3, rvec, np.array([0.0, 0.0, 2500.0]), CAM, np.zeros(4))
    lm = [SimpleNamespace(x=0.0, y=0.0) for _ in range(478)]
    for i, (x, y) in zip(ids, pts2.reshape(-1, 2)):
        lm[i] = SimpleNamespace(x=x / W, y=y / H)
    # Хүүхэн хараа = нүдний булангуудын дунд + шилжилт
    for outer, inner, iris_id in ((33, 133, 468), (362, 263, 473)):
        a, b = lm[outer], lm[inner]
        lm[iris_id] = SimpleNamespace(x=(a.x + b.x) / 2 + iris_shift * (b.x - a.x), y=(a.y + b.y) / 2)
    return lm


def calibrate(ctx, yaw=0.0, pitch=0.0):
    for _ in range(gaze.CALIB_FRAMES):
        r = gaze.gaze_step(make_landmarks(yaw, pitch), W, H, ctx)
    assert r["state"] == "calibrated"
    return ctx


def test_head_pose_recovers_known_angles():
    for yaw, pitch in [(0, 0), (30, 0), (-30, 0), (0, 25), (0, -20), (-20, 15)]:
        est_yaw, est_pitch = gaze.head_pose(make_landmarks(yaw, pitch), W, H)
        assert abs(abs(est_yaw) - abs(yaw)) < 2.0, (yaw, est_yaw)
        assert abs(est_pitch - pitch) < 2.0, (pitch, est_pitch)


def test_pitch_sign_positive_is_looking_down():
    _, pitch = gaze.head_pose(make_landmarks(0, 25), W, H)
    assert pitch > 20   # эрүү цээж рүү → эерэг


def test_off_center_camera_is_not_flagged_after_calibration():
    # Камер хажуу/доор байрласан: оюутан дэлгэц рүү харахад толгой 18°, 12° байрлалтай
    ctx = calibrate({}, yaw=18, pitch=12)
    r = gaze.gaze_step(make_landmarks(18, 12), W, H, ctx)
    assert r["state"] == "tracking" and not r["away"] and not r["down"]


def test_head_turn_from_baseline_is_flagged():
    ctx = calibrate({}, yaw=10)
    r = gaze.gaze_step(make_landmarks(10 + 35, 0), W, H, ctx)
    assert r["away"] and "эргэсэн" in r["reason"]
    assert 0.5 <= r["conf"] <= 1.0


def test_looking_down_is_separate_from_away():
    ctx = calibrate({})
    r = gaze.gaze_step(make_landmarks(0, 30), W, H, ctx)
    assert r["down"] and not r["away"]


def test_looking_up_is_flagged():
    ctx = calibrate({})
    r = gaze.gaze_step(make_landmarks(0, -30), W, H, ctx)
    assert r["away"] and "дээш" in r["reason"]


def test_eyes_sideways_is_flagged():
    ctx = calibrate({})
    r = gaze.gaze_step(make_landmarks(0, 0, iris_shift=0.25), W, H, ctx)
    assert r["away"] and "нүд" in r["reason"]


def test_cannot_calibrate_while_looking_away():
    # Калибровкийн үеэр 50° эргэж харсан ч baseline 20°-оор хязгаарлагдана → дараа нь илэрнэ
    ctx = calibrate({}, yaw=50)
    assert abs(ctx["gaze_baseline"]["yaw"]) <= gaze.MAX_BASELINE_DEG + 1e-6
    r = gaze.gaze_step(make_landmarks(50, 0), W, H, ctx)
    assert r["away"]


def test_baseline_drift_is_capped():
    ctx = calibrate({})
    origin = ctx["gaze_baseline"]["origin"]["yaw"]
    # Аажмаар эргэж baseline-ийг "чирэх" оролдлого
    yaw = 0.0
    for _ in range(600):
        yaw = ctx["gaze_baseline"]["yaw"] + 12.0
        gaze.gaze_step(make_landmarks(yaw, 0), W, H, ctx)
    assert abs(abs(ctx["gaze_baseline"]["yaw"]) - abs(origin)) <= gaze.MAX_DRIFT_DEG + 1e-6
    r = gaze.gaze_step(make_landmarks(origin + 40, 0), W, H, ctx)
    assert r["away"]


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"{len(fns)}/{len(fns)} passed")
