import asyncio
import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessageContent,
    InputTextMessageContent,
)

from bot.formatting import normalize_custom_emoji, split_html, visible_html_length
from bot.context import get_lang
from bot.languages import SUPPORTED_LANGUAGES, normalize_language
from bot.texts import t


logger = logging.getLogger(__name__)
RESULT_PREFIX = "ifmt:"
PENDING_CALLBACK = "ifmt:pending"
_TTL = 3600
_MAX_SNAPSHOTS = 2000
_MAX_COMPLETED = 4000
_EMOJI_TAG = re.compile(r"</?tg-emoji\b[^>]*>", re.IGNORECASE)


def parse_inline_language(value: str, default: str = "ru") -> tuple[str, str]:
    text = str(value or "").strip()
    parts = text.rsplit(None, 1)
    if len(parts) == 2 and parts[1].lower() in SUPPORTED_LANGUAGES:
        return parts[0].strip(), parts[1].lower()
    return text, normalize_language(default)


@dataclass
class InlineSnapshot:
    bot_id: int
    owner_id: int
    expires: float
    caption: bool
    payload: dict
    reply_markup: InlineKeyboardMarkup | None


_snapshots: OrderedDict[str, InlineSnapshot] = OrderedDict()
_completed: OrderedDict[tuple[int, str], float] = OrderedDict()
_in_flight: set[tuple[int, str]] = set()


def fit_inline_html(text: str, limit: int) -> str:
    text = normalize_custom_emoji(text) or "—"
    if visible_html_length(text) <= limit:
        return text
    return split_html(text, limit - 1)[0].rstrip() + "…"


def _without_custom_emoji(text, entities):
    filtered = [entity for entity in (entities or []) if entity.type != "custom_emoji"]
    if entities is not None:
        return text, filtered, len(filtered) != len(entities)
    normalized = normalize_custom_emoji(text or "")
    return _EMOJI_TAG.sub("", normalized), None, bool(_EMOJI_TAG.search(normalized))


def _prune() -> None:
    now = time.monotonic()
    for key, value in list(_snapshots.items()):
        if value.expires <= now:
            del _snapshots[key]
    for key, expires in list(_completed.items()):
        if expires <= now:
            del _completed[key]
    while len(_snapshots) > _MAX_SNAPSHOTS:
        _snapshots.popitem(last=False)
    while len(_completed) > _MAX_COMPLETED:
        _completed.popitem(last=False)


def snapshot_for(bot_id: int, result_id: str, owner_id: int) -> InlineSnapshot | None:
    _prune()
    snapshot = _snapshots.get(result_id)
    if snapshot and snapshot.bot_id == bot_id and snapshot.owner_id == owner_id:
        return snapshot
    return None


def prepare_inline_results(query, results, lang="ru"):
    _prune()
    prepared = []
    for original in results:
        result = original.model_copy(deep=True)
        content = getattr(result, "input_message_content", None)
        caption = False
        payload = None
        if isinstance(content, InputTextMessageContent):
            text, entities, changed = _without_custom_emoji(content.message_text, content.entities)
            if changed:
                payload = {
                    "text": content.message_text if content.entities is not None else normalize_custom_emoji(content.message_text),
                    "parse_mode": None if content.entities is not None else content.parse_mode,
                    "entities": content.entities,
                    "link_preview_options": content.link_preview_options,
                    "disable_web_page_preview": content.disable_web_page_preview,
                }
                result.input_message_content = content.model_copy(update={
                    "message_text": text,
                    "entities": entities,
                    "parse_mode": None if entities is not None else content.parse_mode,
                })
        elif isinstance(content, InputRichMessageContent):
            rich = content.rich_message
            text, _, changed = _without_custom_emoji(rich.html, None)
            if rich.html is not None and changed:
                payload = {"text": None, "rich_message": rich.model_copy(update={"html": normalize_custom_emoji(rich.html)})}
                result.input_message_content = content.model_copy(update={
                    "rich_message": rich.model_copy(update={"html": text}),
                })
        elif getattr(result, "caption", None):
            text, entities, changed = _without_custom_emoji(result.caption, result.caption_entities)
            if changed:
                caption = True
                payload = {
                    "caption": result.caption if result.caption_entities is not None else normalize_custom_emoji(result.caption),
                    "parse_mode": None if result.caption_entities is not None else result.parse_mode,
                    "caption_entities": result.caption_entities,
                    "show_caption_above_media": getattr(result, "show_caption_above_media", None),
                }
                result.caption = text
                result.caption_entities = entities
                if entities is not None:
                    result.parse_mode = None

        if payload is None:
            prepared.append(result)
            continue

        bot_id, owner_id = int(query.bot.id), int(query.from_user.id)
        serialized = json.dumps(original.model_dump(exclude_none=True), ensure_ascii=False, sort_keys=True, default=str)
        source = f"{bot_id}:{owner_id}:{serialized}"
        result_id = RESULT_PREFIX + hashlib.sha256(source.encode()).hexdigest()[:32]
        markup = original.reply_markup.model_copy(deep=True) if original.reply_markup else None
        _snapshots[result_id] = InlineSnapshot(bot_id, owner_id, time.monotonic() + _TTL, caption, payload, markup)
        _snapshots.move_to_end(result_id)
        result.id = result_id
        if not result.reply_markup or not result.reply_markup.inline_keyboard:
            result.reply_markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=t("inline_apply_formatting", lang), callback_data=result_id),
            ]])
        prepared.append(result)
    _prune()
    return prepared


async def answer_inline(query, results, **kwargs):
    results = prepare_inline_results(query, results, get_lang(query.from_user.id))
    if any(result.id.startswith(RESULT_PREFIX) for result in results):
        kwargs["is_personal"] = True
    return await query.answer(results, **kwargs)


async def apply_inline_formatting(bot, result_id: str, owner_id: int, inline_message_id: str) -> bool:
    snapshot = snapshot_for(int(bot.id), result_id, owner_id)
    if not snapshot:
        logger.warning("event=inline.formatting.snapshot_missing bot_id=%s result_id=%s user_id=%s", bot.id, result_id, owner_id)
        return False
    if not inline_message_id:
        logger.warning("event=inline.formatting.missing_inline_id bot_id=%s result_id=%s", bot.id, result_id)
        return False
    key = (int(bot.id), inline_message_id)
    if key in _completed or key in _in_flight:
        return True
    _in_flight.add(key)
    try:
        method = bot.edit_message_caption if snapshot.caption else bot.edit_message_text
        for attempt in range(2):
            try:
                await method(
                    inline_message_id=inline_message_id,
                    reply_markup=snapshot.reply_markup,
                    **snapshot.payload,
                )
            except TelegramRetryAfter as exc:
                if attempt or exc.retry_after > 30:
                    logger.warning("event=inline.formatting.retry_later retry_after=%s", exc.retry_after)
                    return False
                await asyncio.sleep(exc.retry_after)
            except TelegramBadRequest as exc:
                if "message is not modified" not in str(exc).lower() and "message_not_modified" not in str(exc).lower():
                    logger.warning("event=inline.formatting.rejected reason=%s", exc.message)
                    return False
                break
            except TelegramAPIError as exc:
                logger.warning("event=inline.formatting.failed error_type=%s", type(exc).__name__)
                return False
            else:
                break
        _completed[key] = time.monotonic() + _TTL
        _prune()
        logger.info("event=inline.formatting.applied bot_id=%s result_id=%s mode=%s", bot.id, result_id,
                    "caption" if snapshot.caption else "rich" if "rich_message" in snapshot.payload else "text")
        return True
    finally:
        _in_flight.discard(key)
        if key not in _completed and (not snapshot.reply_markup or not snapshot.reply_markup.inline_keyboard):
            try:
                await bot.edit_message_reply_markup(inline_message_id=inline_message_id, reply_markup=None)
            except TelegramAPIError as exc:
                logger.warning("event=inline.formatting.cleanup_failed error_type=%s", type(exc).__name__)
