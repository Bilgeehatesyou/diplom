"""
data/newdata/{computermic,webcammic}/{normal,talking,whisper}/*.webm
файлуудыг models/training_data/{class}/ дотор нэгтгэнэ.

Class нэрүүд:
    whisper → whispering (production label-тай ижил)
    multiple → augment_multiple_audio.py-аар үүснэ

Хэрэглэх:
    python scripts/prepare_training_data.py
"""

import shutil
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent
SRC_BASE = ROOT / "data" / "newdata"
DST_BASE = ROOT / "models" / "training_data"

# Source folder (mic-тэй) → target class name
CLASS_MAP = {
    "normal":     "normal",
    "talking":    "talking",
    "whisper":    "whispering",   # rename: whisper → whispering
}

MICS = ["computermic", "webcammic"]

# Mic-аас гадуур (newdata-н доор шууд) дамжих class-ууд
# Жнь: newdata/multiple/*.webm → training_data/multiple/
DIRECT_CLASSES = {
    "multiple": "multiple",
}


def main():
    if not SRC_BASE.exists():
        print(f"❌ Source олдсонгүй: {SRC_BASE}")
        return

    total = 0

    # ── 1. mic-тэй classes (normal, talking, whispering) ─────────────────
    for src_cls, dst_cls in CLASS_MAP.items():
        dst_dir = DST_BASE / dst_cls
        dst_dir.mkdir(parents=True, exist_ok=True)

        # Хуучин файлуудыг арилгах (зөвхөн нэр prefix-тэй)
        for old in dst_dir.glob("cm_*.webm"):
            old.unlink()
        for old in dst_dir.glob("wc_*.webm"):
            old.unlink()

        copied = 0
        for mic in MICS:
            src_dir = SRC_BASE / mic / src_cls
            if not src_dir.exists():
                continue
            prefix = "cm" if mic == "computermic" else "wc"
            for src_file in sorted(src_dir.glob("*.webm")):
                dst_file = dst_dir / f"{prefix}_{src_file.stem}.webm"
                shutil.copy2(src_file, dst_file)
                copied += 1
        total += copied
        print(f"  {dst_cls:12} ← {copied:3} файл (mic-аас)")

    # ── 2. mic-гүй classes (multiple) — шууд newdata/multiple/-аас ────────
    for src_cls, dst_cls in DIRECT_CLASSES.items():
        dst_dir = DST_BASE / dst_cls
        dst_dir.mkdir(parents=True, exist_ok=True)

        # Хуучин synthetic augment файлуудыг арилгах
        for old in dst_dir.glob("*aug_multiple_*.webm"):
            old.unlink()
        for old in dst_dir.glob("real_*.webm"):
            old.unlink()

        src_dir = SRC_BASE / src_cls
        copied = 0
        if src_dir.exists():
            for src_file in sorted(src_dir.glob("*.webm")):
                dst_file = dst_dir / f"real_{src_file.stem}.webm"
                shutil.copy2(src_file, dst_file)
                copied += 1
        total += copied
        print(f"  {dst_cls:12} ← {copied:3} файл (newdata-аас)")

    print(f"\n✅ Нийт {total} файл {DST_BASE} дотор хуулсан")


if __name__ == "__main__":
    main()
