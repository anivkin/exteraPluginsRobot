from __future__ import annotations

import html
from copy import deepcopy
from datetime import datetime, timezone

REASON_TEMPLATES_VERSION = 1
TEMPLATES_LIMIT = 30
TEMPLATE_PAGE_SIZE = 6
TEMPLATE_PAGE_BUDGET = 2600

DEFAULT_APPROVE_TEMPLATES = ['Полезный плагин, работает стабильно', 'Уникальный функционал, аналогов в каталоге нет', 'Качественная реализация, код аккуратный', 'Заметно лучше существующего аналога', 'Проверено на актуальной версии — работает', 'Закрывает частый запрос пользователей', 'Оптимизировано, клиент не нагружает', 'Форк оправдан: оригинал заброшен и не работает', 'Описание и инструкция оформлены корректно', 'Замечаний нет, к публикации готов']

LEGACY_REJECT_TEMPLATES = ['Плагин не даёт заметной пользы по сравнению с уже опубликованными решениями', 'Функция уже есть в exteraGram, AyuGram, Telegram или существующем плагине', 'Реализация дублирует существующий плагин без заметных преимуществ', 'Задача слишком простая для отдельного плагина', 'В работе найдены критические ошибки или нестабильность', 'Плагин не работает на актуальной версии клиента', 'Метаданные заполнены некорректно либо файл не проходит проверку', 'Описание не объясняет назначение плагина или способ использования', 'В коде есть подозрительное действие, скрытая загрузка или небезопасная логика', 'Код требует доработки и повторной проверки перед публикацией']

DEFAULT_UPDATE_APPROVE_TEMPLATES = ['Версия повышена корректно, метаданные обновления заполнены', 'Обновление проверено на актуальной версии клиента — работает стабильно', 'Исправлены заявленные ошибки, результат соответствует чейнджлогу', 'Восстановлена совместимость с актуальной версией exteraGram/AyuGram', 'Добавлены полезные функции без ухудшения существующего поведения', 'Улучшены производительность и стабильность плагина', 'Критических ошибок и регрессий после обновления не обнаружено', 'Исправлена проблема безопасности или нежелательное поведение', 'Код обновления аккуратный, лишних зависимостей и скрытых действий нет', 'Замечаний к обновлению нет, новая версия готова к публикации']

LEGACY_UPDATE_REJECT_TEMPLATES = ['Версия плагина должна быть строго выше опубликованной', 'Минимальная версия клиента указана ниже допустимой или заполнена неверно', 'Заявленные изменения отсутствуют в файле или не соответствуют чейнджлогу', 'Чейнджлог отсутствует либо не объясняет, что именно изменилось', 'Обновление содержит критические ошибки или ломает существующие функции', 'Обновление не работает на актуальной версии exteraGram/AyuGram', 'ID плагина не совпадает с ID опубликованной версии', 'Метаданные обновления заполнены некорректно или не парсятся', 'В обновлении появился подозрительный код, скрытая загрузка или нежелательное действие', 'После обновления качество, стабильность или удобство плагина ухудшились']

REJECT_PAIRS = [
    ("П. 2.1 — Дубликат плагина: заметных преимуществ нет. Добавьте новые функции или измеримое улучшение относительно аналога.", "Rule 2.1 — Duplicate plugin: no clear advantage. Add new features or a measurable improvement over the existing plugin."),
    ("П. 2.1 — Функция уже есть в клиенте, включая анонсированную. Добавьте возможности, которых нет во встроенной функции.", "Rule 2.1 — The client already has this feature, including announced features. Add capabilities the built-in feature lacks."),
    ("П. 2.2 — Одна косметическая правка или готовое действие. Объедините их в полезный инструмент с более широкими возможностями.", "Rule 2.2 — A single cosmetic edit or preset action. Turn it into a useful tool with broader capabilities."),
    ("П. 2.4 — Локальная шутка без практической пользы. Добавьте полезный сценарий или объясните актуальность мема для широкой аудитории.", "Rule 2.4 — An inside joke with no practical value. Add a useful use case or explain why the meme is relevant to a wider audience."),
    ("П. 2.3 — Сбой при запуске или использовании. Исправьте ошибку и приложите пример работы на актуальной версии клиента.", "Rule 2.3 — Crash on startup or during use. Fix the error and provide a working example on the current client version."),
    ("П. 2.3 — Тормоза и лишние обновления интерфейса. Уберите тяжёлую работу из UI-потока и повторные refresh() без необходимости.", "Rule 2.3 — Lag and excessive UI refreshes. Move heavy work off the UI thread and remove unnecessary refresh() calls."),
    ("П. 2.3 — Сломанный интерфейс или локализация. Исправьте расположение элементов и строки для выбранного языка клиента.", "Rule 2.3 — Broken UI or localization. Fix element placement and strings for the selected client language."),
    ("П. 2.3 — Конфликт с другим плагином. Устраните гонку или конфликт хуков и проверьте совместную работу.", "Rule 2.3 — Conflict with another plugin. Resolve the race or hook conflict and test both plugins together."),
    ("П. 2.3 — Устаревающие значения зашиты в код. Обновляйте курсы, ссылки и другие изменяемые данные либо дайте их настроить.", "Rule 2.3 — Time-sensitive values are hardcoded. Refresh rates, links and other changing data or make them configurable."),
    ("П. 2.5 — Сгенерированный код не проверен и содержит ошибки. Разберите код, исправьте дефекты и протестируйте все заявленные функции.", "Rule 2.5 — Generated code is unverified and contains errors. Review the code, fix the defects and test every advertised feature."),
    ("П. 1.1 — Спам, накрутки или автоматизация нарушений. Удалите массовые рассылки, автофарм, автоинвайт и аналогичные механизмы.", "Rule 1.1 — Spam, artificial engagement or automated abuse. Remove bulk messaging, auto-farming, auto-invites and similar mechanisms."),
    ("П. 1.2 — Вред пользователям или слежка. Удалите сбор чужих данных, фишинг, отслеживание скрытого онлайна и другие вредящие функции.", "Rule 1.2 — User harm or surveillance. Remove collection of others' data, phishing, hidden-online tracking and other harmful features."),
    ("П. 1.3 — Скрытая загрузка или выполнение кода. Удалите скрытый механизм; допустимые расширения и автообновление сделайте явной опцией, выключенной по умолчанию.", "Rule 1.3 — Hidden code download or execution. Remove the hidden mechanism; make permitted extensions and auto-updates explicit, opt-in and off by default."),
    ("П. 1.3 — Нежелательные действия без ведома пользователя. Удалите автоподписки и скрытую передачу данных.", "Rule 1.3 — Unwanted actions without the user's knowledge. Remove automatic channel subscriptions and hidden data transfers."),
    ("П. 1.4 — Поддельные галочки или бейджи доверия. Удалите имитацию; допустима только пометка своего канала и себя как разработчика.", "Rule 1.4 — Fake verification or trust badges. Remove the imitation; only marking your own channel and yourself as its developer is allowed."),
    ("П. 1.5 — Блокировка или подмена официальных ресурсов. Восстановите доступ и исходное содержимое официальных каналов проекта.", "Rule 1.5 — Official resources are blocked or altered. Restore access and the original content of official project channels."),
    ("Раздел 3 — Не раскрыто происхождение форка. Укажите, что это форк, автора оригинала и конкретные изменения или исправления.", "Section 3 — The fork's origin is undisclosed. Label it as a fork, credit the original author and describe the changes or fixes."),
    ("Раздел 3 — Косметический форк или форк живого плагина. Добавьте существенные изменения и подтвердите допустимость публикации по правилам форков.", "Section 3 — Cosmetic fork or fork of an actively maintained plugin. Add substantial changes and demonstrate eligibility under the fork rules."),
    ("Раздел 3 — Форк форка без согласия обоих авторов. Приложите разрешения автора оригинала и автора исходного форка.", "Section 3 — Fork of a fork without both authors' consent. Provide permission from the original author and the author of the source fork."),
    ("Тех. требования — Метаданные не читаются или заполнены неверно. Исправьте id, name, version, app_version и author; проверьте разбор файла.", "Technical requirements — Invalid or unreadable metadata. Fix id, name, version, app_version and author; verify that the file parses."),
    ("Тех. требования — Некорректный файл плагина. Пришлите исправный файл без ошибок кодировки: .plugin без BOM до 8 МБ; .elyx/.eaf до 100 МБ.", "Technical requirements — Invalid plugin file. Submit a valid file without encoding errors: .plugin without BOM up to 8 MB; .elyx/.eaf up to 100 MB."),
    ("Тех. требования — Назначение или инструкция неясны. Опишите, что делает плагин, где включить его функции и как ими пользоваться.", "Technical requirements — Purpose or instructions are unclear. Explain what the plugin does, where to enable its features and how to use them."),
]

UPDATE_REJECT_PAIRS = [
    ("Требования к обновлению — Чейнджлог отсутствует или не объясняет изменения. Перечислите новые функции, исправления и отличия от опубликованной версии.", "Update requirements — The changelog is missing or unclear. List new features, fixes and differences from the published version."),
    ("Требования к обновлению — Нет новых примеров изменений. Приложите отдельные скриншоты или видео новой версии, показывающие заявленные изменения.", "Update requirements — No new examples of the changes. Attach separate screenshots or a video of the new version demonstrating the advertised changes."),
    ("Тех. требования — Версия обновления не выше опубликованной. Увеличьте version и отправьте новый файл.", "Technical requirements — The update version is not higher than the published version. Increase version and submit a new file."),
    ("Тех. требования — Минимальная версия клиента указана неверно. Укажите поддерживаемую версию и проверьте обновление на актуальном клиенте.", "Technical requirements — Invalid minimum client version. Set a supported version and test the update on the current client."),
    ("Тех. требования — ID отличается от опубликованного плагина. Верните исходный id; отдельный плагин отправляйте новой заявкой.", "Technical requirements — The ID differs from the published plugin. Restore its original id; submit a separate plugin as a new request."),
    ("Тех. требования — Метаданные обновления не читаются. Исправьте обязательные поля и проверьте разбор нового файла.", "Technical requirements — Update metadata cannot be parsed. Fix the required fields and verify that the new file parses."),
    ("Тех. требования — Файл обновления повреждён или превышает лимит. Отправьте исправный файл: .plugin без BOM до 8 МБ; .elyx/.eaf до 100 МБ.", "Technical requirements — The update file is damaged or exceeds its size limit. Submit a valid file: .plugin without BOM up to 8 MB; .elyx/.eaf up to 100 MB."),
    ("П. 2.3 — Заявленного исправления нет в файле. Внесите исправление, проверьте его и опишите фактические изменения в чейнджлоге.", "Rule 2.3 — The advertised fix is missing from the file. Implement and test it, then describe the actual changes in the changelog."),
    ("П. 2.3 — После обновления сломалась работавшая функция. Устраните регрессию и проверьте старые сценарии вместе с новыми.", "Rule 2.3 — The update breaks a previously working feature. Fix the regression and test existing use cases alongside the new ones."),
    ("П. 2.3 — Обновление вызывает вылет. Исправьте сбой и приложите пример работы новой версии на актуальном клиенте.", "Rule 2.3 — The update causes a crash. Fix it and provide a working example of the new version on the current client."),
    ("П. 2.3 — Новая версия тормозит или расходует лишние ресурсы. Уберите частые refresh(), тяжёлые хуки и лишнюю фоновую работу.", "Rule 2.3 — The new version lags or wastes resources. Remove excessive refresh() calls, costly hooks and unnecessary background work."),
    ("П. 2.3 — Обновление ломает интерфейс или inline. Исправьте отображение и действия элементов на поддерживаемых экранах.", "Rule 2.3 — The update breaks the UI or inline controls. Fix their layout and actions on supported screens."),
    ("П. 2.3 — Нарушена локализация обновления. Добавьте переводы новых строк и проверьте выбранный язык клиента.", "Rule 2.3 — Update localization is broken. Translate the new strings and verify the selected client language."),
    ("П. 2.3 — Новые хуки конфликтуют с другим плагином. Устраните гонку или конфликт и проверьте совместную работу.", "Rule 2.3 — New hooks conflict with another plugin. Resolve the race or conflict and test both plugins together."),
    ("П. 2.3 — После отключения остаются хуки, таймеры или изменённый интерфейс. Освободите ресурсы и восстановите состояние при выгрузке.", "Rule 2.3 — Hooks, timers or UI changes remain after disabling. Release resources and restore the original state on unload."),
    ("П. 2.5 — Новый сгенерированный код не проверен и содержит ошибки. Разберите изменения, исправьте дефекты и протестируйте обновление.", "Rule 2.5 — New generated code is unverified and contains errors. Review the changes, fix the defects and test the update."),
    ("П. 1.3 — В обновлении появилась скрытая загрузка или выполнение кода. Удалите механизм; допустимые расширения включайте только явной опцией, выключенной по умолчанию.", "Rule 1.3 — The update adds hidden code download or execution. Remove the mechanism; enable permitted extensions only through an explicit opt-in option, off by default."),
    ("П. 1.3 — Обновление добавило автоподписки или скрытую передачу данных. Удалите эти действия и проверьте все новые сетевые обращения.", "Rule 1.3 — The update adds auto-subscriptions or hidden data transfers. Remove them and review every new network request."),
    ("Пп. 1.1–1.2 — Добавлены спам, накрутки, слежка или вред пользователям. Полностью удалите запрещённые функции из обновления.", "Rules 1.1–1.2 — The update adds spam, artificial engagement, surveillance or user harm. Remove the prohibited features entirely."),
    ("Пп. 1.4–1.5 — Добавлены поддельные бейджи или подмена официальных ресурсов. Удалите имитацию доверия и восстановите официальное содержимое.", "Rules 1.4–1.5 — The update adds fake badges or alters official resources. Remove the false trust cues and restore official content."),
    ("П. 2.1 — Новая функция дублирует готовое решение без преимуществ. Добавьте отличия или уберите дубликат из обновления.", "Rule 2.1 — A new feature duplicates an existing solution without an advantage. Add a clear improvement or remove the duplicate from the update."),
    ("Раздел 3 — Обновление содержит чужой форк без обязательных сведений. Укажите оригинал, автора и изменения; для форка форка приложите согласие обоих авторов.", "Section 3 — The update includes a fork without the required attribution. Identify the original, its author and your changes; obtain both authors' consent for a fork of a fork."),
]

DEFAULT_REJECT_TEMPLATES = [ru for ru, _ in REJECT_PAIRS]
DEFAULT_UPDATE_REJECT_TEMPLATES = [ru for ru, _ in UPDATE_REJECT_PAIRS]

APPROVE_EN = [
    "Useful plugin, works reliably",
    "Unique functionality, no equivalent in the catalog",
    "Well implemented, clean code",
    "Noticeably better than the existing alternative",
    "Tested on the current version and working",
    "Addresses a frequent user request",
    "Optimized, does not overload the client",
    "Justified fork: the original is abandoned and no longer works",
    "Description and instructions are clear",
    "No issues, ready for publication",
]
UPDATE_APPROVE_EN = [
    "Version increased correctly, update metadata is complete",
    "Update tested on the current client version and working reliably",
    "Reported bugs fixed, results match the changelog",
    "Compatibility with the current exteraGram/AyuGram version restored",
    "Useful features added without disrupting existing behavior",
    "Plugin performance and stability improved",
    "No critical bugs or regressions found after the update",
    "Security issue or unwanted behavior fixed",
    "Clean update code, no unnecessary dependencies or hidden actions",
    "No issues with the update, the new version is ready for publication",
]

TEMPLATE_CONFIG_KEYS = {
    "reject": "reject_templates",
    "approve": "approve_templates",
    "update_reject": "update_reject_templates",
    "update_approve": "update_approve_templates",
}
DEFAULTS = {
    "reject": DEFAULT_REJECT_TEMPLATES,
    "approve": DEFAULT_APPROVE_TEMPLATES,
    "update_reject": DEFAULT_UPDATE_REJECT_TEMPLATES,
    "update_approve": DEFAULT_UPDATE_APPROVE_TEMPLATES,
}
LEGACY_DEFAULTS = {
    **DEFAULTS,
    "reject": LEGACY_REJECT_TEMPLATES,
    "update_reject": LEGACY_UPDATE_REJECT_TEMPLATES,
}
BUILTIN_PAIRS = [*REJECT_PAIRS, *UPDATE_REJECT_PAIRS,
                 *zip(DEFAULT_APPROVE_TEMPLATES, APPROVE_EN),
                 *zip(DEFAULT_UPDATE_APPROVE_TEMPLATES, UPDATE_APPROVE_EN)]
BUILTIN_TRANSLATIONS = {text: {"ru": ru, "en": en} for ru, en in BUILTIN_PAIRS for text in (ru, en)}


def template_kind(raw: str) -> str:
    return raw if raw in TEMPLATE_CONFIG_KEYS else "reject"


def load_reason_templates(config: dict, kind: str = "reject", lang: str = "ru") -> list[str]:
    kind = template_kind(kind)
    raw = config.get(TEMPLATE_CONFIG_KEYS[kind])
    values = raw if isinstance(raw, list) else DEFAULTS[kind]
    language = "en" if lang == "en" else "ru"
    return [BUILTIN_TRANSLATIONS.get(value, {}).get(language, value)
            for item in values if (value := str(item).strip())]


def upgrade_reason_templates(config: dict) -> bool:
    try:
        current = int(config.get("reason_templates_version") or 0)
    except (ValueError, TypeError):
        current = 0
    if current >= REASON_TEMPLATES_VERSION:
        return False
    previous = {key: deepcopy(config[key]) for key in TEMPLATE_CONFIG_KEYS.values() if key in config}
    archive = config.get("templates_archive")
    if not isinstance(archive, list):
        archive = [] if archive is None else [deepcopy(archive)]
    else:
        archive = deepcopy(archive)
    archive.append({"version": current, "upgraded_to": REASON_TEMPLATES_VERSION,
                    "archived_at": datetime.now(timezone.utc).isoformat(), "templates": previous})
    for kind, key in TEMPLATE_CONFIG_KEYS.items():
        raw = config.get(key)
        if not isinstance(raw, list) or raw == LEGACY_DEFAULTS[kind]:
            config[key] = list(DEFAULTS[kind])
    config["templates_archive"] = archive
    config["reason_templates_version"] = REASON_TEMPLATES_VERSION
    return True


def templates_allowed(entry: dict | None, *, check_access: bool = True) -> bool:
    if not isinstance(entry, dict) or entry.get("type") not in {"new", "update"}:
        return False
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    if payload.get("is_appeal") or str(entry.get("status")) in {"banned", "blocked"}:
        return False
    if any(payload.get(key) or entry.get(key) for key in ("banned", "blocked", "is_banned", "is_blocked")):
        return False
    if not check_access:
        return True
    from bot.services.validation import is_plugin_blocked
    from user_store import is_user_banned

    plugin = payload.get("plugin") if isinstance(payload.get("plugin"), dict) else {}
    plugin_id = str(plugin.get("id") or "").strip()
    if plugin_id and is_plugin_blocked(plugin_id):
        return False
    user_id = payload.get("user_id")
    try:
        return not (user_id and is_user_banned(int(user_id)))
    except (ValueError, TypeError):
        return False


def _utf16_size(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _template_chunks(text: str) -> list[str]:
    chunks = []
    current = []
    size = 0
    for char in str(text):
        width = _utf16_size(html.escape(char, quote=False))
        if size + width > TEMPLATE_PAGE_BUDGET:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(char)
        size += width
    chunks.append("".join(current))
    return chunks


def template_pages(templates: list[str]) -> list[list[tuple[int, str]]]:
    pages, page, size = [], [], 0
    for index, value in enumerate(templates):
        for chunk in _template_chunks(value):
            width = _utf16_size(html.escape(chunk, quote=False)) + 24
            if page and (len(page) >= TEMPLATE_PAGE_SIZE or size + width > TEMPLATE_PAGE_BUDGET):
                pages.append(page)
                page, size = [], 0
            page.append((index, chunk))
            size += width
    if page:
        pages.append(page)
    return pages or [[]]


def template_page(templates: list[str], page: int = 0) -> tuple[str, list[int], int, int]:
    pages = template_pages(templates)
    page = max(0, min(int(page), len(pages) - 1))
    items = pages[page]
    text = "\n\n".join(f"<b>{idx + 1}.</b> {html.escape(value, quote=False)}" for idx, value in items)
    return text, list(dict.fromkeys(idx for idx, _ in items)), page, len(pages)
