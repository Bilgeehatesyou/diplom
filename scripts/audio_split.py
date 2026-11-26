"""
Leakage-гүй train/val split (аудио классификаторын сургалтад).

Өмнөх асуудал: "multiple" ангиллын дээжийг talking клипүүдийг хольж (augment_multiple_audio.py)
split-ээс ӨМНӨ үүсгэдэг, дараа нь файл бүрийг санамсаргүй хуваадаг байсан. Ингэснээр нэг talking клип
train-д "talking"-аар, val-д "multiple" mix дотор давхар орж, val-ийн нарийвчлал хэт өндөр гардаг байв.

Шийдэл:
  1. Эх бичлэгүүдийг (mix биш) эхлээд хуваана.
  2. Mix-ийн бүх эх нь train-д бол train, бүгд val-д бол val, холимог бол ХАСНА.
  3. --split mic: компьютерийн микрофоноор (cm_) сургаж, вэбкамерын микрофон (wc_) дээр шалгана —
     өөр төхөөрөмж дээр хэр ажиллахыг харуулах бодит тоо.
  4. Төгсгөлд нь train/val-д давхардсан эх клип байхгүйг шалгана.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

MANIFEST_NAME = "aug_manifest.json"


def load_manifest(train_dir: Path) -> dict[str, list[str]]:
    """{mix файлын нэр: [эх файлын нэр, ...]} — augment_multiple_audio.py үүсгэнэ."""
    out: dict[str, list[str]] = {}
    for p in train_dir.glob(f"*/{MANIFEST_NAME}"):
        out.update(json.loads(p.read_text(encoding="utf-8")))
    return out


def mic_of(name: str) -> str | None:
    return "cm" if name.startswith("cm_") else "wc" if name.startswith("wc_") else None


def group_split(names: list[str], labels: list[int], manifest: dict[str, list[str]],
                mode: str = "random", val_frac: float = 0.2, seed: int = 42) -> tuple[list[int], list[int], dict]:
    """names[i] = файлын нэр (давхардахгүй). Буцаах: (train_idx, val_idx, тайлан)."""
    rng = random.Random(seed)
    originals = [i for i, n in enumerate(names) if n not in manifest]
    assign: dict[str, str] = {}

    pending: dict[int, list[int]] = {}
    for i in originals:
        n = names[i]
        if mode == "mic" and mic_of(n):
            assign[n] = "train" if mic_of(n) == "cm" else "val"
        else:
            pending.setdefault(labels[i], []).append(i)
    for idxs in pending.values():
        idxs = sorted(idxs, key=lambda i: names[i])
        rng.shuffle(idxs)
        n_val = max(1, round(len(idxs) * val_frac)) if len(idxs) > 1 else 0
        for k, i in enumerate(idxs):
            assign[names[i]] = "val" if k < n_val else "train"

    dropped = []
    for i, n in enumerate(names):
        if n not in manifest:
            continue
        sides = {assign.get(src) for src in manifest[n]}
        if sides == {"train"}:
            assign[n] = "train"
        elif sides == {"val"}:
            assign[n] = "val"
        else:
            dropped.append(n)        # эх нь хоёр талд (эсвэл эх нь олдохгүй) → leakage тул хасна

    train_idx = [i for i, n in enumerate(names) if assign.get(n) == "train"]
    val_idx = [i for i, n in enumerate(names) if assign.get(n) == "val"]

    def sources(idx):
        s = set()
        for i in idx:
            s.update(manifest.get(names[i], [names[i]]))
        return s
    overlap = sources(train_idx) & sources(val_idx)
    report = {"mode": mode, "train": len(train_idx), "val": len(val_idx),
              "dropped_mixes": len(dropped), "source_overlap": sorted(overlap)}
    if overlap:
        raise AssertionError(f"Leakage: {len(overlap)} эх клип train болон val хоёуланд орсон: {sorted(overlap)[:5]}")
    return train_idx, val_idx, report
