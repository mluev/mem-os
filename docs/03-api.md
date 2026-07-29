# 03 — HTTP API

База: `http://localhost:8077/v1`
Аутентификация: заголовок `X-API-Key`, статичный ключ из `.env`.
Сервис слушает только `127.0.0.1`.

---

## Запись

### `POST /v1/messages`

Принять сообщение. Возвращает сразу, судья работает в фоне.

```json
// запрос
{
  "session_id": "s-abc",
  "owner_id": "u-1",
  "agent_id": "chat",
  "role": "user",
  "content": "да я месяц назад слез с реакта, вью норм заходит"
}

// ответ 202
{ "message_id": 8814, "extraction_queued": true }
```

`extraction_queued: false` означает, что gate не сработал и сообщение просто
легло в буфер. Это нормальное состояние для большинства сообщений.

### `POST /v1/sessions/{id}/close`

Закрыть сессию и форсировать извлечение из хвоста.

```json
{ "extracted": 3, "cost_usd": 0.0021 }
```

### `POST /v1/memories`

Добавить факт руками, минуя судью. Для импорта и ручных правок.

```json
{
  "owner_id": "u-1",
  "scope": "user",
  "type": "preference",
  "text": "Не любит тёмные темы с низким контрастом",
  "importance": 0.6
}
```

---

## Чтение

### `POST /v1/search`

Главный эндпоинт. Его дёргает каждый агент перед каждым ответом.

```json
// запрос
{
  "owner_id": "u-1",
  "query": "как мне лучше построить фронтенд",
  "agent_id": "coder",          // опц., NULL-факты попадут всё равно
  "scopes": ["user", "project"], // опц., по умолчанию все
  "scope_key": "memkit",         // опц., текущий проект/задача — см. ниже
  "types": null,                 // опц., фильтр по типам
  "budget_tokens": 800,          // сколько токенов отдать под память
  "limit": 30
}

// ответ 200
{
  "memories": [
    {
      "id": "m-7f2a",
      "text": "Перешёл с React на Vue (июнь 2026)",
      "type": "preference",
      "score": 0.87,
      "similarity": 0.79,
      "importance": 0.8,
      "age_days": 44,
      "updated_at": "2026-07-28T09:12:00Z"
    }
  ],
  "used_tokens": 612,
  "took_ms": 41
}
```

`score` — итоговый ранг после пересчёта, `similarity` — сырое косинусное
сходство. Оба в ответе, чтобы можно было отлаживать формулу глазами.

`scope_key` обязателен в запросе, хотя изначально его тут не было: правило из
`05-retrieval.md` требует выбрасывать факты чужого проекта или задачи, а сравнить
их ключ не с чем, если текущий ключ не пришёл в запросе.

### `GET /v1/memories`

Листинг с фильтрами. Для отладочного UI и ревизии.

```
GET /v1/memories?owner_id=u-1&type=preference&status=active&limit=100
```

### `GET /v1/memories/{id}/sources`

Откуда взялся факт — исходные сообщения и запуск судьи.

```json
{
  "memory": { "id": "m-7f2a", "text": "..." },
  "messages": [
    { "id": 8814, "content": "да я месяц назад слез с реакта...",
      "created_at": "2026-07-28T09:11:00Z" }
  ],
  "judge_run": { "id": 412, "prompt_version": "v3", "model": "claude-haiku-4-5" }
}
```

Этот эндпоинт кажется необязательным. Он не необязательный: когда сервис
запомнит про тебя чушь, ты захочешь узнать откуда.

### Task board

`GET /v1/admin/tasks/board?include_archived=false` возвращает все task-memory,
счётчики четырёх колонок и обнаруженные имена проектов.

`POST /v1/admin/tasks` создаёт task-memory и Kanban-метаданные:

```json
{
  "text": "Проверить релиз",
  "workflow_status": "todo",
  "project_key": "memkit",
  "importance": 0.7,
  "valid_until": null
}
```

`PATCH /v1/admin/tasks/{id}` правит содержимое или перемещает карточку.
Перемещение задаётся `workflow_status`, `before_id`, `after_id` и
`expected_board_version`. Для изменения memory-полей дополнительно нужен
`expected_memory_updated_at`; устаревшая версия получает `409`.

---

## Правки

### `PATCH /v1/memories/{id}`

```json
{ "text": "...", "importance": 0.9, "status": "superseded" }
```

### `DELETE /v1/memories/{id}`

Мягкое удаление: `status = 'expired'`. Точка из Qdrant убирается,
строка в SQLite остаётся. Физическое удаление — только `?hard=true`,
и оно не трогает `messages`. Для задач это архивирование/восстановление;
workflow `done` остаётся отдельным состоянием.

---

## Админ

### `POST /v1/admin/reindex`

Пересобрать Qdrant из SQLite. Должно работать всегда.

```json
{ "reindexed": 4821, "took_ms": 39400 }
```

### `POST /v1/admin/reextract`

Прогнать историю заново с новой версией промпта.

```json
// запрос
{
  "owner_id": "u-1",
  "from_date": "2026-01-01",
  "prompt_version": "v4",
  "dry_run": true,
  "use_batch": true
}

// ответ при dry_run
{
  "messages_to_process": 12400,
  "estimated_calls": 1240,
  "estimated_cost_usd": 1.24
}
```

Всегда сначала `dry_run: true`. `use_batch: true` включает Batch API,
это вдвое дешевле, а результата ждать всё равно не надо.

Старые факты при реэкстракции не затираются — создаётся новый набор с новым
`extraction_version`, а старый помечается `superseded`. Так можно сравнить
две версии на одном и том же эвале и откатиться.

### `POST /v1/admin/consolidate`

Ручной запуск ночной консолидации.

### `GET /v1/admin/costs?days=30`

```json
{ "total_usd": 6.42, "by_kind": { "extract": 4.10, "consolidate": 2.32 },
  "calls": 3211 }
```

### `GET /healthz`

```json
{ "ok": true, "qdrant": true, "embedder": true, "queue_depth": 2 }
```

---

## Как агент это использует

```python
mem = requests.post(f"{BASE}/search", json={
    "owner_id": OWNER, "query": user_message, "budget_tokens": 800
}).json()

block = "\n".join(f"- {m['text']}" for m in mem["memories"])
system = f"Что ты знаешь о пользователе:\n{block}"

reply = llm(system=system, messages=history + [user_message])

for role, content in [("user", user_message), ("assistant", reply)]:
    requests.post(f"{BASE}/messages", json={
        "session_id": sid, "owner_id": OWNER, "agent_id": "chat",
        "role": role, "content": content
    })
```

Девять строк на стороне агента. Так и должно быть — вся сложность внутри
сервиса, а не размазана по агентам.
