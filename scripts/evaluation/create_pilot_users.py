"""
Pilot оролцогчдод оюутны бүртгэл үүсгэнэ (PILOT01, PILOT02, ...) — bcrypt нууц үгтэй.
Аль хэдийн байгаа бүртгэлийг хөндөхгүй.

Ажиллуулах (backend унтарсан эсвэл асаалттай байсан ч болно):
  python scripts/evaluation/create_pilot_users.py --count 10 --password <нууц үг>
  python scripts/evaluation/create_pilot_users.py --count 3 --password <нууц үг> --db path/to/aiproctor.db
"""
import argparse
import sqlite3
from pathlib import Path

import bcrypt

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--password", required=True, help="бүх pilot бүртгэлийн нууц үг")
    ap.add_argument("--prefix", default="PILOT")
    ap.add_argument("--db", type=Path, default=ROOT / "backend" / "aiproctor.db")
    a = ap.parse_args()
    if len(a.password) < 6:
        raise SystemExit("Нууц үг дор хаяж 6 тэмдэгт байна")

    con = sqlite3.connect(str(a.db))
    pw_hash = bcrypt.hashpw(a.password.encode(), bcrypt.gensalt(rounds=12)).decode()
    created = []
    for i in range(1, a.count + 1):
        sid = f"{a.prefix}{i:02d}"
        if con.execute("SELECT 1 FROM students WHERE id = ?", (sid,)).fetchone():
            continue
        con.execute("INSERT INTO students (id, name, department, password) VALUES (?, ?, ?, ?)",
                    (sid, f"Оролцогч {i:02d}", "Pilot үнэлгээ", pw_hash))
        created.append(sid)
    con.commit()
    con.close()
    print(f"Үүсгэсэн: {', '.join(created) if created else 'шинэ бүртгэл алга (бүгд байсан)'}")


if __name__ == "__main__":
    main()
