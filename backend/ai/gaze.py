"""
Харцын шинжилгээ: толгойн байрлал (solvePnP → yaw/pitch градус) + нүдний хүүхэн хараа (iris),
оюутан бүрийн калибровктой.

Өмнө нь тогтмол босго (turn_ratio > 0.20, iris > 0.22) ашигладаг байсан тул камер голоос зөрсөн
оюутныг байнга "өөр тийш харсан" гэж бүртгэдэг, мөн доош харахыг (pitch) огт мэддэггүй байсан.

Одоо:
  1. Эхний CALIB_FRAMES (~5с) кадрын медианаар тухайн оюутны "дэлгэц рүү харж буй" байрлалыг тогтооно.
  2. Дараа нь baseline-аас ХЭР ЗӨРСНӨӨР шийднэ (камерын байрлалаас хамаарахгүй).
  3. Baseline нь ±MAX_BASELINE_DEG-ээр хязгаарлагдана → калибровкийн үеэр хажуу тийш харж
     системийг "сургах" боломжгүй. Суух байрлал аажмаар өөрчлөгдөхөд жижиг EMA-аар дасна,
     гэхдээ анхны калибровкоос MAX_DRIFT_DEG-ээс хэтрэхгүй.
  4. Доош харах нь (бичих, бодох) хэвийн тул дангаараа gaze_away биш — удаан үргэлжилбэл
     зөвхөн "looking_down" (low), утастай хамт бол "looking_down_phone" (high).
"""
import cv2
import numpy as np

CALIB_FRAMES          = 5       # калибровкийн кадр (1 Hz → ~5 секунд)
MAX_BASELINE_DEG      = 20.0    # камер голоос зөрөх зөвшөөрөгдөх дээд хэмжээ
MAX_BASELINE_IRIS     = 0.15
MAX_DRIFT_DEG         = 10.0    # baseline анхны калибровкоос хэр холдож болох
MAX_DRIFT_IRIS        = 0.05
ADAPT_ALPHA           = 0.02    # хэвийн байрлалд байх үеийн EMA дасал

YAW_THRESH_DEG        = 25.0    # толгой хажуу тийш эргэх
PITCH_DOWN_THRESH_DEG = 20.0    # доош харах
PITCH_UP_THRESH_DEG   = 20.0    # дээш харах (дэлгэцийн дээрх тэмдэглэл гэх мэт)
IRIS_THRESH           = 0.18    # нүд хажуу тийш (нүдний өргөний харьцаагаар)

# Ерөнхий 3D нүүрний загвар (мм), OpenCV камерын координатад: x баруун, y доош, z камераас холдох.
# Тэг эргэлт = камер руу шууд харсан нүүр. Эерэг pitch = доош харах.
_MODEL_POINTS = np.array([
    (0.0,     0.0,   0.0),    # 1   хамрын үзүүр
    (0.0,   330.0,  65.0),    # 152 эрүү
    (-225.0, -170.0, 135.0),  # 33  зураг дээрх зүүн нүдний гадна булан
    (225.0,  -170.0, 135.0),  # 263 зураг дээрх баруун нүдний гадна булан
    (-150.0,  150.0, 125.0),  # 61  амны зүүн булан
    (150.0,   150.0, 125.0),  # 291 амны баруун булан
], dtype=np.float64)
_LM_IDS = (1, 152, 33, 263, 61, 291)


def head_pose(lm, w: int, h: int) -> tuple[float, float] | None:
    """MediaPipe landmark → (yaw, pitch) градусаар. Эерэг pitch = доош."""
    try:
        pts = np.array([(lm[i].x * w, lm[i].y * h) for i in _LM_IDS], dtype=np.float64)
    except (IndexError, AttributeError):
        return None
    cam = np.array([[w, 0, w / 2], [0, w, h / 2], [0, 0, 1]], dtype=np.float64)
    ok, rvec, _ = cv2.solvePnP(_MODEL_POINTS, pts, cam, np.zeros((4, 1)),
                               flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return None
    rmat, _ = cv2.Rodrigues(rvec)
    pitch, yaw, _roll = cv2.RQDecomp3x3(rmat)[0]
    # Тоон тогтворгүй ±180 шилжилтийг засах
    if pitch > 90:
        pitch -= 180
    elif pitch < -90:
        pitch += 180
    return float(yaw), float(pitch)


def iris_offset(lm) -> float | None:
    """Хоёр нүдний iris-ийн хэвтээ байрлал (нүдний өргөний харьцаагаар), 0 = төв. Зураг дээр баруун = эерэг."""
    try:
        l_w = lm[133].x - lm[33].x          # зүүн нүд: гадна 33 → дотор 133, iris 468
        r_w = lm[263].x - lm[362].x         # баруун нүд: дотор 362 → гадна 263, iris 473
        if l_w <= 0.005 or r_w <= 0.005:
            return None
        l_iris = (lm[468].x - lm[33].x) / l_w
        r_iris = (lm[473].x - lm[362].x) / r_w
        return float((l_iris + r_iris) / 2 - 0.5)
    except (IndexError, AttributeError):
        return None


def _clip(v: float, lim: float) -> float:
    return float(max(-lim, min(lim, v)))


def gaze_step(lm, w: int, h: int, ctx: dict) -> dict:
    """
    Нэг кадрын харцыг үнэлнэ. Буцаах dict:
      state: "unknown" | "calibrating" | "calibrated" | "tracking"
      away (bool), reason (str), conf (0.5–1.0), down (bool), d_yaw/d_pitch/d_iris
    """
    pose = head_pose(lm, w, h)
    if pose is None:
        return {"state": "unknown", "away": False, "down": False}
    yaw, pitch = pose
    iris = iris_offset(lm)

    base = ctx.get("gaze_baseline")
    if base is None:
        samples = ctx.setdefault("_gaze_samples", [])
        samples.append((yaw, pitch, iris if iris is not None else 0.0))
        if len(samples) < CALIB_FRAMES:
            return {"state": "calibrating", "away": False, "down": False}
        med = np.median(np.array(samples), axis=0)
        base = {"yaw":   _clip(med[0], MAX_BASELINE_DEG),
                "pitch": _clip(med[1], MAX_BASELINE_DEG),
                "iris":  _clip(med[2], MAX_BASELINE_IRIS)}
        base["origin"] = {k: base[k] for k in ("yaw", "pitch", "iris")}
        ctx["gaze_baseline"] = base
        ctx["gaze_calibrated"] = True
        ctx.pop("_gaze_samples", None)
        return {"state": "calibrated", "away": False, "down": False}

    d_yaw   = yaw - base["yaw"]
    d_pitch = pitch - base["pitch"]
    d_iris  = (iris - base["iris"]) if iris is not None else 0.0

    head_away = abs(d_yaw) > YAW_THRESH_DEG
    look_up   = d_pitch < -PITCH_UP_THRESH_DEG
    eye_away  = abs(d_iris) > IRIS_THRESH
    down      = d_pitch > PITCH_DOWN_THRESH_DEG

    # Хэвийн байрлалд байх үед baseline-ийг аажмаар дасгана (анхны утгаас хэт холдохгүй)
    if (abs(d_yaw) < YAW_THRESH_DEG / 2 and abs(d_pitch) < PITCH_DOWN_THRESH_DEG / 2
            and abs(d_iris) < IRIS_THRESH / 2):
        for k, v, lim in (("yaw", yaw, MAX_DRIFT_DEG), ("pitch", pitch, MAX_DRIFT_DEG),
                          ("iris", iris, MAX_DRIFT_IRIS)):
            if v is None:
                continue
            o = base["origin"][k]
            base[k] = float(np.clip(base[k] * (1 - ADAPT_ALPHA) + v * ADAPT_ALPHA, o - lim, o + lim))

    # Confidence: босгон дээр 0.5, босгоос 2 дахин хэтэрвэл 1.0 (оноонд жин болно)
    if head_away:
        reason, conf = f"толгой {abs(d_yaw):.0f}° эргэсэн", abs(d_yaw) / (2 * YAW_THRESH_DEG)
    elif look_up:
        reason, conf = f"дээш {abs(d_pitch):.0f}° харсан", abs(d_pitch) / (2 * PITCH_UP_THRESH_DEG)
    elif eye_away:
        reason, conf = "нүдээ хажуу тийш хазайлгасан", abs(d_iris) / (2 * IRIS_THRESH)
    else:
        reason, conf = "", 0.0

    return {"state": "tracking", "away": head_away or look_up or eye_away, "reason": reason,
            "conf": round(float(np.clip(conf, 0.5, 1.0)), 2), "down": down,
            "d_yaw": d_yaw, "d_pitch": d_pitch, "d_iris": d_iris}
