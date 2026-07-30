# 04 — Судья

Две роли, разные требования. Не одна функция.

| | Экстрактор | Консолидатор |
|---|---|---|
| Когда | в реальном времени, в фоне | раз в сутки |
| Модель | `gemini-3.5-flash-lite` через Vertex AI (см. ниже) | то же |
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

Схему выхода задаём по-разному в зависимости от провайдера: у Gemini это
`response_json_schema`, у Claude — tool use, **обязательно со `strict: true` и
`additionalProperties: false`**. Ниже — вариант для Claude. Без strict-режима tool use не гарантирует, что
`input` соответствует схеме — «модель физически не может вернуть кривой JSON»
верно только в strict. Strict дополнительно требует, чтобы все свойства были
перечислены в `required`, поэтому необязательные поля объявляются nullable, а не
опускаются.

Межполевые правила (`text` обязателен при ADD, `id` — при UPDATE/DELETE) схемой
не выражаются и проверяются в коде: `Op.parse` в `src/memkit/judge.py`.

```python
TOOL = {
    "name": "emit_operations",
    "description": "Emit memory operations for the conversation window.",
    "strict": True,
    "input_schema": {
        "additionalProperties": False,
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
                        "task_status":{"enum": ["unknown", "todo", "doing",
                                                "done", None]},
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

`task_status` заполняется только при явной формулировке: «надо сделать»,
«делаю сейчас», «готово». При отсутствии такого сигнала задача попадает в
`unknown`; UPDATE без нового статуса сохраняет прежнее состояние.

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

### Стоимость и выбор модели

Цена Haiku 4.5 в доке была указана верно — $1/$5 за миллион, Batch действительно
вдвое дешевле. Но расходы этого развёртывания идут против кредитов Google Cloud,
поэтому судья по умолчанию — **Gemini 3.5 Flash-Lite на Vertex AI**.

Замерено на реальном корпусе, за один вызов при окне v2:

| Модель | $/Mtok (in/out) | За вызов | Полный бэкфилл |
|---|---|---|---|
| **gemini-3.5-flash-lite** | **$0.30 / $2.50** | **$0.0009** | **~$0.21** |
| claude-haiku-4-5 | $1 / $5 | $0.0023 | ~$0.55 |
| claude-sonnet-5 | $2 / $10 (интро до 2026-08-31) | $0.0046 | ~$1.10 |
| claude-opus-5 | $5 / $25 | $0.0115 | ~$2.76 |

Claude-модели остаются рабочими (`src/memkit/providers.py`), чтобы сравнивать их
на одном эвале, а не менять на веру.

**Важная особенность Flash-Lite:** выход дороже входа в 8 раз, и reasoning
биллится как выход. Поэтому в промпте жёсткий лимит длины факта, а thinking
выставлен в `MINIMAL` — Google сам рекомендует это для классификации и
JSON-extraction. Batch вдвое дешевле ($0.15/$1.25), кэшированный вход — $0.03.

Формы запроса у провайдеров разные, и это не однострочная замена:

| | Структурированный вывод | Глубина | Креды |
|---|---|---|---|
| Gemini API / Vertex | `response_json_schema` + `response_mime_type` | `thinking_level=MINIMAL` | API key / ADC |
| Anthropic / Sonnet, Opus | tool use + `strict: true` | `output_config.effort` | `ANTHROPIC_API_KEY` |
| Anthropic / Haiku 4.5 | то же | `effort` **не поддерживается** | то же |

Сквозной гарант в обоих случаях — `Op.parse`: ни одна схема не выражает правило
«при ADD поле text обязательно».

Плюс консолидатор: ~30 запусков в месяц, промпты крупнее, но Batch API вдвое
дешевле → ещё $0.5–1.5.

**Реалистичный итог: $1–4 в месяц.** Твой бюджет $5–10 не является
ограничением. Не оптимизируй то, что и так дёшево — оптимизируй качество
извлечения.

Про кэширование промпта: вывод был верный, но причина другая. Дело не только в
том, что кэш протухает между вызовами — стабильная часть промпта (правила плюс
якоря importance) это ~350 токенов, а минимальный кэшируемый префикс у Sonnet 5
равен 1024 токенам (у Haiku 4.5 — 4096, у Opus 5 — 512). Префикс просто короче
минимума, поэтому кэш не создаётся ни при каком TTL. Ничего включать не нужно.

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

### Реализовано: `src/memkit/consolidate.py`

Три отступления от написанного выше, все осознанные.

**Batch API не берём.** Дока права, что он вдвое дешевле, но на 88 фактах весь
прогон — единицы вызовов (замерено: $0.00025 за склейку одного кластера). Batch
покупает эту скидку асинхронным ожиданием; за четверть цента это не стоит
сложности.

**Порог 0.92 работает, вопреки пессимизму `05-retrieval.md`.** Замерено на этом
корпусе: настоящая пара дублей («User's name is Maga Luev» / «User's name is Maga
(or MagaLoviev)») даёт 0.9278, а пара, которую склеивать нельзя («Prefers pnpm» /
«Prefers pytest») — 0.7422. Порог вынесен в `MEMKIT_CONSOLIDATE_COSINE` и в тело
запроса. Он строже порога дедупа на чтении (0.90) намеренно: дедуп прячет дубль из
одного ответа, консолидация перезаписывает хранилище — цена ошибки разная по роду.

**Кластеры — компоненты связности через union-find, с потолком в 6 элементов.**
Транзитивность нужна: если A близко к B, B к C, а A к C нет, все три про одно и то
же, и одиночный проход по парам оставил бы два кластера. Потолок — предохранитель:
кластер из пятнадцати «дублей» почти всегда означает низкий порог, а не пятнадцать
пересказов одного факта, поэтому такой кластер пропускается с записью в лог.

Плюс две вещи, которых в доке не было, но без них фаза не закрывается: истечение
`valid_until` (на пути чтения он не фильтруется, то есть до этой фазы просроченный
по дате факт выдавался как живой) и понижение importance у фактов, не всплывавших
90 дней. Оба шага идут **до** склейки, чтобы мёртвый факт не отправлялся в модель.

Слитый факт наследует `memory_sources` всех своих входов, иначе
`GET /v1/memories/{id}/sources` перестал бы отвечать на «откуда это».

---

## Версионирование промптов

Каждый факт хранит `extraction_version`. При изменении промпта — новая версия,
старые факты не трогаем. Тогда:

- можно сравнить v3 и v4 на одном эвале;
- можно прогнать `reextract` и откатиться, если стало хуже;
- видно, какие факты из какой эпохи.

Без этого через три месяца в базе будет каша из фактов, извлечённых разными
промптами, и разобраться, почему поиск деградировал, будет невозможно.
