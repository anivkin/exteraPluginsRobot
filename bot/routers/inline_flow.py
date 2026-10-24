import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, ChosenInlineResult

from bot.context import get_lang
from bot.services.inline import PENDING_CALLBACK, RESULT_PREFIX, apply_inline_formatting, snapshot_for
from bot.texts import t


router = Router(name="inline-formatting")
logger = logging.getLogger(__name__)


@router.chosen_inline_result(F.result_id.startswith(RESULT_PREFIX))
async def on_chosen_inline_result(result: ChosenInlineResult) -> None:
    logger.info("event=inline.formatting.chosen bot_id=%s result_id=%s user_id=%s has_inline_id=%s",
                result.bot.id, result.result_id, result.from_user.id, bool(result.inline_message_id))
    if result.inline_message_id:
        await apply_inline_formatting(result.bot, result.result_id, result.from_user.id, result.inline_message_id)
    else:
        logger.warning("event=inline.formatting.chosen_without_inline_id result_id=%s", result.result_id)


@router.callback_query(F.data == PENDING_CALLBACK)
async def on_inline_pending(cb: CallbackQuery) -> None:
    await cb.answer(t("inline_formatting_expired", get_lang(cb.from_user.id)), show_alert=True)


@router.callback_query(F.data.regexp(r"^ifmt:[0-9a-f]{32}$"))
async def on_apply_inline_formatting(cb: CallbackQuery) -> None:
    lang = get_lang(cb.from_user.id)
    if not snapshot_for(int(cb.bot.id), cb.data, cb.from_user.id):
        await cb.answer(t("inline_formatting_expired", lang), show_alert=True)
        return
    logger.info("event=inline.formatting.callback bot_id=%s result_id=%s user_id=%s",
                cb.bot.id, cb.data, cb.from_user.id)
    applied = await apply_inline_formatting(cb.bot, cb.data, cb.from_user.id, cb.inline_message_id)
    if applied:
        await cb.answer()
    else:
        await cb.answer(t("inline_formatting_unavailable", lang), show_alert=True)
