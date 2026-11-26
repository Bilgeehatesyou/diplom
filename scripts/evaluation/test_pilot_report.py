"""
pilot_report.py-ийн тооцооллыг гараар бэлдсэн гүйлт дээр шалгана (хариу нь урьдчилан мэдэгдэнэ).

Ажиллуулах:  python scripts/evaluation/test_pilot_report.py
"""
import json
import math
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pilot_report as pr  # noqa: E402

PROTOCOL = json.loads(pr.PROTOCOL.read_text(encoding="utf-8"))


def build_db(path: str):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE exam_sessions (id INTEGER PRIMARY KEY, student_id TEXT);
        CREATE TABLE pilot_marks (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INT, protocol TEXT,
                                  step_index INT, step_id TEXT, started_at TEXT, skipped INT);
        CREATE TABLE risk_events (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INT, event_type TEXT,
                                  severity TEXT, timestamp TEXT, confidence REAL);
    """)
    con.execute("INSERT INTO exam_sessions VALUES (7, 'PILOT01')")
    t0 = datetime(2026, 11, 27, 10, 0, 0)
    start = {}
    t = t0
    for i, s in enumerate(PROTOCOL["steps"]):
        start[s["id"]] = t
        con.execute("INSERT INTO pilot_marks (session_id, protocol, step_index, step_id, started_at, skipped) "
                    "VALUES (7, ?, ?, ?, ?, 0)", (PROTOCOL["id"], i, s["id"], str(t)))
        if s["id"] == "second_person":     # туслах хүнгүй → алгассан
            con.execute("INSERT INTO pilot_marks (session_id, protocol, step_index, step_id, started_at, skipped) "
                        "VALUES (7, ?, ?, ?, ?, 1)", (PROTOCOL["id"], i, s["id"], str(t + timedelta(seconds=1))))
        t += timedelta(seconds=s["duration"])
    con.execute("INSERT INTO pilot_marks (session_id, protocol, step_index, step_id, started_at, skipped) "
                "VALUES (7, ?, ?, 'end', ?, 0)", (PROTOCOL["id"], len(PROTOCOL["steps"]), str(t)))

    dur = {s["id"]: s["duration"] for s in PROTOCOL["steps"]}

    def ev(step, offset, etype, sev="high"):
        con.execute("INSERT INTO risk_events (session_id, event_type, severity, timestamp, confidence) "
                    "VALUES (7, ?, ?, ?, 0.9)", (etype, sev, str(start[step] + timedelta(seconds=offset))))

    ev("calibrate", -30, "gaze_away", "medium")          # протоколоос өмнө → тооцохгүй
    ev("calibrate", 3, "gaze_away", "medium")            # setup → саармаг
    ev("normal_1", 60, "gaze_away", "medium")            # хэвийн үеийн FP
    ev("look_left", 3, "gaze_away", "medium")            # TP, хоцролт 3с
    # look_right: илрээгүй (FN)
    ev("write_paper", 5, "looking_down", "low")          # зөвшөөрөгдсөн → саармаг
    ev("write_paper", 8, "gaze_away", "medium")          # hard negative FP
    ev("phone", 2, "object_detected")                    # TP
    ev("phone", 4, "gaze_away", "medium")                # зөвшөөрөгдсөн
    ev("phone_lap", dur["phone_lap"] + 2, "looking_down_phone")   # tolerance дотор хоцорсон TP (22с)
    # book: илрээгүй (FN)
    ev("leave", 5, "face_missing")                       # TP
    ev("second_person", 5, "multiple_faces")             # алгассан алхам → саармаг
    ev("talk", 4, "audio_speech")                        # TP
    ev("whisper", 6, "audio_whispering", "medium")       # TP
    ev("read_aloud", 3, "audio_speech")                  # hard negative FP
    ev("tab", 0.5, "tab_switch", "medium")               # TP
    ev("tab", 1, "fullscreen_exit", "medium")            # зөвшөөрөгдсөн
    con.commit()
    return con


def run():
    with tempfile.TemporaryDirectory() as d:
        con = build_db(str(Path(d) / "t.db"))
        runs = pr.load_runs(con, PROTOCOL, None)
        m = pr.evaluate(runs, PROTOCOL, lambda sid: pr.load_events(con, sid), PROTOCOL["tolerance_sec"])
        report = pr.write_outputs(m, PROTOCOL, Path(d) / "out")
        text = report.read_text(encoding="utf-8")
        con.close()

    D = m["detectors"]
    checks = [
        ("one complete run", m["runs"] == 1),
        ("gaze recall 1/2", (D["gaze"]["detected"], D["gaze"]["steps"]) == (1, 2)),
        ("gaze precision 1/3 (normal + hard-negative FP)", (D["gaze"]["tp_events"], D["gaze"]["fp_events"]) == (1, 2)),
        ("gaze latency 3s", D["gaze"]["latency_median"] == 3.0),
        ("object recall 2/3 (book missed)", (D["object"]["detected"], D["object"]["steps"]) == (2, 3)),
        ("late phone_lap detection inside tolerance counts", m["steps"]["phone_lap"]["detected"] == 1
                                                             and m["steps"]["phone_lap"]["latency_median"] == 22.0),
        ("object precision 100%", D["object"]["precision"] == 1.0),
        ("skipped second_person excluded", D["multiple_faces"]["steps"] == 0 and D["multiple_faces"]["recall"] is None),
        ("speech precision 1/2 (read aloud FP)", (D["speech"]["tp_events"], D["speech"]["fp_events"]) == (1, 1)),
        ("whisper + tab + face_missing detected", all(D[k]["recall"] == 1.0 for k in ("whisper", "tab", "face_missing"))),
        ("normal FP = 1 over 330s → 10.9/h", m["normal"]["fp_total"] == 1 and m["normal"]["seconds"] == 330.0
                                            and math.isclose(m["normal"]["fp_per_hour"], 3600 / 330)),
        ("hard negatives: write_paper & read_aloud flagged, typing clean",
            m["hard_negatives"]["write_paper"]["runs_with_fp"] == 1
            and m["hard_negatives"]["read_aloud"]["runs_with_fp"] == 1
            and m["hard_negatives"]["typing"]["runs_with_fp"] == 0),
        ("wilson CI sane", pr.wilson(1, 2) is not None and pr.wilson(1, 2)[0] < 0.5 < pr.wilson(1, 2)[1]),
        ("markdown report rendered", "Детектор тус бүрээр" in text and "Харц" in text),
    ]
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
    passed = sum(ok for _, ok in checks)
    print(f"{passed}/{len(checks)} passed")
    return passed == len(checks)


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
