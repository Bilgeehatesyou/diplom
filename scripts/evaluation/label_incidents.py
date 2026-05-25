"""Interactive labeling tool for incident snapshots.

For each image saved in models/incidents/<student_id>/, shows the picture and asks
whether the system's detection (event_type from filename) was a TRUE POSITIVE
or a FALSE POSITIVE. Labels are saved to scripts/evaluation/vision_labels.json
so you can resume across sessions.

Run:  python scripts/evaluation/label_incidents.py
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from tkinter import Tk, Label, Button, Frame, StringVar
from PIL import Image, ImageTk

REPO_ROOT     = Path(__file__).resolve().parent.parent.parent
INCIDENTS_DIR = REPO_ROOT / "models" / "incidents"
LABELS_PATH   = Path(__file__).resolve().parent / "vision_labels.json"

# Filename format: 20260523_132308_544_<event_type>.jpg
EVENT_RE = re.compile(r"^\d+_\d+_\d+_(.+)\.jpg$")

def list_incidents() -> list[tuple[str, str, Path]]:
    """Return [(student_id, event_type, path), ...] sorted by filename."""
    items = []
    if not INCIDENTS_DIR.exists():
        return items
    for student_dir in sorted(INCIDENTS_DIR.iterdir()):
        if not student_dir.is_dir():
            continue
        for img in sorted(student_dir.glob("*.jpg")):
            m = EVENT_RE.match(img.name)
            if not m:
                continue
            items.append((student_dir.name, m.group(1), img))
    return items

def load_labels() -> dict:
    if LABELS_PATH.exists():
        return json.loads(LABELS_PATH.read_text())
    return {}

def save_labels(labels: dict) -> None:
    LABELS_PATH.write_text(json.dumps(labels, indent=2, ensure_ascii=False))


class LabelerApp:
    def __init__(self, root: Tk):
        self.root  = root
        self.root.title("Incident labeling")
        self.items = list_incidents()
        self.labels = load_labels()
        self.idx = self._find_first_unlabeled()

        self.progress_var = StringVar()
        self.event_var    = StringVar()

        Label(root, textvariable=self.progress_var, font=("Helvetica", 11)).pack(pady=4)
        Label(root, textvariable=self.event_var, font=("Helvetica", 14, "bold")).pack(pady=2)

        self.img_label = Label(root)
        self.img_label.pack(padx=12, pady=8)

        btns = Frame(root); btns.pack(pady=8)
        Button(btns, text="TRUE positive (y)",  width=18, command=lambda: self.label("tp"),
               bg="#d1fae5").grid(row=0, column=0, padx=4)
        Button(btns, text="FALSE positive (n)", width=18, command=lambda: self.label("fp"),
               bg="#fee2e2").grid(row=0, column=1, padx=4)
        Button(btns, text="Skip (s)",  width=10, command=self.next).grid(row=0, column=2, padx=4)
        Button(btns, text="Back (b)",  width=10, command=self.prev).grid(row=0, column=3, padx=4)
        Button(btns, text="Quit (q)",  width=10, command=root.quit).grid(row=0, column=4, padx=4)

        root.bind("y", lambda e: self.label("tp"))
        root.bind("n", lambda e: self.label("fp"))
        root.bind("s", lambda e: self.next())
        root.bind("b", lambda e: self.prev())
        root.bind("q", lambda e: root.quit())

        self.show()

    def _find_first_unlabeled(self) -> int:
        for i, (_, _, p) in enumerate(self.items):
            if str(p) not in self.labels:
                return i
        return 0

    def show(self):
        if not self.items:
            self.event_var.set("(No incidents found in models/incidents/)")
            return
        if self.idx >= len(self.items):
            self.event_var.set("✅ All done — close window")
            self.img_label.config(image="")
            self.progress_var.set(f"{len(self.items)} / {len(self.items)} labeled")
            return
        sid, event, path = self.items[self.idx]
        existing = self.labels.get(str(path), "")
        marker   = f"  [already: {existing.upper()}]" if existing else ""
        self.progress_var.set(f"{self.idx+1} / {len(self.items)}   ({sum(1 for v in self.labels.values() if v) } labeled){marker}")
        self.event_var.set(f"{event}   —   {sid}")
        img = Image.open(path)
        img.thumbnail((640, 480))
        photo = ImageTk.PhotoImage(img)
        self.img_label.config(image=photo)
        self.img_label.image = photo

    def label(self, value: str):
        if self.idx >= len(self.items):
            return
        _, _, path = self.items[self.idx]
        self.labels[str(path)] = value
        save_labels(self.labels)
        self.next()

    def next(self):
        self.idx = min(self.idx + 1, len(self.items))
        self.show()

    def prev(self):
        self.idx = max(self.idx - 1, 0)
        self.show()


if __name__ == "__main__":
    root = Tk()
    LabelerApp(root)
    root.mainloop()
    print(f"Labels saved to {LABELS_PATH}")
