"""
Шалгалтын тодорхойлолт (асуулт, хугацаа) — серверт байна.
Client зөвхөн уншдаг; хугацааг сервер ExamSession.started_at + duration-аар тооцно.
Олон шалгалтын DB schema нь цаашдын ажил (Exam/Question хүснэгт).
"""
import os

DEFAULT_EXAM_ID = "exam_001"

EXAMS: dict[str, dict] = {
    "exam_001": {
        "title": "Мэдээллийн систем — Улирлын шалгалт",
        "duration_sec": int(os.getenv("EXAM_DURATION_SEC", str(50 * 60))),
        "questions": [
            {
                "id": 1,
                "text": "Мэдээллийн системийн үндсэн бүрэлдэхүүн хэсгүүдийг тодорхойл.",
                "type": "text",
            },
            {
                "id": 2,
                "text": "Өгөгдлийн сангийн нормализацийн зорилго юу вэ?",
                "type": "choice",
                "options": [
                    "Өгөгдлийн давхардлыг арилгах",
                    "Хурдыг нэмэгдүүлэх",
                    "Хадгалах зайг ихэсгэх",
                    "Нууцлалыг сайжруулах",
                ],
            },
            {
                "id": 3,
                "text": "REST болон SOAP архитектурыг харьцуул.",
                "type": "text",
            },
        ],
    },
}


def get_exam(exam_id: str) -> dict | None:
    return EXAMS.get(exam_id)


def exam_duration(exam_id: str) -> int:
    exam = EXAMS.get(exam_id)
    return exam["duration_sec"] if exam else 50 * 60


def public_exam(exam_id: str) -> dict:
    """Client-д илгээх хувилбар (зөв хариулт гэх мэт нууц талбаргүй)."""
    exam = EXAMS[exam_id]
    return {
        "exam_id": exam_id,
        "title": exam["title"],
        "duration_sec": exam["duration_sec"],
        "questions": [
            {k: v for k, v in q.items() if k in ("id", "text", "type", "options")}
            for q in exam["questions"]
        ],
    }
