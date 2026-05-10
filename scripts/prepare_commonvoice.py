#!/usr/bin/env python3
"""
Common Voice 16.0 Mongolian — дата бэлдэх скрипт
wav2vec2.0 fine-tune хийхэд бэлтгэсэн өгөгдөл бэлдэнэ.
"""
import os
import subprocess
import sys
from pathlib import Path
import shutil

# Конфиг
LANG = "mn"
DATASET_DIR = Path("./data/commonvoice25/mn")
OUTPUT_DIR = Path("./data/wav2vec_commonvoice")
TARGET_SAMPLE_RATE = 16000
MIN_CLIP_DURATION = 1.0   # сек
MAX_CLIP_DURATION = 30.0  # сек
TRAIN_SAMPLES = 3000      # fine-tune хийхэд хүрэлцэхүйц
VAL_SAMPLES = 500

CV_VERSION = "cv-corpus-16.0-2024-06-07"


def find_audio_files():
    """Common Voice dataset-аас audio файлнуудыг олдог."""
    clips_dir = DATASET_DIR / "clips"
    if not clips_dir.exists():
        raise FileNotFoundError(f"'clips' folder олдсонгүй: {clips_dir}")

    audio_files = list(clips_dir.glob("*.mp3")) + list(clips_dir.glob("*.mp3"))
    print(f"   ✅ {len(audio_files)} audio файл олдлоо")
    return audio_files


def load_tsv(tsv_path: Path) -> list[dict]:
    """TSV файл уншиж, строудыг list болгон буцаана."""
    rows = []
    with open(tsv_path, "r", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        # header may have more columns than data rows (trailing empty fields)
        # find actual indices for fields we need
        path_idx = header.index("path")
        sentence_idx = header.index("sentence")
        for line in f:
            fields = line.strip().split("\t")
            if len(fields) <= path_idx or len(fields) <= sentence_idx:
                continue
            rows.append({
                "path": fields[path_idx],
                "sentence": fields[sentence_idx],
                "_orig": fields,
            })
    return rows


def load_durations(tsv_path: Path) -> dict:
    """clip_durations.tsv уншиж, dictionary болгон буцаана."""
    durations = {}
    with open(tsv_path, "r", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        clip_idx = header.index("clip")
        dur_idx = header.index("duration[ms]")
        for line in f:
            fields = line.strip().split("\t")
            if len(fields) > max(dur_idx, clip_idx):
                durations[fields[clip_idx]] = int(fields[dur_idx])
    return durations


def filter_clips(rows: list[dict], audio_dir: Path, durations: dict = None) -> list[dict]:
    """Дата шүүх: хугацаа, MP3 файл байгаа эсэх."""
    filtered = []
    skipped_duration = 0
    skipped_missing = 0
    skipped_invalid = 0

    for row in rows:
        try:
            path_val = row.get("path", "")
            if not path_val:
                continue
            mp3_path = audio_dir / path_val
            if not mp3_path.exists():
                skipped_missing += 1
                continue

            # Duration from clip_durations.tsv (in milliseconds)
            dur_ms = 0
            if durations:
                dur_ms = durations.get(path_val, 0)
            duration = dur_ms / 1000.0  # convert to seconds

            if duration > 0 and not (MIN_CLIP_DURATION <= duration <= MAX_CLIP_DURATION):
                skipped_duration += 1
                continue

            filtered.append({**row, "_path": str(mp3_path), "_duration": duration})
        except Exception:
            skipped_invalid += 1

    print(f"   📊 Шүүсэн дата: {len(filtered)} / {len(rows)} clip")
    print(f"      - хугацааны шалгуур: {skipped_duration}")
    print(f"      - файл олдсонгүй: {skipped_missing}")
    print(f"      - алдаатай: {skipped_invalid}")

    return filtered


def convert_to_wav(audio_path: Path, output_path: Path):
    """MP3 → WAV (16kHz, mono) хувиргах."""
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-ar", str(TARGET_SAMPLE_RATE),
        "-ac", "1",
        "-hide_banner", "-loglevel", "error",
        str(output_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def prepare_dataset(clips: list[dict], split: str, out_dir: Path, max_count: int):
    """Өгөгдөл бэлдэх: WAV болгон хувиргаж, manifest үүсгэнэ."""
    import random
    random.shuffle(clips)

    clips = clips[:max_count]
    audio_out = out_dir / "audio" / split
    audio_out.mkdir(parents=True, exist_ok=True)

    manifest_path = out_dir / f"{split}.tsv"
    manifest_rows = []
    errors = 0

    for i, clip in enumerate(clips):
        mp3_path = Path(clip["_path"])
        wav_name = f"{split}_{i:06d}.wav"
        wav_path = audio_out / wav_name

        try:
            convert_to_wav(mp3_path, wav_path)
            manifest_rows.append({
                "file_name": f"audio/{split}/{wav_name}",
                "text": clip.get("sentence", "").strip(),
                "duration": clip.get("duration", ""),
                "client_id": clip.get("client_id", ""),
            })
            if (i + 1) % 500 == 0:
                print(f"      {i+1}/{len(clips)} хувиргаж дууслаа")
        except Exception as e:
            errors += 1
            print(f"      ⚠ Алдаа [{i}]: {e}")

    # Manifest TSV бичих
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("file_name\ttext\tduration\tclient_id\n")
        for row in manifest_rows:
            text = row["text"].replace("\t", " ").replace("\n", " ")
            f.write(f"{row['file_name']}\t{text}\t{row['duration']}\t{row['client_id']}\n")

    print(f"   ✅ {split}: {len(manifest_rows)} файл ({errors} алдаа)")
    return manifest_rows


def create_vocab_mapping(manifests: list[Path], output_dir: Path):
    """Mongolian vocabulary бүх текстээс үүсгэнэ."""
    vocab = set()
    for manifest in manifests:
        with open(manifest, "r", encoding="utf-8") as f:
            header = f.readline()
            for line in f:
                fields = line.strip().split("\t")
                if len(fields) >= 2:
                    text = fields[1].lower()
                    vocab.update(text)

    vocab_list = sorted(list(vocab))
    vocab_path = output_dir / "vocab.txt"
    with open(vocab_path, "w", encoding="utf-8") as f:
        for w in vocab_list:
            f.write(w + "\n")

    print(f"   📚 Vocabulary: {len(vocab_list)} unique текст")
    return vocab_path


def main():
    print("=" * 60)
    print("  Common Voice 16.0 Mongolian — Wav2Vec2 бэлдэх")
    print("=" * 60)
    print()

    # 1. TSV унших
    dev_tsv = DATASET_DIR / "dev.tsv"
    validated_path = DATASET_DIR / "validated.tsv"

    clips_dir = DATASET_DIR / "clips"

    if not dev_tsv.exists() or not validated_path.exists():
        print(f"❌ TSV файл олдсонгүй!")
        print(f"  Өгөгдөл татсан эсэхээ шалгана уу:")
        print(f"   - {dev_tsv}")
        print(f"   - {validated_path}")
        print()
        print("   Татахын тулд: bash scripts/download_commonvoice.sh")
        sys.exit(1)

    print("[1/5] clip_durations.tsv уншиж байна...")
    durations = load_durations(DATASET_DIR / "clip_durations.tsv")
    print(f"   📊 {len(durations)} clip durations loaded")

    print("[2/5] Validated TSV уншиж байна (train)...")
    validated_rows = load_tsv(validated_path)
    print(f"   📊 Нийт {len(validated_rows)} validated clip")

    print("[3/5] Dev TSV уншиж байна...")
    dev_rows = load_tsv(dev_tsv)
    print(f"   📊 Нийт {len(dev_rows)} dev clip")

    # 4. Шүүх
    print("[4/5] clips шүүж байна...")
    train_filtered = filter_clips(validated_rows, clips_dir, durations)
    val_filtered = filter_clips(dev_rows, clips_dir, durations)

    # 5. Хувиргах
    print("[5/5] Train өгөгдөл хувиргаж байна...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prepare_dataset(train_filtered, "train", OUTPUT_DIR, TRAIN_SAMPLES)

    print("[5/5] Validation өгөгдөл хувиргаж байна...")
    prepare_dataset(val_filtered, "val", OUTPUT_DIR, VAL_SAMPLES)

    # 6. Vocabulary
    print("[6/6] Vocabulary үүсгэж байна...")
    create_vocab_mapping(
        [OUTPUT_DIR / "train.tsv", OUTPUT_DIR / "val.tsv"],
        OUTPUT_DIR
    )

    print()
    print("=" * 60)
    print("  ✅ Wav2Vec2 Mongolian fine-tune дата бэлэн!")
    print("=" * 60)
    print(f"   📁 Өгөгдөл: {OUTPUT_DIR}")
    print(f"   📊 Train: {TRAIN_SAMPLES} clip")
    print(f"   📊 Val: {VAL_SAMPLES} clip")
    print()
    print("   Дараах тушаалтай fine-tune хийх боломжтой:")
    print(f"   python scripts/train_wav2vec.py --data_dir {OUTPUT_DIR}")
    print()


if __name__ == "__main__":
    main()
