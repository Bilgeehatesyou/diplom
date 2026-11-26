"""
WebSocket ачааллын тест — "Нэг сервер хэдэн оюутан зэрэг даах вэ?" гэсэн асуултад тоо гаргана.

N оюутныг дуурайна: тус бүр 5 fps-ээр JPEG кадр, 2с тутам WebM дуу, ~12с тутам client event
илгээнэ. Нэг багш холбогдож эхний оюутныг ажиглана. Хэмжих зүйл:

  analyses/s/student  Сервер оюутан бүрийн кадрыг секундэд хэдэн удаа шинжилж чадсан (зорилт 1.0)
  analysis p50/p95    Нэг кадрын шинжилгээний хугацаа (MediaPipe + YOLO, мс)
  audio/s/student     Дууны шинжилгээ (зорилт 0.5 = 2с тутам), хаягдсан chunk
  event latency       Client event → багшийн самбарт хүрэх хугацаа (p50/p95)
  teacher fps         Ажиглаж буй оюутны видео багшид хэдэн fps-ээр хүрч байна (зорилт 5)
  CPU / RAM           Backend процессын ачаалал

Бэлтгэл (тест DB дээр ажиллуулахыг зөвлөнө):
  python scripts/evaluation/create_pilot_users.py --prefix LOAD --count 30 --password <pw> --db <db>
  # backend:  LIVENESS=0 INCIDENTS_DIR=<түр хавтас> DATABASE_URL=sqlite+aiosqlite:///<db> uvicorn main:app
Ажиллуулах:
  python scripts/loadtest/ws_load.py --password <pw> --teacher-password <pw> --frame face.jpg \
      --audio quiet.webm --students 1,5,10,20 --duration 45
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

import websockets

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def http(api: str, method: str, path: str, body=None, token=None):
    req = urllib.request.Request(api + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def pct(vals, q):
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * len(v)))]


def server_process(port: int):
    if psutil is None:
        return None
    for c in psutil.net_connections(kind="tcp"):
        if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN and c.pid:
            return psutil.Process(c.pid)
    return None


async def run_once(n: int, a, frame: bytes, audio: bytes | None, tokens: list[str], teacher_tok: str) -> dict:
    ws_url = a.api.replace("http", "ws", 1)
    stop = asyncio.Event()
    sent_at: dict[str, float] = {}
    latencies: list[float] = []
    teacher_frames = 0
    ready = 0

    async def teacher():
        nonlocal teacher_frames
        async with websockets.connect(f"{ws_url}/ws/teacher", max_size=None) as ws:
            await ws.send(json.dumps({"type": "auth", "token": teacher_tok}))
            await ws.send(json.dumps({"action": "watch", "student_id": f"{a.prefix}01"}))
            while not stop.is_set():
                try:
                    m = await asyncio.wait_for(ws.recv(), 0.5)
                except asyncio.TimeoutError:
                    continue
                if isinstance(m, bytes):
                    if measuring.is_set():
                        teacher_frames += 1
                    continue
                d = json.loads(m)
                ev = d.get("event") or {}
                sid = d.get("student_id")
                if ev.get("event_type") == "copy_attempt" and sid in sent_at and measuring.is_set():
                    latencies.append(time.monotonic() - sent_at.pop(sid))

    async def student(i: int, tok: str):
        nonlocal ready
        sid = f"{a.prefix}{i + 1:02d}"
        async with websockets.connect(f"{ws_url}/ws/student?exam_id=exam_001", max_size=None) as ws:
            await ws.send(json.dumps({"type": "auth", "token": tok}))
            while True:
                d = json.loads(await asyncio.wait_for(ws.recv(), 30))
                if d.get("type") == "ready":
                    break
            ready += 1

            async def drain():
                try:
                    async for _ in ws:
                        pass
                except websockets.ConnectionClosed:
                    pass
            dr = asyncio.create_task(drain())
            period = 1.0 / a.fps
            next_t = time.monotonic() + random.uniform(0, period)
            next_ev = time.monotonic() + random.uniform(2, 12)
            k = 0
            while not stop.is_set():
                await ws.send(frame)
                if audio and k % int(2 * a.fps) == 0:
                    await ws.send(json.dumps({"_audio": True}))
                    await ws.send(audio)
                if time.monotonic() >= next_ev:
                    sent_at[sid] = time.monotonic()
                    await ws.send(json.dumps({"event": "copy_attempt", "detail": "loadtest"}))
                    next_ev += 12 + random.random()      # dedup цонх (10с)-оос урт
                k += 1
                next_t += period
                await asyncio.sleep(max(0.0, next_t - time.monotonic()))
            dr.cancel()

    measuring = asyncio.Event()
    tasks = [asyncio.create_task(teacher())]
    tasks += [asyncio.create_task(student(i, tokens[i])) for i in range(n)]
    proc = server_process(int(a.api.rsplit(":", 1)[1]))

    await asyncio.sleep(a.warmup)
    if ready < n:
        print(f"  ⚠ зөвхөн {ready}/{n} оюутан холбогдсон")
    m0 = http(a.api, "GET", "/api/metrics", token=teacher_tok)[1]
    if proc:
        proc.cpu_percent(None)
    measuring.set()
    t0 = time.monotonic()
    await asyncio.sleep(a.duration)
    dt = time.monotonic() - t0
    cpu = proc.cpu_percent(None) if proc else None
    m1 = http(a.api, "GET", "/api/metrics", token=teacher_tok)[1]
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    d_frames = m1["frames_analyzed"] - m0["frames_analyzed"]
    d_audio = m1["audio_analyzed"] - m0["audio_analyzed"]
    return {
        "students": n, "connected": ready, "duration_sec": round(dt, 1),
        "analyses_per_student_sec": round(d_frames / dt / n, 2),
        "analysis_ms_p50": m1["analysis_ms_p50"], "analysis_ms_p95": m1["analysis_ms_p95"],
        "audio_per_student_sec": round(d_audio / dt / n, 2) if audio else None,
        "audio_ms_p50": m1["audio_ms_p50"], "audio_ms_p95": m1["audio_ms_p95"],
        "audio_dropped": m1["audio_dropped"] - m0["audio_dropped"],
        "event_latency_p50": round(pct(latencies, 0.5), 2) if latencies else None,
        "event_latency_p95": round(pct(latencies, 0.95), 2) if latencies else None,
        "teacher_fps": round(teacher_frames / dt, 1),
        "cpu_percent": round(cpu, 0) if cpu is not None else None,
        "cpu_cores": psutil.cpu_count() if psutil else None,
        "rss_mb": m1["rss_mb"],
    }


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--prefix", default="LOAD")
    ap.add_argument("--password", required=True)
    ap.add_argument("--teacher", default="Tsetsegee")
    ap.add_argument("--teacher-password", required=True)
    ap.add_argument("--students", default="1,5,10,20")
    ap.add_argument("--duration", type=float, default=45)
    ap.add_argument("--warmup", type=float, default=10)
    ap.add_argument("--fps", type=float, default=5)
    ap.add_argument("--frame", type=Path, required=True, help="илгээх JPEG (нүүртэй зураг бодит ачаалал өгнө)")
    ap.add_argument("--audio", type=Path, default=None, help="2с WebM/Opus файл (заавал биш)")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "results.jsonl")
    a = ap.parse_args()

    frame = a.frame.read_bytes()
    audio = a.audio.read_bytes() if a.audio else None
    counts = [int(x) for x in a.students.split(",")]
    st, t = http(a.api, "POST", "/api/login/teacher", {"name": a.teacher, "password": a.teacher_password})
    assert st == 200, t
    tokens = []
    for i in range(max(counts)):
        st, s = http(a.api, "POST", "/api/login/student",
                     {"student_id": f"{a.prefix}{i + 1:02d}", "password": a.password})
        assert st == 200, (i, s)
        st, e = http(a.api, "POST", "/api/exam/start", {"exam_id": "exam_001"}, s["token"])
        assert st == 200, (i, e)
        tokens.append(s["token"])

    print(f"{'N':>3} {'анализ/с':>9} {'p50мс':>6} {'p95мс':>6} {'аудио/с':>8} {'хаягд':>6} "
          f"{'event p50':>9} {'p95':>5} {'багш fps':>8} {'CPU%':>6} {'RAM MB':>7}")
    for n in counts:
        r = await run_once(n, a, frame, audio, tokens, t["token"])
        with open(a.out, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M"), **r}, ensure_ascii=False) + "\n")
        print(f"{n:>3} {r['analyses_per_student_sec']:>9} {r['analysis_ms_p50']!s:>6} {r['analysis_ms_p95']!s:>6} "
              f"{r['audio_per_student_sec']!s:>8} {r['audio_dropped']:>6} {r['event_latency_p50']!s:>9} "
              f"{r['event_latency_p95']!s:>5} {r['teacher_fps']:>8} {r['cpu_percent']!s:>6} {r['rss_mb']!s:>7}",
              flush=True)
        await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
