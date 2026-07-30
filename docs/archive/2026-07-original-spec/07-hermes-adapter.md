> **АРХИВ — НЕ НОРМАТИВНЫЙ ДОКУМЕНТ.**
> Это исходная проектная спецификация memkit, написанная до реализации (июль 2026).
> Здесь есть утверждения, которые код опроверг, и решения, которые были отменены.
> **Ничего в этом файле не описывает работающую систему.** Действующие документы —
> в `docs/`, отменённые решения с обоснованием — в `docs/decisions/`.
> Файл сохранён неизменным: он фиксирует, чем обосновывались первоначальные решения.

# 07 — Адаптер для Hermes

Hermes Agent (NousResearch) подключает внешнюю память через плагин, реализующий
ABC `MemoryProvider`. Наш сервис — один такой провайдер; всё внутреннее
устройство (Qdrant, BGE-M3, судья) снаружи не видно.

## Размещение

```
plugins/memory/memkit/
    __init__.py
    provider.py      # класс MemkitProvider
    client.py        # HTTP-клиент к сервису
    scrub.py         # вычистка секретов
    cli.py           # опц., register_cli(subparser)
```

Конфиг Hermes:

```yaml
memory:
  provider: memkit
  memkit:
    base_url: http://127.0.0.1:8077/v1
    api_key_env: MEMKIT_API_KEY
    owner_id: u-1
    budget_tokens: 800
    send_tool_results: false     # см. раздел про секреты
```

`$HERMES_HOME` брать через `hermes_constants.get_hermes_home()`, не хардкодить
`~/.hermes`.

## Маппинг методов

| Метод Hermes | Наш эндпоинт | Примечание |
|---|---|---|
| `initialize(session_id, **kw)` | `POST /v1/sessions` | создать сессию, прогреть кэш |
| `system_prompt_block()` | — | статичная строка, что провайдер умеет |
| `prefetch(query)` | `POST /v1/search` | синхронно с таймаутом, см. ниже |
| `sync_turn(user, assistant, ...)` | `POST /v1/messages` ×2 | в фоновом потоке |
| `get_tool_schemas()` | — | схемы `memkit_search`, `memkit_remember` |
| `handle_tool_call(name, args)` | `/v1/search`, `/v1/memories` | |
| `shutdown()` | — | дождаться фоновых потоков |
| `on_session_end()` | `POST /v1/sessions/{id}/close` | форсирует извлечение из хвоста |
| `on_session_switch(new_id)` | `close` + `sessions` | сбросить кэш prefetch |
| `on_memory_write(...)` | `POST /v1/memories` | зеркало встроенной памяти |
| `on_turn_start`, `on_pre_compress`, `on_delegation` | no-op | пока не нужны |

## prefetch: синхронно, но с таймаутом

Штатный контракт Hermes — возвращаться мгновенно из фонового кэша, из-за чего
у облачных провайдеров память отстаёт на один ход. У нас всё локальное
(BGE-M3 на MPS ~30 мс + Qdrant ~10 мс), поэтому успеваем ответить по существу.

```python
def prefetch(self, query: str) -> str:
    key = _key(query)
    try:
        mems = self._client.search(query, budget_tokens=self.budget, timeout=0.15)
        self._cache[key] = mems
    except (Timeout, ConnectionError, CircuitOpen):
        mems = self._cache.get(key) or self._cache.get(_LAST) or []
    if not mems:
        return ""
    self._cache[_LAST] = mems
    return "\n".join(f"- {m['text']}" for m in mems)
```

Два правила:

- **Никогда не поднимать исключение наружу.** Провайдер, падающий в prefetch,
  ломает ход агента. Любая ошибка → пустая строка.
- **Не оборачивать результат в `<memory-context>`.** Hermes сам оборачивает;
  если провайдер вернёт готовую обёртку, Hermes её срежет и напишет warning.

Замерь реальный p95 после фазы 3. Если таймаут срабатывает чаще 5% — вынеси
в фон и живи с отставанием на ход.

## sync_turn: секреты и идемпотентность

```python
def sync_turn(self, user_content, assistant_content, *,
              session_id="", messages=None):
    payloads = [
        self._mk("user", user_content, session_id),
        self._mk("assistant", assistant_content, session_id),
    ]
    if self.send_tool_results and messages:
        payloads += [self._mk(m["role"], m["content"], session_id)
                     for m in messages if m["role"] == "tool"]

    t = threading.Thread(target=self._post_all, args=(payloads,), daemon=True)
    t.start()
    self._threads.append(t)
```

### Почему `send_tool_results` по умолчанию `false`

`messages` содержит вызовы инструментов и их результаты: пути к файлам, вывод
команд, содержимое рабочего окружения. Кодовый агент регулярно видит `.env`,
вывод `git remote -v`, токены в логах.

Наш судья — облачный API. Значит эти данные уйдут наружу **и осядут в базе как
постоянные факты**. Структурный запрет надёжнее любой регулярки, поэтому по
умолчанию tool-сообщения не отправляются вообще.

Если включишь — обязателен скраб:

```python
# scrub.py
PATTERNS = [
    (r"(?i)\b(sk|pk)-[A-Za-z0-9_\-]{20,}",            "[KEY]"),
    (r"\bAKIA[0-9A-Z]{16}\b",                          "[AWS_KEY]"),
    (r"\bghp_[A-Za-z0-9]{36}\b",                       "[GH_TOKEN]"),
    (r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}", "[JWT]"),
    (r"(?i)(bearer|authorization:)\s+\S+",             r"\1 [REDACTED]"),
    (r"(?i)^\s*\w*(secret|token|password|passwd|api_?key|credential)\w*\s*=.*$",
                                                        "[ENV_LINE]"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
                                                        "[PRIVATE_KEY]"),
    (r"://[^:/\s]+:[^@/\s]+@",                         "://[CRED]@"),
]

def scrub(text: str) -> str:
    for pat, repl in PATTERNS:
        text = re.sub(pat, repl, text, flags=re.MULTILINE)
    return text
```

Плюс строка в промпт экстрактора (`04-judge.md`):

```
8. Never store credentials, tokens, keys, connection strings, file contents,
   or command output. If a message contains them, extract only the surrounding
   intent, never the value.
```

Регулярки — второй рубеж, не первый. Они всегда что-нибудь пропустят.

### Идемпотентность

У Hermes **три** канала записи в нас: `sync_turn`, зеркало встроенной памяти
через `on_memory_write`, и tools через `handle_tool_call`. Один и тот же
контент придёт дважды.

Каждое сообщение уходит со стабильным внешним id:

```python
def _mk(self, role, content, session_id):
    body = scrub(content)
    ext_id = hashlib.sha256(
        f"{session_id}|{role}|{body}".encode()
    ).hexdigest()[:32]
    return {
        "session_id": session_id, "owner_id": self.owner_id,
        "agent_id": "hermes", "role": role, "content": body,
        "external_source": "hermes", "external_id": ext_id,
    }
```

На стороне сервиса — `UNIQUE (external_source, external_id)` и
`INSERT ... ON CONFLICT DO NOTHING`. Повтор просто не создаёт запись.

Хэш от содержимого, а не uuid: если Hermes переотправит тот же ход после
сбоя сети, id совпадёт.

## Circuit breaker

Скопировано из mem0-провайдера для Hermes: пять неудач подряд → пауза две
минуты, агент продолжает работать без памяти.

```python
class Breaker:
    def __init__(self, fails=5, cooldown=120):
        self.fails, self.cooldown = fails, cooldown
        self._n, self._until = 0, 0.0

    def allow(self) -> bool:
        return time.time() >= self._until

    def ok(self):
        self._n = 0

    def fail(self):
        self._n += 1
        if self._n >= self.fails:
            self._until = time.time() + self.cooldown
            self._n = 0
            logger.warning("memkit: breaker open for %ss", self.cooldown)
```

404 на несуществующий id — ожидаемая ошибка, брейкер не трогает. Считаем
только сетевые ошибки и 5xx.

## Tools провайдера

```python
def get_tool_schemas(self):
    return [
        {"name": "memkit_search",
         "description": "Search long-term memory about the user and projects.",
         "input_schema": {"type": "object", "properties": {
             "query": {"type": "string"},
             "scope": {"enum": ["user", "project", "task"]}},
             "required": ["query"]}},
        {"name": "memkit_remember",
         "description": "Store a fact the user explicitly asked to remember.",
         "input_schema": {"type": "object", "properties": {
             "text": {"type": "string"},
             "type": {"enum": ["preference", "fact", "skill", "relation",
                               "project", "decision", "task"]}},
             "required": ["text"]}},
    ]
```

`memkit_remember` идёт в `POST /v1/memories` **мимо судьи**, с
`importance=0.9`. Если пользователь сказал «запомни» явно — обсуждать нечего.

Отдельного read-tool могло бы не быть, раз prefetch и так подставляет контекст.
Но он нужен: prefetch ищет по последней реплике, а модель иногда хочет задать
поиску более точный запрос.

## Дублирование истории — это нормально

Hermes ведёт свою `messages` в SessionDB с FTS5-поиском по сессиям. Мы ведём
свою. Это не ошибка: у Hermes это история разговора для поиска по ней, у нас —
сырьё для реэкстракции и provenance.

Условие только одно: связь должна быть явной. `external_id` даёт возможность
проследить факт до конкретного сообщения в базе Hermes и заметить расхождение.
Без него две базы разъедутся молча.

## Дельта к остальным докам

`02-data-model.md`, таблица `messages`:

```sql
ALTER TABLE messages ADD COLUMN external_source TEXT;
ALTER TABLE messages ADD COLUMN external_id     TEXT;
CREATE UNIQUE INDEX idx_messages_external
    ON messages(external_source, external_id)
    WHERE external_id IS NOT NULL;
```

`03-api.md`: `POST /v1/messages` принимает `external_source` и `external_id`,
на конфликте возвращает `200` с существующим `message_id` и
`"deduplicated": true` вместо `201`.

`04-judge.md`: правило 8 в промпт экстрактора.

`06-roadmap.md`: адаптер — это фаза 5. Прежде чем его писать, сервис должен
проходить эвал сам по себе, через curl.

## Чек-лист приёмки

- [ ] Сервис остановлен → Hermes работает, память пустая, ошибок в ходе нет
- [ ] Сервис отвечает 3 секунды → prefetch отдаёт кэш, ход не блокируется
- [ ] Один ход отправлен дважды → в базе одна пара сообщений
- [ ] Строка `AWS_SECRET_ACCESS_KEY=...` в выводе команды → в базу не попала
- [ ] Факт, сказанный в чате → всплыл в кодовом агенте
- [ ] `on_session_end` → извлечение из хвоста сессии произошло
- [ ] Прерванный ход → в память ничего не записалось
