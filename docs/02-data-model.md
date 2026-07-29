# 02 — Модель данных

## SQLite — источник правды

```sql
-- Кто владелец памяти. Пока одна строка, но поле есть везде.
CREATE TABLE owners (
    id          TEXT PRIMARY KEY,          -- uuid
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- Сессия = один разговор одного агента.
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES owners(id),
    agent_id    TEXT NOT NULL,             -- 'chat', 'coder', 'research'
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    meta        TEXT                       -- JSON
);

-- Сырые сообщения. НИКОГДА не удаляются.
CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    role            TEXT NOT NULL,             -- 'user' | 'assistant'
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    processed       INTEGER NOT NULL DEFAULT 0, -- прошло через судью?
    -- Перенесено сюда из 07-hermes-adapter.md: импортёр транскриптов нужен
    -- в фазе 1, а он без идемпотентности работать не может.
    external_source TEXT,
    external_id     TEXT
);
CREATE INDEX idx_messages_session ON messages(session_id, id);
CREATE INDEX idx_messages_unprocessed ON messages(processed) WHERE processed = 0;
CREATE UNIQUE INDEX idx_messages_external
    ON messages(external_source, external_id) WHERE external_id IS NOT NULL;

-- Извлечённые факты. Это то, что ищется.
CREATE TABLE memories (
    id                 TEXT PRIMARY KEY,   -- uuid, он же point id в Qdrant
    owner_id           TEXT NOT NULL REFERENCES owners(id),
    agent_id           TEXT,               -- NULL = общий для всех агентов
    scope              TEXT NOT NULL,      -- 'user' | 'project' | 'task'
    scope_key          TEXT,               -- имя проекта, id задачи
    type               TEXT NOT NULL,      -- см. таблицу типов ниже
    text               TEXT NOT NULL,      -- сам факт, самодостаточный
    importance         REAL NOT NULL,      -- 0.0 .. 1.0
    confidence         REAL NOT NULL,      -- 0.0 .. 1.0
    status             TEXT NOT NULL,      -- 'active' | 'superseded' | 'expired'
    superseded_by      TEXT REFERENCES memories(id),
    valid_from         TEXT NOT NULL,
    valid_until        TEXT,               -- NULL = бессрочно
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    last_retrieved_at  TEXT,
    retrieval_count    INTEGER NOT NULL DEFAULT 0,
    extraction_version TEXT NOT NULL,      -- 'v3' — версия промпта
    -- Без этой связи GET /v1/memories/{id}/sources не может вернуть judge_run,
    -- который он обещает в 03-api.md.
    judge_run_id       INTEGER REFERENCES judge_runs(id)
);
CREATE INDEX idx_memories_owner ON memories(owner_id, status);
CREATE INDEX idx_memories_scope ON memories(owner_id, scope, scope_key);

-- Kanban-поля задач. Отдельная таблица намеренно: перемещение карточки не
-- обновляет memories.updated_at и не делает задачу искусственно «свежей».
CREATE TABLE task_board (
    memory_id        TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    workflow_status  TEXT NOT NULL
                     CHECK(workflow_status IN ('unknown','todo','doing','done')),
    project_key      TEXT,
    position         REAL NOT NULL,
    version          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX idx_task_board_order
    ON task_board(workflow_status, project_key, position, memory_id);

-- Откуда взялся факт. Позволяет ответить «почему ты так решил».
CREATE TABLE memory_sources (
    memory_id   TEXT NOT NULL REFERENCES memories(id),
    message_id  INTEGER NOT NULL REFERENCES messages(id),
    PRIMARY KEY (memory_id, message_id)
);

-- Лог вызовов судьи. Для отладки, аудита и подсчёта денег.
CREATE TABLE judge_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,         -- 'extract' | 'consolidate'
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    input_json      TEXT NOT NULL,
    output_json     TEXT,
    error           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL,
    latency_ms      INTEGER,
    created_at      TEXT NOT NULL
);
```

## Типы фактов

| type | scope | Пример | Живёт |
|---|---|---|---|
| `preference` | user | «Предпочитает pnpm вместо npm» | годы |
| `fact` | user | «Живёт в Ташкенте» | годы |
| `skill` | user | «Уверенно пишет на Python, слабо на Rust» | месяцы |
| `relation` | user | «Работает с Азизом над проектом X» | месяцы |
| `project` | project | «Аутентификация лежит в `auth/`» | жизнь проекта |
| `decision` | project | «Решили не брать Redux, слишком много кода» | жизнь проекта |
| `task` | task | «Сегодня: починить баг #14» | часы |

`type` влияет на скорость забывания — см. `05-retrieval.md`.

## Qdrant

Одна коллекция `memories`. **Не по коллекции на агента** — фильтры дешёвые,
коллекции нет.

```python
from qdrant_client import QdrantClient, models

client.create_collection(
    collection_name="memories",
    vectors_config={
        "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE),
    },
    sparse_vectors_config={
        "bm25": models.SparseVectorParams(),      # зарезервировано, фаза 2
    },
)
```

**Важно:** новый именованный вектор нельзя добавить в существующую коллекцию —
только пересоздать и переиндексировать. Поэтому `bm25` объявляем сразу, даже
если заполнять начнём позже. Переиндексация из SQLite возможна, но это лишний
час работы на ровном месте.

Индексы по payload (без них фильтры идут перебором):

```python
for field, schema in [
    ("owner_id", "keyword"),
    ("agent_id", "keyword"),
    ("scope",    "keyword"),
    ("type",     "keyword"),
    ("status",   "keyword"),
    ("task_status", "keyword"),
]:
    client.create_payload_index("memories", field, schema)
```

Payload точки:

```json
{
  "owner_id": "u-1",
  "agent_id": null,
  "scope": "user",
  "scope_key": null,
  "type": "preference",
  "task_status": null,
  "text": "Перешёл с React на Vue (июнь 2026)",
  "importance": 0.8,
  "status": "active",
  "created_at": "2026-06-14T10:00:00Z",
  "updated_at": "2026-07-28T09:12:00Z"
}
```

`text` дублируется в payload специально: иначе после поиска пришлось бы идти
в SQLite за каждым результатом.

Для `type='task'` payload всегда содержит `task_status`. Все четыре состояния,
включая `done`, остаются доступными поиску; lifecycle `expired` от workflow
не зависит.

## Размер

100 000 фактов × 1024 измерения × 4 байта ≈ **410 MB**. Влезает в RAM.
Если перевалит за 500k — включить скалярную квантизацию int8, станет ~4x меньше
с почти нулевой потерей качества:

```python
quantization_config=models.ScalarQuantization(
    scalar=models.ScalarQuantizationConfig(type=models.ScalarType.INT8)
)
```

Реалистичный прогноз для одного человека: 5–20 тысяч фактов за год. Это ничто.

## Инвариант

`memories` в SQLite и точки в Qdrant всегда синхронны по `id`.
`POST /v1/admin/reindex` дропает коллекцию и заливает заново из SQLite.
Эта команда должна работать всегда — проверяй её после каждой фазы.

**Важно:** reindex заливает только `status='active'`. Мягкое удаление оставляет
строку в SQLite, поэтому «залить всё из SQLite» означало бы воскресить каждый
когда-либо удалённый факт.

Коллекций две, не одна. `memories` — по одной точке на активный факт, это и есть
инвариант. `raw` — проиндексированные сырые реплики: нужна фазе 1, чтобы поиск
работал до появления судьи и дал базовое число для эвала. Держать их в одной
коллекции (как предлагает `06-roadmap.md`) нельзя — это ломает соответствие
«одна точка = один факт».
