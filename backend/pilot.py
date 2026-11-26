"""
Pilot үнэлгээний горим (PILOT_MODE=1).

Оролцогч шалгалт өгөх үеэр дэлгэцийн дээд хэсэгт протоколын заавар гарч, тогтсон үйлдлүүдийг
(хажуу тийш харах, утас гаргах, ярих ...) хийнэ. Алхам бүрийн эхлэх цагийг сервер бүртгэдэг тул
ground truth автоматаар үүснэ; scripts/evaluation/pilot_report.py нь үүнийг системийн
event-үүдтэй тулган Precision / Recall / F1, хоцролт, худал дохиоллын давтамжийг тооцно.

Энгийн ашиглалтад унтраалттай байна.
"""
import json
import os
from pathlib import Path

PILOT_MODE = os.getenv("PILOT_MODE", "0") == "1"
PROTOCOL_PATH = Path(__file__).resolve().parent / "pilot_protocol.json"


def load_protocol() -> dict:
    with open(PROTOCOL_PATH, encoding="utf-8") as f:
        return json.load(f)


def public_protocol() -> dict | None:
    """Client-д илгээх хувилбар (зөвхөн заавар, хугацаа)."""
    if not PILOT_MODE:
        return None
    p = load_protocol()
    return {
        "id": p["id"],
        "steps": [{"id": s["id"], "text": s["text"], "duration": s["duration"],
                   "category": s["category"], "helper": bool(s.get("helper"))}
                  for s in p["steps"]],
    }
