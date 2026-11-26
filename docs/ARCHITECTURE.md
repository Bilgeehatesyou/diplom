# AI Proctor — Архитектур

Диаграммууд нь Mermaid форматтай (GitHub дээр шууд зураг болж харагдана; дипломд оруулахдаа
mermaid.live-аас PNG/SVG экспортлоно).

## 1. Системийн бүрэлдэхүүн

```mermaid
flowchart LR
    subgraph Browser_Student["Оюутны browser (Next.js :3000)"]
        EX[Шалгалтын хуудас<br/>асуулт, autosave, таймер]
        CAP[Камер 5 fps 640px<br/>Микрофон 2с WebM]
        MON[Client хяналт<br/>tab / fullscreen / copy /<br/>виртуал камер]
    end
    subgraph Browser_Teacher["Багшийн browser (Next.js :3001)"]
        DASH[Dashboard<br/>шууд видео, оноо, event]
        HIST[Түүх, хариулт, CSV]
    end
    subgraph Backend["FastAPI backend (:8000)"]
        REST[REST API<br/>JWT + RBAC + rate limit]
        WSS[/ws/student/]
        WST[/ws/teacher/]
        subgraph Workers["Оюутан бүрийн async worker"]
            VW[Video worker 1 Hz]
            AW[Audio worker]
            WD[Watchdog]
            LV[Liveness]
        end
        subgraph AI["AI (загварын pool)"]
            MP[MediaPipe<br/>нүүр + харц]
            YO[YOLOv8n<br/>объект, 0.5 Hz]
            VAD[Silero VAD<br/>+ дохионы шинж]
            CLF[WavLM v3<br/>яриа ангилах]
        end
        EV[Event pipeline<br/>dedup → оноо → DB → багш]
    end
    DB[(SQLite<br/>sessions, events,<br/>submissions)]
    FS[(models/incidents<br/>нотлох зураг)]

    EX -- REST --> REST
    CAP -- binary --> WSS
    MON -- JSON --> WSS
    WSS --> VW & AW & WD
    VW --> MP & YO
    AW --> VAD --> CLF
    VW & AW & WD & LV --> EV
    EV --> DB
    EV --> FS
    EV --> WST
    WSS -- кадр Queue(1) --> WST
    WST --> DASH
    REST --> DB
    HIST -- REST --> REST
```

## 2. Шалгалтын урсгал (sequence)

```mermaid
sequenceDiagram
    autonumber
    participant S as Оюутан (browser)
    participant API as REST API
    participant WS as /ws/student
    participant AI as AI worker
    participant DB as DB
    participant T as Багш (/ws/teacher)

    S->>API: POST /login/student
    API-->>S: JWT (6 цаг)
    S->>API: POST /exam/start
    API->>DB: идэвхтэй session олох эсвэл үүсгэх (unique index)
    API-->>S: асуулт, үлдсэн хугацаа, хадгалсан хариулт
    S->>WS: connect + {"type":"auth", token}
    WS-->>S: ready
    WS-->>T: {meta: online}
    loop шалгалтын турш
        S->>WS: JPEG кадр (5 fps), WebM дуу (2с)
        WS->>T: кадр (ажиглаж байвал)
        AI->>AI: 1 Hz шинжилгээ (харц, нүүр, объект, яриа)
        alt зөрчил илэрвэл
            AI->>DB: RiskEvent + оноо (severity × confidence)
            AI-->>S: анхааруулга
            AI-->>T: event + серверийн оноо
        end
        S->>API: PUT /exam/answers (autosave)
    end
    S->>API: POST /exam/submit
    API->>DB: Submission.submitted_at, session.ended_at
    API-->>T: {meta: submitted}
```

## 3. Session-ий төлөв

```mermaid
stateDiagram-v2
    [*] --> Active: /exam/start
    Active --> Active: refresh / дахин нэвтрэх / reconnect<br/>(оноо, таймер хэвээр)
    Active --> Disconnected: WS тасрах
    Disconnected --> Active: 10с дотор эргэж холбогдох
    Disconnected --> Disconnected: 10с+ → stream_lost event
    Active --> Submitted: /exam/submit
    Active --> AutoSubmitted: хугацаа дуусах (серверийн цаг)
    Disconnected --> AutoSubmitted: хугацаа дуусах
    Submitted --> Reset: багш "Цэвэрлэх"
    AutoSubmitted --> Reset: багш "Цэвэрлэх"
    Reset --> [*]: дахин өгөх боломжтой
    Submitted --> [*]
    AutoSubmitted --> [*]
```

## 4. Өгөгдлийн загвар

```mermaid
erDiagram
    STUDENTS ||--o{ EXAM_SESSIONS : "өгнө"
    EXAM_SESSIONS ||--o{ RISK_EVENTS : "бүртгэнэ"
    EXAM_SESSIONS ||--|| SUBMISSIONS : "хариулт"
    EXAM_SESSIONS ||--o{ PILOT_MARKS : "pilot ground truth"
    STUDENTS {
        string id PK
        string name
        string password "bcrypt"
    }
    TEACHERS {
        int id PK
        string name UK
        string password "bcrypt"
    }
    EXAM_SESSIONS {
        int id PK
        string student_id
        string exam_id
        datetime started_at
        datetime ended_at "NULL = идэвхтэй (нэг л байна)"
        float risk_score
        string decision "pending|flagged|cleared|reset"
        bool archived
    }
    RISK_EVENTS {
        int id PK
        int session_id FK
        string event_type
        string severity
        float confidence
        datetime timestamp
        string snapshot
    }
    SUBMISSIONS {
        int id PK
        int session_id FK "unique"
        text answers "JSON"
        datetime submitted_at
        bool auto_submitted
    }
    PILOT_MARKS {
        int id PK
        int session_id FK
        string step_id
        datetime started_at
    }
```

## 5. Аюулгүй байдлын давхаргууд

| Аюул | Хамгаалалт | Байршил |
|---|---|---|
| Нэвтрэлтгүй хандалт | JWT + role (student/teacher) бүх endpoint-д | `backend/auth.py` |
| Нууц үг таах | bcrypt, IP+нэрээр 5 оролдлого, IP-ээр 20 → 5 мин түгжээ; бүртгэлгүй нэрийн хугацааг тэнцүүлэх | `backend/ratelimit.py` |
| Өөр оюутны/багшийн нэрээр WS холбогдох | student_id-г token-оос авна, багш тусдаа socket | `api/websocket.py` |
| Дахин нэвтэрч оноо/таймер reset хийх | Session зөвхөн илгээх/хугацаа дуусахад хаагдана | `exam_service.py` |
| Камер/дуу зогсоох (DevTools) | Серверийн watchdog | `_watchdog` |
| Урьдчилан бичсэн видео, зураг | Санамсаргүй liveness даалгавар | `ai/liveness.py` |
| Виртуал камер | Төхөөрөмжийн нэр шалгах (тойрч болно → liveness) | `exam/page.tsx` |
| Нотлох зургийн IDOR | Incident зураг зөвхөн багшид, path traversal шалгалт | `routes.py` |
