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

Прогнать историю заново с другой версией промпта.

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
  "messages_to_process": 2399,
  "sessions": 85,
  "estimated_calls": 260,
  "facts_to_supersede": 86,
  "input_tokens_per_call": 3007,
  "output_tokens_per_call": 91,
  "basis": "measured over 247 real calls",
  "estimated_cost_usd": 0.293696
}
```

Всегда сначала `dry_run: true`. Он ничего не вызывает и считает цену по
измеренному расходу токенов, если реальные вызовы уже были.

`messages_to_process` меньше общего числа сообщений: окна без реплик пользователя
отбрасываются так же, как на живом пути — из них факт о человеке не получится.

**`use_batch` отклоняется с 422, а не игнорируется.** Batch API здесь не
реализован: полный прогон этого корпуса стоит около $0.29, а Batch покупает
половинную скидку асинхронным ожиданием. Молча принять флаг значило бы отчитаться
о скидке, которой не было — ровно тот класс дефекта, из-за которого фильтр
`scopes` месяцами не работал.

Старые факты не затираются — создаётся новый набор с новым `extraction_version`, а
старый помечается `superseded`. Ответ содержит `superseded_ids`, поэтому откат —
это один вызов `POST /v1/admin/memories/bulk` с `op="restore"`.

Три инварианта, которые стоит знать:

- кандидаты для судьи исключают заменяемые факты, иначе он выдал бы против них
  UPDATE и переписал старый набор на месте — а сравнивать было бы уже нечего;
- старый набор гасится **после** записи нового, поэтому сбой на середине оставляет
  оба набора живыми;
- при `max_calls` гасятся только факты, все источники которых были перечитаны. Факт,
  собранный из перечитанного и нетронутого окна, остаётся активным: половина его
  доказательной базы не заменена.

### `POST /v1/admin/consolidate`

Ручной запуск ночной консолидации. `dry_run` по умолчанию `true`.

```json
// запрос
{ "dry_run": true, "threshold": 0.92 }

// ответ
{ "expired": 0, "demoted": 0, "clusters": 1, "merged": 0, "declined": 0,
  "superseded": 0, "cost_usd": 0.0, "merges": [ ... ],
  "dry_run": true, "threshold": 0.92, "active_after": 88, "took_ms": 4100 }
```

`threshold` в запросе перекрывает `MEMKIT_CONSOLIDATE_COSINE` — порог склейки это
эмпирический вопрос, и его надо мочь свипать по эвалу без рестарта.

`declined` — кластеры, которые модель отказалась склеивать по правилу 4 («это про
разное»). Это не ошибка, а нужное поведение.

То же из CLI: `memkit consolidate --dry-run`, расписание —
`deploy/ai.memkit.consolidate.plist`.

### `GET /v1/admin/costs?days=30`

```json
{ "total_usd": 6.42, "by_kind": { "extract": 4.10, "consolidate": 2.32 },
  "calls": 3211 }
```

### Поверхность дашборда

Появилась вместе с фазой 6 и в этой доке не была описана. Всё под тем же
`X-API-Key`, всё только для чтения, кроме явно помеченного.

| Эндпоинт | Зачем |
|---|---|
| `GET /v1/admin/stats` | сводка: факты по статусу/типу/scope, backlog, расходы, здоровье индекса |
| `GET /v1/admin/facets` | значения и счётчики для фильтров UI |
| `GET /v1/admin/activity?days=` | дневной ряд с нулями для графиков и хитмапа |
| `GET /v1/admin/costs/daily?days=` | расходы по дням и по `kind` |
| `GET /v1/admin/judge-runs` | лог вызовов судьи с фильтрами и разобранными операциями |
| `GET /v1/admin/judge-runs/{id}` | один вызов целиком: вход, выход, затронутые факты и сообщения |
| `GET /v1/admin/sessions` | сессии со счётчиками сообщений, необработанных и фактов |
| `GET /v1/admin/sessions/{id}/messages` | сообщения сессии с пометкой, какие факты из них вышли |
| `GET /v1/admin/messages/{id}` | одно сообщение и его факты |
| `POST /v1/admin/search-preview` | тот же путь чтения плюс диагностика: что отброшено по scope, дедупу и бюджету |
| `POST /v1/admin/memories/bulk` | **мутация**: expire / restore / hard_delete / set_type / set_importance / set_scope |
| `POST /v1/memories/{id}/supersede` | **мутация**: пометить факт замещённым другим |
| `POST /v1/admin/reindex/start` + `GET .../reindex/status` | асинхронная пересборка с прогрессом |

Синхронный `POST /v1/admin/reindex` из раздела выше и асинхронный
`reindex/start` делят один слот: пока идёт любой из них, мутации отвечают `409`.

### `GET /healthz`

```json
{ "ok": true, "qdrant": true, "embedder": true, "queue_depth": 2 }
```

`queue_depth` — число сообщений с `processed = 0`. Очереди как таковой нет:
экстракция идёт фоновой задачей FastAPI, а не через `asyncio.Queue` из
`01-architecture.md`. Осмысленный аналог — сколько истории ещё ждёт судью.

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
