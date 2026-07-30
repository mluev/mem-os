> **АРХИВ — НЕ НОРМАТИВНЫЙ ДОКУМЕНТ.**
> Это исходная проектная спецификация memkit, написанная до реализации (июль 2026).
> Здесь есть утверждения, которые код опроверг, и решения, которые были отменены.
> **Ничего в этом файле не описывает работающую систему.** Действующие документы —
> в `docs/`, отменённые решения с обоснованием — в `docs/decisions/`.
> Файл сохранён неизменным: он фиксирует, чем обосновывались первоначальные решения.

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
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    role        TEXT NOT NULL,             -- 'user' | 'assistant'
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    processed   INTEGER NOT NULL DEFAULT 0, -- прошло через судью?
    -- связь с внешней системой (Hermes). Даёт provenance и идемпотентность.
    external_source TEXT,                   -- 'hermes'
    external_id     TEXT
);
CREATE INDEX idx_messages_session ON messages(session_id, id);
CREATE INDEX idx_messages_unprocessed ON messages(processed) WHERE processed = 0;
CREATE UNIQUE INDEX idx_messages_external ON messages(external_source, external_id)
    WHERE external_id IS NOT NULL;

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
    -- откуда пришло утверждение. 'user' | 'assistant' | 'tool' | 'manual'
    source_role        TEXT NOT NULL
);
CREATE INDEX idx_memories_owner ON memories(owner_id, status);
CREATE INDEX idx_memories_scope ON memories(owner_id, scope, scope_key);

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

## Запрет на самоотравление

Поле `source_role` — не метаданные, а защита. `sync_turn` присылает и реплику
пользователя, и ответ модели. Если факт можно извлечь из слов ассистента,
возникает замкнутый контур: галлюцинация становится фактом → факт всплывает
в prefetch → модель на него опирается → судья видит подтверждение → уверенность
растёт. Ты не узнаешь, где это началось.

Правило в промпте («не храни то, что сказал ассистент») — просьба, а не
гарантия. Гарантия — на уровне записи:

```sql
-- факт не может иметь единственным источником сообщение ассистента
```

```python
def may_write(op, source_messages):
    roles = {m.role for m in source_messages}
    if roles <= {"assistant"}:
        log_event("memory.rejected", reason="assistant_only_source")
        return False
    return True
```

Реплики ассистента остаются в окне судьи — они нужны, чтобы разрешать «это»,
«оно», «тот вариант». Но фактом стать не могут.

## Журнал событий

Append-only. Пишется всё: создание, изменение, смена типа, удаление, выдача,
вызовы судьи, отказы, скрабы, реэкстракции. Цель — иметь возможность через год
разобраться, почему система вела себя так, и учиться на своих ошибках.

```sql
CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    actor       TEXT NOT NULL,   -- 'judge' | 'consolidator' | 'user'
                                 -- | 'agent:hermes' | 'system'
    action      TEXT NOT NULL,   -- см. список ниже
    entity      TEXT,            -- 'memory' | 'message' | 'session'
    entity_id   TEXT,
    before      TEXT,            -- JSON-снимок до (только для мутаций)
    after       TEXT,            -- JSON-снимок после
    context     TEXT,            -- JSON: prompt_version, model, score, reason
    redacted    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_events_entity ON events(entity, entity_id, id);
CREATE INDEX idx_events_action ON events(action, id);
CREATE INDEX idx_events_ts     ON events(ts);
```

Список `action`:

```
memory.added        memory.updated       memory.type_changed
memory.deleted      memory.superseded    memory.rejected
memory.retrieved    memory.importance_decayed
judge.called        judge.failed         judge.empty
gate.skipped        scrub.redacted
consolidate.merged  reextract.started    reextract.finished
search.performed    event.redacted
```

### Три правила

**1. Полные снимки только на мутациях.** `memory.retrieved` и
`search.performed` — самые частые события. При 100 поисках в день по 20
результатов это 2000 строк в сутки. Для SQLite это ничто, но снимки туда писать
нельзя: только `entity_id`, `score` и `query_hash` в `context`.

**2. Это журнал, а не event sourcing.** Текущее состояние живёт в `memories`.
Соблазн «восстанавливать состояние проигрыванием событий» ведёт к сильно
большей системе, чем тебе нужно. Журнал нужен, чтобы его *читать*, а не чтобы
на него *опираться*.

**3. Есть аварийный люк для стирания.** «Append-only» плюс «в лог может попасть
секрет, который пропустил скраб» = вечная утечка. Поэтому скраб применяется
**до** записи события, а на случай промаха есть операция:

```
POST /v1/admin/events/{id}/redact
```

Она обнуляет `before`/`after`/`context`, ставит `redacted = 1` и пишет
собственное событие `event.redacted`. Факт стирания зафиксирован, содержимое
уничтожено. Без этого люка append-only становится обузой, а не активом.

### Что этот журнал позволит через год

- реконструировать состояние любого факта на любую дату;
- сравнить качество фактов, извлечённых промптом v3 и v7;
- найти факты, которые не выдавались ни разу, и понять, чем они похожи;
- посмотреть, что судья отклонил, и оценить, правильно ли;
- посчитать, сколько денег ушло на какой тип фактов.

Раз в месяц смотреть глазами `SELECT action, COUNT(*) FROM events
WHERE ts > date('now','-30 day') GROUP BY 1`. Смещения в этом распределении
и есть ранние признаки поломки.

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
  "text": "Перешёл с React на Vue (июнь 2026)",
  "importance": 0.8,
  "status": "active",
  "created_at": "2026-06-14T10:00:00Z",
  "updated_at": "2026-07-28T09:12:00Z"
}
```

`text` дублируется в payload специально: иначе после поиска пришлось бы идти
в SQLite за каждым результатом.

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
