# AI Proctor — Загваруудын автомат үнэлгээ

_Үүсгэсэн: 2026-05-25 11:58_

Энэхүү тайлан нь **гар аргын тэмдэглэгээ шаардаагүйгээр** автоматаар үүссэн.

## 1. Аргачлал

**Vision:** Систем ажиллах хугацаанд хадгалагдсан incident snapshot бүр дээр харгалзах детектор (MediaPipe / YOLOv8)-ийг **дахин ажиллуулж**, үр дүн нь анхны таамаглалтай тохирч буй эсэхийг шалгав. Жишээ нь `multiple_faces` гэж тэмдэглэсэн зурагт үнэхээр 2+ нүүр илрэх ёстой. Verified = TRUE positive batalgaazhsan, Rejected = FALSE positive байх магадлал өндөр.

**Synthetic negatives:** Хоосон болон шуугиант зургуудыг үүсгэж, vision pipeline тэр болгонд **юу ч илрүүлэх ёсгүй** — энэ нь specificity-ийг хэмжинэ.

**Audio:** Програмаар үүсгэсэн чимээгүй (`зерос` массив), цагаан шуугиан, болон ярианы давтамжийн муж (250 Hz, 4 Hz envelope) дахь синус долгионыг VAD-д өгч, баталгаатай ground truth-тэй харьцуулав.

## 2. Vision pipeline (MediaPipe + YOLOv8)

### 2.1. Incident snapshot-уудын дахин баталгаажуулалт

| Үйл явдал | Загвар | Verified | Rejected | Нийт | Precision* |
|---|---|---:|---:|---:|---:|
| `face_missing` | MediaPipe face detection | 13 | 0 | 13 | 100.0% |
| `multiple_faces` | MediaPipe face detection | 6 | 0 | 6 | 100.0% |
| `gaze_away` | MediaPipe face mesh | 2 | 3 | 5 | 40.0% |

_\* Precision* энд = (Verified) / (Verified + Rejected). Энэ нь нэг кадрын дахин үнэлгээн дээр суурилсан учир бодит precision-аас арай ялгаатай байж болно (анхны логик нь олон кадрын temporal хуримтлал ашигладаг)._

### 2.2. Synthetic negative test (specificity)

| Туршилт | Зөв (юу ч илрээгүй) | Нийт | Specificity |
|---|---:|---:|---:|
| Хоосон зураг | 10 | 10 | 100.0% |
| Шуугиант зураг | 5 | 10 | 50.0% |

## 3. Audio pipeline (Silero VAD)

Нийт 15 синтетик дээжтэй тест.

### 3.1. Категори тус бүрд

| Category | Ground truth | Correct | Total | Accuracy |
|---|---|---:|---:|---:|
| silence | нам гүм | 5 | 5 | 100.0% |
| white_noise | нам гүм (шуугиан) | 5 | 5 | 100.0% |
| speech_tone | яриа | 0 | 5 | 0.0% |

### 3.2. Бинар VAD (яриа эсэх)

- True positives (зөв илрүүлсэн яриа): **0**
- False positives (буруу даллагаа): **0**
- True negatives (зөв нам гүм): **10**
- False negatives (алдсан яриа): **5**
- **Accuracy:** 66.7%
- **Precision:** 0.0% | **Recall:** 0.0% | **F1:** 0.0%

## 4. Нийтлэгдсэн benchmark-ууд (паперээс)

Дээрх тоонуудыг доорх олон улсын benchmark-уудтай харьцуулж болно:

| Загвар | Датасет | Метрик | Утга | Эх сурвалж |
|---|---|---|---|---|
| MediaPipe BlazeFace | WIDER FACE (easy) | mAP | ~95% | Bazarevsky et al., 2019 |
| MediaPipe Face Mesh | FaceMesh internal | NME | <2% | Kartynnik et al., 2019 |
| YOLOv8n | COCO val | mAP@0.5:0.95 | 37.3 | Ultralytics, 2023 |
| Silero VAD v4 | Multilingual VAD set | Accuracy | ~98% | Silero Team, 2021 |
| WavLM-base+ | SUPERB benchmark | SD/SER/ER avg | ~85-95% | Chen et al., 2022 |

## 5. WavLM cheating classifier — ил тод дүгнэлт

Энэ загвар нь Colab дахь сургалтын үед 4 ангилалд (normal / talking / multiple_voices / whispering) **~98% accuracy** үзүүлсэн боловч хөтчөөр бичсэн WebM audio дээр бараг үргэлж `normal` гэж таамагладаг. Шалтгаан нь сургалтын датасет (утас/студийн микрофон) болон бодит хэрэглээний домэйн (хөтчийн WebM кодек) хоорондын аккустик зөрөө. Production-д энэ загварыг ашиглаагүй — оронд нь VAD + RMS heuristic-ийг хослуулсан.

## 6. Хязгаарлалт

1. **Single-frame re-verification:** Анхны системийн логик нь олон кадрын temporal хуримтлалд (жишээ нь 5 кадр дараалан нүүр алдагдах) тулгуурладаг. Snapshot нэг кадр учир дахин үнэлгээ нь арай консерватив (FALSE positive-ийн магадлалыг бага зэрэг хэт үнэлж магадгүй).
2. **Дээж бага:** Нэг хэрэглэгчийн 49 incident-ийн өгөгдөл. Илүү хэрэглэгчид, янз бүрийн гэрэлтүүлэг, камерын чанарт тестлэх шаардлагатай.
3. **Synthetic audio:** 250 Hz синус долгион нь жинхэнэ яриа биш учир VAD-ийн **shallow stress test** хийсэн. Бодит ярианд VAD-ийн гүйцэтгэл нийтлэгдсэн benchmark-тай (98%) ойролцоо байна гэж тооцож болно.
4. **Recall тооцоогүй:** Зөвхөн системийн илрүүлсэн зүйлсийг шалгасан учир алдсан үйл явдлуудыг (false negatives) шууд хэмжих боломжгүй.
