> **АРХИВ — НЕ НОРМАТИВНЫЙ ДОКУМЕНТ.**
> Это исходная проектная спецификация memkit, написанная до реализации (июль 2026).
> Здесь есть утверждения, которые код опроверг, и решения, которые были отменены.
> **Ничего в этом файле не описывает работающую систему.** Действующие документы —
> в `docs/`, отменённые решения с обоснованием — в `docs/decisions/`.
> Файл сохранён неизменным: он фиксирует, чем обосновывались первоначальные решения.

# 04 — Судья

Две роли, разные требования. Не одна функция.

| | Экстрактор | Консолидатор |
|---|---|---|
| Когда | в реальном времени, в фоне | раз в сутки |
| Модель | `claude-haiku-4-5` | Haiku, можно Sonnet если качество не устроит |
| Режим | обычный вызов | Batch API (в 2 раза дешевле) |
| Вход | окно сообщений + 8 кандидатов | кластер похожих фактов |
| Выход | список операций | склеенный факт |

---

## Экстрактор

### Контракт

```python
extract(
    window:     list[Message],   # последние N сообщений
    candidates: list[Memory],    # top-8 из Qdrant по эмбеддингу окна
) -> list[Op]
```

Схему выхода задаём через tool use — тогда модель физически не может вернуть
кривой JSON.

```python
TOOL = {
    "name": "emit_operations",
    "description": "Emit memory operations for the conversation window.",
    "input_schema": {
        "type": "object",
        "properties": {
            "operations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "op":         {"enum": ["ADD", "UPDATE", "DELETE"]},
                        "id":         {"type": "string"},   # для UPDATE/DELETE
                        "text":       {"type": "string"},
                        "type":       {"enum": ["preference", "fact", "skill",
                                                "relation", "project",
                                                "decision", "task"]},
                        "scope":      {"enum": ["user", "project", "task"]},
                        "importance": {"type": "number"},
                        "confidence": {"type": "number"},
                        "valid_until":{"type": ["string", "null"]},
                        "reason":     {"type": "string"}
                    },
                    "required": ["op", "reason"]
                }
            }
        },
        "required": ["operations"]
    }
}
```

Поле `reason` не используется кодом. Оно нужно тебе, когда будешь разбирать
логи и понимать, почему сервис запомнил ерунду.

### Промпт

```
You extract long-term memories from a conversation.

RULES

1. A memory must be self-contained. Someone reading it in a year, with no
   other context, must understand it. Never write "he", "it", "this project".
2. Resolve relative time to absolute dates. Today is {today}.
   "last month" -> "(June 2026)".
3. Store what is true about the user and their world. Do NOT store what the
   assistant said, suggested, or explained.
4. Skip transient states: mood, tiredness, "currently reading X".
   Keep only what will still matter in three months.
5. If new information contradicts or refines a CANDIDATE, emit UPDATE with
   that candidate's id. Do not emit ADD.
6. Returning an empty operations list is correct and common. Most messages
   contain nothing worth remembering.
7. Write the memory in the same language the user used.
8. Never store credentials, tokens, keys, connection strings, file contents,
   or command output. If a message contains them, extract only the surrounding
   intent, never the value.
9. Extract only from what the USER stated. Assistant turns are context for
   resolving references, never a source of fact. If the user did not confirm
   it, it is not a memory.
10. Never phrase a memory as a negation. Not "no longer uses React" but
    "uses Vue (since June 2026)". Embeddings barely distinguish "prefers X"
    from "does not prefer X"; express change by superseding the old memory,
    not by wording.
11. Always assign the narrowest scope that fits. If the fact is about one
    project, scope is 'project', not 'user'. Current project: {project}.

IMPORTANCE
  0.9-1.0  identity, hard constraints, things that change every answer
  0.6-0.8  stable preferences and skills
  0.3-0.5  useful context, narrow applicability
  0.0-0.2  do not emit at all

CANDIDATES (existing memories, may be empty)
{candidates}

CONVERSATION WINDOW
{window}
```

Почему правила такие:

- **1** — иначе через полгода в базе будет «ему не нравится этот подход» без
  единого шанса понять, о чём речь.
- **3** — самая частая ошибка. Ты спросил про Vue, ассистент расписал Vue —
  и в память падает «пользователь интересуется Vue». Он не интересуется,
  он спросил один раз.
- **5** — без этого через месяц у тебя три противоречащих факта про React.
- **6** — модели склонны что-нибудь да вернуть, чтобы «быть полезными».
  Пустой список надо разрешить явно.
- **IMPORTANCE** — без числовых якорей модель ставит 0.7 всему подряд,
  и поле становится бесполезным.

### Gate: когда звать

Звать при любом из условий:

```python
should_extract = (
    session_closed
    or messages_since_last >= 10
    or re.search(r"\b(запомни|remember|не забудь)\b", text, re.I)
)
```

Главная причина группировать сообщения — **не деньги, а качество**. Из окна
в 10 сообщений извлекается лучший факт, чем из одной реплики: видно контекст,
разрешаются «это», «оно», «тот проект».

### Стоимость

Один вызов: ~1200 входных + ~150 выходных токенов.
При $1 / $5 за миллион:

```
1200 × $1/1M  = $0.0012
 150 × $5/1M  = $0.00075
                ─────────
                $0.002 за вызов
```

| Нагрузка | Вызовов/мес | $/мес |
|---|---|---|
| 50 сообщений/день | ~210 | $0.42 |
| 150 сообщений/день | ~560 | $1.12 |
| 300 сообщений/день | ~1050 | $2.10 |

Плюс консолидатор: ~30 запусков в месяц, промпты крупнее, но Batch API вдвое
дешевле → ещё $0.5–1.5.

**Реалистичный итог: $1–4 в месяц.** Твой бюджет $5–10 не является
ограничением. Не оптимизируй то, что и так дёшево — оптимизируй качество
извлечения.

Про кэширование промпта: скидка на закэшированный ввод большая, но окно жизни
кэша короткое. При личном использовании вызовы разбросаны по дню, кэш чаще
успевает протухнуть, чем сработать. Включать имеет смысл только если пойдёшь
в реэкстракцию тысяч сообщений подряд.

Ограничитель на всякий случай: жёсткий лимит $15/мес в коде, при превышении
экстракция ставится на паузу и пишет в лог. Один баг с циклом может съесть
месячный бюджет за час.

---

## Консолидатор

Ночью, батчем.

```python
consolidate(cluster: list[Memory]) -> Memory | None
```

Как собирать кластеры: для каждого активного факта ищем соседей с
`similarity > 0.92` в пределах одного `owner_id` + `type`. Компоненты
связности и есть кластеры. Кластеры размером 1 пропускаем.

```
Merge these near-duplicate memories into one.

RULES
1. Keep the most recent state of affairs. Older contradicted facts are dropped.
2. Preserve specifics: dates, names, versions, numbers.
3. The result must be shorter than the inputs combined, but must not lose
   information that is still true.
4. If the memories are actually about different things, return null.
   Similar wording is not the same as same meaning.

MEMORIES
{cluster}
```

Правило 4 обязательно. «Предпочитает pnpm» и «Предпочитает pytest» дадут
высокое сходство (обе про инструменты), но склеивать их нельзя.

Применение: новый факт `ADD`, старые `status='superseded'`,
`superseded_by = new_id`. Ничего не теряем.

---

## Версионирование промптов

Каждый факт хранит `extraction_version`. При изменении промпта — новая версия,
старые факты не трогаем. Тогда:

- можно сравнить v3 и v4 на одном эвале;
- можно прогнать `reextract` и откатиться, если стало хуже;
- видно, какие факты из какой эпохи.

Без этого через три месяца в базе будет каша из фактов, извлечённых разными
промптами, и разобраться, почему поиск деградировал, будет невозможно.
