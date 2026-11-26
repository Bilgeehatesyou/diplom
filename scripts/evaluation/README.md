# Загваруудын тоон үнэлгээ (Model Evaluation)

> **Санал болгох арга: Pilot үнэлгээ** — `PILOT_GUIDE.md`-г үзнэ үү. Оролцогчид тогтсон протоколоор
> зөрчлийн үйлдэл хийж, сервер ground truth-ийг автоматаар бүртгэнэ. `pilot_report.py` нь детектор
> бүрийн Recall / Precision / F1 (95% итгэх интервалтай), илрүүлэх хоцролт, хэвийн үеийн цагт ногдох
> худал дохиоллыг гаргана. Дипломд оруулах тоог эндээс авна.
>
> - `create_pilot_users.py` — PILOT01… бүртгэл үүсгэх
> - `pilot_report.py` — тайлан (`results/` руу)
> - `test_pilot_report.py` — тайлангийн тооцооллын тест
>
> Доорх хуучин арга: `label_incidents.py` нь зөвхөн precision хэмждэг (recall хэмжихгүй).
> `auto_test.py` нь детекторын өөрийн гаргасан зураг дээр мөн тэр детекторыг дахин ажиллуулдаг
> **тойрог үнэлгээ** тул дипломын тоо болгон ашиглахгүй.

Энэ фолдер нь AI Proctor системд хэрэглэгдсэн загваруудын (MediaPipe, YOLOv8,
Silero VAD, WavLM cheating classifier) тоон үнэлгээг гаргахад зориулагдсан.

## Алхам 1 — Vision загваруудыг тэмдэглэх

`models/incidents/` дотор системийн илрүүлсэн зургууд хадгалагдсан байгаа.
Тэдгээрийг гар аргаар TRUE positive / FALSE positive гэж шалгана:

```bash
cd backend && source .venv/bin/activate
python scripts/evaluation/label_incidents.py
```

GUI цонх нээгдэнэ:
- **TRUE positive (y)** — системийн дүгнэлт зөв (жишээ нь "multiple_faces"
  тэмдэглэгдсэн зураг үнэхээр 2+ хүнтэй)
- **FALSE positive (n)** — алдаатай дүгнэлт (1 хүнтэй атал "multiple_faces" гэсэн)
- **Skip (s)** — тодорхойгүй бол алгасах
- **Back (b)** — өмнөх зураг руу буцах
- **Quit (q)** — гарах (тэмдэглэгээ автоматаар хадгалагдана)

Тэмдэглэгээ нь `scripts/evaluation/vision_labels.json` руу хадгалагдах ба
дараагийн удаа үргэлжлүүлэх боломжтой.

## Алхам 2 — Audio туршилтын дээж нэмэх (заавал биш)

Хэрэв audio загваруудыг үнэлэх бол `audio_samples/` фолдерт дээж хийнэ.
4 ангилал бүрд 5-15 файл нэмэхийг зөвлөж байна (нийт ~30-50 файл).

Фолдерын бүтэц:
```
scripts/evaluation/audio_samples/
├── normal/        # чимээгүй, эсвэл өөрөө л дотроосоо ярьж байгаа
├── talking/       # хэн нэгэнтэй ярилцаж байгаа
├── multiple/      # хэд хэдэн хүний дуу
└── whispering/    # шивнэх яриа
```

Дэмждэг формат: `.wav`, `.mp3`, `.m4a`, `.webm`, `.ogg`, `.flac`
(автоматаар 16kHz mono руу хувиргана — `ffmpeg` шаардлагатай).

Бичих хэрэгсэл: Mac-д **QuickTime → New Audio Recording** эсвэл **Voice Memos**.
Тус бүр 3-5 секундын урттай байх.

## Алхам 3 — Тайлан үүсгэх

```bash
python scripts/evaluation/evaluate.py
```

Үр дүн нь repo-ийн root-д `EVALUATION_REPORT.md` файл болж үүснэ. Дотор нь:

- **Vision метрик** — үйл явдал тус бүрд TP/FP/Precision
- **Audio confusion matrix** — 4×4 бодит vs таамаг
- **Per-class precision/recall/F1** — анги тус бүрд
- **Зөвхөн VAD-ийн үнэлгээ** — яриа эсэх хоёрчилсон шинжилгээ
- **Нийтлэгдсэн benchmark-ууд** — паперээс эш татсан тоонууд
- **Хязгаарлалт** — диплом ажилд бичих ил тод дүгнэлтүүд

## Workflow дүгнэлт

```
1. python scripts/evaluation/label_incidents.py    # GUI-ээр зураг тэмдэглэх
2. (audio_samples/ руу аудио хуулах)                # заавал биш
3. python scripts/evaluation/evaluate.py            # тайлан үүсгэх
4. EVALUATION_REPORT.md-ийг диплом ажилд хуулах
```

## Анхаар

- Эхний удаа `label_incidents.py` ажиллуулахад `Pillow` дутаж магадгүй.
  `pip install Pillow` (хэрэв `requirements.txt`-д байхгүй бол).
- `evaluate.py` нь `backend/ai/analyzer.py`-ийг in-process-оор импортолдог
  тул backend-ийн виртуал орчноос ажиллуулна (MediaPipe, torch гэх мэт
  суулгасан байх).
- Бичсэн `vision_labels.json`-г git-д commit хийх эсэхээ өөрөө шийднэ.
  (Хувийн өгөгдөл биш — зөвхөн зам + label гэх метаөгөгдөл).
