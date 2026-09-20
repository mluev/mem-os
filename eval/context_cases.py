"""New authored scenario families, frozen before context-assembly experiments.

Facet labels describe information, not wording. Repeated paraphrases cover one
facet. Source text is fictional, original, and copied verbatim by all variants.
The split is by scenario, never by paraphrase or query.
"""

from __future__ import annotations

from typing import Any

# id, split, language, broad query, detail query, unknown query,
# three equivalent summaries, three source details, topic-matching distractor.
FAMILIES = [
    (
        "ledger",
        "dev",
        "ru",
        "Как устроено хранение в Ledger, почему так и какие есть исключения?",
        "Что в Ledger разрешено хранить в Redis?",
        "Какой у Ledger пароль администратора?",
        [
            "Ledger хранит основные данные в PostgreSQL.",
            "Основное хранилище Ledger — PostgreSQL.",
            "В Ledger для основных данных выбрана база PostgreSQL.",
        ],
        [
            "Для Ledger мы выбрали PostgreSQL, потому что перевод денег должен быть атомарным.",
            "Redis в Ledger оставляем только для временного кеша; баланс туда не записываем.",
            "В Ledger кеш можно потерять: мы восстановим его из PostgreSQL.",
        ],
        "В проекте Ledger-demo баланс храним в Redis. Это демонстрация, отдельная от Ledger.",
    ),
    (
        "seminar",
        "dev",
        "ru",
        "Какие правила у семинара Лира, включая исключения и причины?",
        "Когда участникам семинара Лира можно пропустить выступление?",
        "Сколько стоит участие в семинаре Лира?",
        [
            "На семинаре Лира каждый участник выступает.",
            "Все участники Лиры должны подготовить выступление.",
            "Семинар Лира предполагает выступление каждого участника.",
        ],
        [
            "На семинаре Лира каждый выступает, чтобы потренироваться защищать свою позицию.",
            "На Лире участники с потерей голоса могут вместо выступления прислать письменный разбор.",
            "На Лире вопросы собираем после выступления, чтобы не сбивать начинающего докладчика.",
        ],
        "Семинар Вега допускает свободное посещение без выступлений; у Лиры другая программа.",
    ),
    (
        "trail",
        "dev",
        "en",
        "What are the plans, reasons and exceptions for the Cedar hiking trip?",
        "What is the rain fallback for the Cedar trip?",
        "Who paid for the Cedar trip tickets?",
        [
            "The Cedar trip follows the ridge trail.",
            "We chose the ridge route for the Cedar hike.",
            "Cedar hikers normally take the ridge trail.",
        ],
        [
            "For Cedar we take the ridge trail because the valley bridge is closed.",
            "For Cedar, if heavy rain is forecast we visit the local museum instead of hiking.",
            "On Cedar everyone carries water; the spring marked on old maps has dried up.",
        ],
        "The Birch trip crosses the valley bridge and hikes in the rain; Cedar is a separate group.",
    ),
    (
        "reader",
        "dev",
        "en",
        "How should the Iris reader behave, including accessibility exceptions?",
        "When should animation be disabled in Iris?",
        "What font license did Iris purchase?",
        [
            "Iris uses animated page transitions.",
            "Page changes in Iris have an animation.",
            "The Iris reader animates transitions between pages.",
        ],
        [
            "Iris animates page changes to preserve the reader's spatial orientation.",
            "In Iris, disable transitions when the operating system requests reduced motion.",
            "Iris keeps keyboard focus on the next page heading after a page change.",
        ],
        "Iris-marketing plays animated banners regardless of reduced-motion settings; it is a separate site.",
    ),
    (
        "lunch",
        "dev",
        "ru",
        "Что нужно учесть при заказе обеда для группы Север?",
        "Какую еду нельзя добавлять в обед группы Север даже отдельно?",
        "Какой номер карты используется для обедов группы Север?",
        [
            "Группа Север заказывает вегетарианский обед.",
            "Для Севера выбираем обед без мяса.",
            "Обеды участников группы Север вегетарианские.",
        ],
        [
            "Север заказывает вегетарианский обед, чтобы не собирать разные мясные заказы.",
            "В обедах Севера не должно быть орехов даже в отдельной упаковке: у участника аллергия.",
            "Для Севера молочные продукты подаём отдельно, а не смешиваем с основным блюдом.",
        ],
        "Группа Юг заказывает мясо и ореховый десерт. Их меню не распространяется на Север.",
    ),
    (
        "alerts",
        "dev",
        "en",
        "Describe the Harbor notification rules and exceptions.",
        "Which Harbor alerts bypass quiet hours?",
        "What is the Harbor on-call phone number?",
        [
            "Harbor suppresses notifications during quiet hours.",
            "Quiet hours in Harbor mute notifications.",
            "Harbor notifications are normally silent in quiet hours.",
        ],
        [
            "Harbor mutes routine notifications at night so volunteers can sleep.",
            "Harbor smoke alarms bypass quiet hours; routine device-battery alerts do not.",
            "Harbor sends routine alerts held overnight as one morning digest.",
        ],
        "Harbor-sandbox mutes every alarm, including smoke alarms, because it has no real devices.",
    ),
    (
        "notes",
        "dev",
        "uz",
        "Navo dars konspektlari uchun qoidalar, sabablar va istisnolar qanday?",
        "Navo konspektlarida qachon inglizcha terminni qoldirish mumkin?",
        "Navo kursining narxi qancha?",
        [
            "Navo konspektlari o'zbek tilida yoziladi.",
            "Navo dars yozuvlari uchun o'zbek tili tanlangan.",
            "Navo konspektlarining asosiy tili o'zbekcha.",
        ],
        [
            "Navo konspektlarini o'zbekcha yozamiz, chunki guruh shu tilda o'qiydi.",
            "Navo konspektida aniq tarjimasi bo'lmagan texnik termin inglizcha qoladi, yonida izoh beriladi.",
            "Navo konspektlarida kod misollaridagi nomlar tarjima qilinmaydi.",
        ],
        "Sado kursi konspektlari inglizcha; bu Navo kursining til qoidasi emas.",
    ),
    (
        "vault",
        "dev",
        "mixed",
        "Какие backup rules у Vault, включая причины и исключения?",
        "Какие файлы Vault исключает из backup?",
        "Какой SSH key используется для Vault?",
        [
            "Vault делает резервную копию каждую ночь.",
            "В Vault настроен nightly backup.",
            "Резервное копирование Vault выполняется ночью.",
        ],
        [
            "Vault делает nightly backup, чтобы копирование не мешало дневным операциям.",
            "В Vault каталог scratch исключён из backup: там только воспроизводимые temporary files.",
            "Vault сохраняет оригинальные загрузки, даже если их thumbnails можно пересоздать.",
        ],
        "Vault-playground исключает и uploads, и scratch: это disposable instance, не основной Vault.",
    ),
    (
        "invoice",
        "confirmation",
        "en",
        "Explain the Maple invoicing process, its reasons and exceptions.",
        "Which Maple customers do not receive automatic invoice reminders?",
        "What is Maple's bank account number?",
        [
            "Maple sends automatic invoice reminders.",
            "Invoice reminders are automated in Maple.",
            "Maple normally reminds customers of unpaid invoices automatically.",
        ],
        [
            "Maple sends automatic reminders so staff do not chase every unpaid invoice manually.",
            "For Maple customers with an open billing dispute, automatic reminders are paused.",
            "Maple reminders contain a link to the invoice, never a copy of stored payment details.",
        ],
        "Maple-demo sends reminders even for disputed invoices because it uses fictional customers.",
    ),
    (
        "lab",
        "confirmation",
        "ru",
        "Как лаборатория Кварц хранит образцы и какие есть исключения?",
        "Какие образцы Кварца нельзя замораживать?",
        "Кто производитель морозильника в Кварце?",
        [
            "В лаборатории Кварц образцы замораживают.",
            "Кварц обычно хранит образцы в замороженном состоянии.",
            "Для хранения образцов Кварц использует заморозку.",
        ],
        [
            "Кварц замораживает обычные образцы, чтобы замедлить их разложение.",
            "Живые культуры Кварца не замораживаем: они остаются в инкубаторе.",
            "Каждый образец Кварца маркируем до помещения в хранилище, а не после.",
        ],
        "В учебной лаборатории Кварц-макет живых культур нет, поэтому замораживают всё.",
    ),
    (
        "classroom",
        "confirmation",
        "en",
        "What are the rules and exceptions for homework in the Otter class?",
        "How do Otter students without home internet submit homework?",
        "What is the Otter teacher's home address?",
        [
            "The Otter class submits homework online.",
            "Otter homework is normally handed in through the online portal.",
            "Students in Otter use the portal for homework submission.",
        ],
        [
            "Otter uses online submission so students can see the teacher's written feedback.",
            "Otter students without home internet may hand in a paper copy at the next class.",
            "Otter group assignments list each contributor, even when only one student uploads the file.",
        ],
        "The Fox class requires online submission without a paper option; its rules differ from Otter.",
    ),
    (
        "photos",
        "confirmation",
        "ru",
        "Как устроена обработка фотографий в Альбоме и что нельзя потерять?",
        "Что Альбом делает с исходниками после уменьшения фотографий?",
        "Сколько стоит подписка Альбома?",
        [
            "Альбом уменьшает фотографии для просмотра.",
            "Для отображения Альбом создаёт уменьшенные фотографии.",
            "В Альбоме фотографии показываются в уменьшенном размере.",
        ],
        [
            "Альбом создаёт уменьшенные копии, чтобы страницы открывались быстрее.",
            "После уменьшения в Альбоме оригинал сохраняем без изменений; уменьшенная копия его не заменяет.",
            "Альбом удаляет GPS только из публичной копии, а приватный оригинал сохраняет метаданные.",
        ],
        "Альбом-демо удаляет оригиналы после уменьшения: там только тестовые картинки.",
    ),
    (
        "meeting",
        "confirmation",
        "mixed",
        "Какие meeting rules у команды Orbit и зачем они нужны?",
        "Когда Orbit допускает созвон вместо async update?",
        "Какой пароль у видеоконференции Orbit?",
        [
            "Orbit обсуждает статус работы асинхронно.",
            "В Orbit приняты async status updates.",
            "Команда Orbit обычно сообщает прогресс без созвонов.",
        ],
        [
            "Orbit делает status updates асинхронно, потому что участники в разных часовых поясах.",
            "При production incident Orbit сразу собирает созвон; обычный статус ждёт async update.",
            "Решение после созвона Orbit записываем текстом, чтобы отсутствовавшие могли его прочитать.",
        ],
        "Orbit-sales проводит ежедневные созвоны; это отдельная команда с другой практикой.",
    ),
    (
        "garden",
        "confirmation",
        "uz",
        "Bog' loyihasida sug'orish qoidalari va istisnolari qanday?",
        "Bog'dagi kaktuslarni qachon sug'orish kerak?",
        "Bog' uchun suvning oylik narxi qancha?",
        [
            "Bog' loyihasidagi o'simliklar har kuni sug'oriladi.",
            "Bog'da odatda kundalik sug'orish qo'llanadi.",
            "Bog' o'simliklari uchun har kungi sug'orish rejalashtirilgan.",
        ],
        [
            "Bog'da ko'p o'simliklarni har kuni sug'oramiz, chunki issiqxonada havo quruq.",
            "Bog'dagi kaktuslar har kuni sug'orilmaydi; tuprog'i to'liq qurigandan keyingina suv beriladi.",
            "Bog'da yomg'ir suvini ishlatamiz, lekin idish tagida turgan iflos suvni qayta quymaymiz.",
        ],
        "Dala loyihasida kaktuslar yo'q va hamma o'simlik har kuni sug'oriladi; bu Bog' qoidasi emas.",
    ),
    (
        "migration",
        "confirmation",
        "en",
        "What is the Finch migration plan, including compatibility and rollback details?",
        "Does Finch remove the old API immediately after the migration?",
        "Who approved the Finch migration budget?",
        [
            "Finch is moving to the new API.",
            "The Finch migration adopts the new API.",
            "Finch clients are being migrated to the replacement API.",
        ],
        [
            "Finch moves to the new API to support cursor-based pagination.",
            "Finch keeps the old API available for existing mobile clients until they upgrade.",
            "If Finch's new API fails, route traffic back to the old API without rewriting stored data.",
        ],
        "Finch-lab removes its old API immediately; it has no mobile clients and is a separate deployment.",
    ),
    (
        "print",
        "confirmation",
        "ru",
        "Какие правила оформления у журнала Маяк, с причинами и исключениями?",
        "Можно ли в журнале Маяк уменьшать подписи к иллюстрациям?",
        "Какой тираж следующего выпуска Маяка?",
        [
            "Журнал Маяк использует крупный шрифт.",
            "Текст Маяка набирается крупным шрифтом.",
            "Для журнала Маяк выбран увеличенный размер текста.",
        ],
        [
            "В Маяке используем крупный шрифт, потому что журнал читают люди со слабым зрением.",
            "Подписи к иллюстрациям Маяка не уменьшаем относительно основного текста.",
            "В Маяке длинную таблицу переносим на следующую страницу вместо уменьшения шрифта.",
        ],
        "В рекламной листовке Маяк-промо подписи мелкие; она не является выпуском журнала Маяк.",
    ),
]


def corpus() -> dict[str, Any]:
    items, queries, coverage = [], [], []
    for name, split, lang, broad, detail, unknown, summaries, sources, distractor in FAMILIES:
        for i, text in enumerate(summaries):
            items.append(
                dict(
                    id=f"{name}-m{i}",
                    family=name,
                    split=split,
                    language=lang,
                    kind="memory",
                    text=text,
                    facets=[f"{name}:base"],
                )
            )
        for i, text in enumerate(sources):
            facets = [f"{name}:{['reason', 'exception', 'detail'][i]}"]
            if i == 0:
                facets.append(f"{name}:base")
            items.append(
                dict(
                    id=f"{name}-e{i}",
                    family=name,
                    split=split,
                    language=lang,
                    kind="evidence",
                    text=text,
                    facets=facets,
                )
            )
        items.append(
            dict(
                id=f"{name}-d",
                family=name,
                split=split,
                language=lang,
                kind="distractor",
                text=distractor,
                facets=[],
            )
        )
        useful = [i["id"] for i in items if i["family"] == name and i["facets"]]
        for suffix, query, expected in [
            ("broad", broad, [f"{name}:{f}" for f in ("base", "reason", "exception", "detail")]),
            ("detail", detail, [f"{name}:exception"]),
            ("unknown", unknown, []),
        ]:
            queries.append(
                dict(
                    id=f"{name}-{suffix}",
                    family=name,
                    split=split,
                    language=lang,
                    query=query,
                    expected=expected,
                    relevant_ids=useful if expected else [],
                )
            )
        # A missing-detail judgment; a corresponding covered case provides a
        # negative control. Reference summaries are deliberately lossy.
        for i, text in enumerate(sources):
            coverage.append(
                dict(
                    id=f"{name}-missing-{i}",
                    family=name,
                    split=split,
                    source=text,
                    memories=summaries,
                    expected=True,
                )
            )
            coverage.append(
                dict(
                    id=f"{name}-covered-{i}",
                    family=name,
                    split=split,
                    source=text,
                    memories=[*summaries, text],
                    expected=False,
                )
            )
    return {
        "version": "context-details-v1",
        "items": items,
        "queries": queries,
        "coverage": coverage,
    }
