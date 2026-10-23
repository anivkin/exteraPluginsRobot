import asyncio
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field

from aiogram.methods import AnswerCallbackQuery


logger = logging.getLogger(__name__)


@dataclass
class CallbackTrace:
    query_id: str
    chat_id: int | None
    action: str
    started: float = field(default_factory=time.perf_counter)
    api_calls: int = 0
    api_seconds: float = 0
    first_ui_ms: float | None = None
    acknowledged: bool = False
    ack_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


callback_trace: ContextVar[CallbackTrace | None] = ContextVar("callback_trace", default=None)
_UI_METHODS = {
    "sendMessage", "sendPhoto", "editMessageMedia", "editMessageText", "editMessageCaption", "editMessageReplyMarkup",
}


class TelegramRequestTimingMiddleware:
    async def __call__(self, make_request, bot, method):
        trace = callback_trace.get()
        name = method.__api_method__

        async def send():
            started = time.perf_counter()
            succeeded = False
            try:
                result = await make_request(bot, method)
                succeeded = True
                return result
            finally:
                elapsed = time.perf_counter() - started
                if trace is not None:
                    trace.api_calls += 1
                    trace.api_seconds += elapsed
                    if (succeeded and trace.first_ui_ms is None and name in _UI_METHODS
                            and getattr(method, "chat_id", None) == trace.chat_id):
                        trace.first_ui_ms = (time.perf_counter() - trace.started) * 1000
                if elapsed >= 0.75 and name != "getUpdates":
                    logger.info("event=telegram.request_slow method=%s action=%s duration_ms=%.0f success=%s",
                                name, trace.action if trace else "-", elapsed * 1000, succeeded)

        if trace and isinstance(method, AnswerCallbackQuery) and method.callback_query_id == trace.query_id:
            async with trace.ack_lock:
                if trace.acknowledged and not (method.text or method.show_alert or method.url):
                    return True
                result = await send()
                if result:
                    trace.acknowledged = True
                return result
        return await send()
