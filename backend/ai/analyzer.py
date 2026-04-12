import cv2
import numpy as np
from datetime import datetime
from dataclasses import dataclass, asdict

try:
    import mediapipe as mp
    _face_det  = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.6)
    _face_mesh = mp.solutions.face_mesh.FaceMesh(max_num_faces=2, refine_landmarks=True,
                     min_detection_confidence=0.6, min_tracking_confidence=0.5)
    MP_OK = True
    print("[AI] MediaPipe ✓")
except Exception as e:
    MP_OK = False
    print(f"[AI] MediaPipe алдаа: {e}")

try:
    from ultralytics import YOLO
    _yolo   = YOLO("yolov8n.pt")
    YOLO_OK = True
    print("[AI] YOLOv8 ✓")
except Exception as e:
    _yolo   = None
    YOLO_OK = False
    print(f"[AI] YOLO алдаа: {e}")

FORBIDDEN_OBJECTS = {"cell phone", "book", "laptop", "remote"}

@dataclass
class DetectionEvent:
    event_type : str
    severity   : str
    message    : str
    confidence : float
    timestamp  : str
    def to_dict(self): return asdict(self)

def analyze_frame(frame: np.ndarray, ctx: dict) -> list:
    events = []
    now    = datetime.now().isoformat()
    if frame is None or frame.size == 0:
        return events
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # 1. Нүүр
    if MP_OK:
        faces = (_face_det.process(rgb).detections or [])
        n     = len(faces)
        if n == 0:
            ctx["face_miss_count"] = ctx.get("face_miss_count", 0) + 1
            m = ctx["face_miss_count"]
            if m >= 5 and m % 5 == 0:
                events.append(DetectionEvent("face_missing","high",
                    f"Нүүр кадраас {m} секунд гарсан", 0.95, now))
        else:
            ctx["face_miss_count"] = 0

        # 2. Олон хүн
        if n > 1:
            conf = float(faces[1].score[0]) if faces[1].score else 0.7
            events.append(DetectionEvent("multiple_faces","high",
                f"Камерт {n} хүн илэрлээ", round(conf,2), now))

        # 3. Харц
        mesh = _face_mesh.process(rgb)
        if mesh.multi_face_landmarks:
            lm = mesh.multi_face_landmarks[0].landmark
            dx = abs(lm[263].x - lm[33].x)
            dy = abs(lm[1].y - (lm[33].y + lm[263].y) / 2)
            if dx < 0.06 or dy > 0.08:
                ctx["gaze_away_count"] = ctx.get("gaze_away_count", 0) + 1
                g = ctx["gaze_away_count"]
                if g >= 15 and g % 15 == 0:
                    events.append(DetectionEvent("gaze_away","medium",
                        f"Дэлгэцээс {g} секунд өөр тийш харсан",
                        round(max(0, 1 - dx / 0.1), 2), now))
            else:
                ctx["gaze_away_count"] = 0

    # 4. Объект
    if YOLO_OK and _yolo:
        for r in _yolo.predict(frame, conf=0.45, verbose=False):
            for box in r.boxes:
                name = _yolo.names[int(box.cls)]
                if name in FORBIDDEN_OBJECTS:
                    last = ctx.get(f"last_{name}", -999)
                    cur  = ctx.get("frame_no", 0)
                    if cur - last > 10:
                        ctx[f"last_{name}"] = cur
                        events.append(DetectionEvent("object_detected","high",
                            f'"{name}" объект илэрлээ', round(float(box.conf),2), now))

    ctx["frame_no"] = ctx.get("frame_no", 0) + 1
    return events
