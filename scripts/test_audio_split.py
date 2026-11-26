"""audio_split.group_split-ийн leakage шалгалт.  Ажиллуулах: python -m pytest scripts/test_audio_split.py -q"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_split import group_split  # noqa: E402

N, T, W, M = 0, 1, 2, 3   # normal, talking, whispering, multiple


def dataset():
    names, labels = [], []
    for mic in ("cm", "wc"):
        for cls, lab in (("n", N), ("t", T), ("w", W)):
            for k in range(10):
                names.append(f"{mic}_{cls}{k}.webm")
                labels.append(lab)
    talking = [n for n, l in zip(names, labels) if l == T]
    manifest = {}
    for i in range(30):                       # synthetic mixes of two talking clips
        a, b = talking[i % len(talking)], talking[(i * 7 + 3) % len(talking)]
        if a == b:
            continue
        mix = f"aug_multiple_{i:03d}.webm"
        manifest[mix] = [a, b]
        names.append(mix)
        labels.append(M)
    return names, labels, manifest


def _sources(idx, names, manifest):
    s = set()
    for i in idx:
        s.update(manifest.get(names[i], [names[i]]))
    return s


def test_random_split_has_no_source_leakage():
    names, labels, manifest = dataset()
    tr, va, rep = group_split(names, labels, manifest, mode="random")
    assert not (_sources(tr, names, manifest) & _sources(va, names, manifest))
    assert rep["dropped_mixes"] > 0                       # straddling mixes were removed
    assert rep["source_overlap"] == []


def test_every_class_present_in_val():
    names, labels, manifest = dataset()
    tr, va, _ = group_split(names, labels, manifest, mode="random")
    assert {labels[i] for i in va} >= {N, T, W}


def test_mic_split_trains_on_computer_mic_and_tests_on_webcam():
    names, labels, manifest = dataset()
    tr, va, _ = group_split(names, labels, manifest, mode="mic")
    assert all(not names[i].startswith("wc_") for i in tr)
    assert all(not names[i].startswith("cm_") for i in va)
    for i in tr + va:                                       # mixes follow their sources' mic
        if names[i] in manifest:
            mics = {s[:2] for s in manifest[names[i]]}
            assert mics == ({"cm"} if i in tr else {"wc"})


def test_old_file_level_split_would_leak():
    """Хуучин арга (файл бүрийг санамсаргүй хуваах) leakage үүсгэдгийг харуулна."""
    import random
    names, labels, manifest = dataset()
    idx = list(range(len(names)))
    random.Random(42).shuffle(idx)
    va, tr = idx[: len(idx) // 5], idx[len(idx) // 5:]
    assert _sources(tr, names, manifest) & _sources(va, names, manifest)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
