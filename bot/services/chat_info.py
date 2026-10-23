import asyncio
import time
from collections import OrderedDict


_cache: OrderedDict[tuple[int, int], tuple[float, dict[str, str]]] = OrderedDict()
_CACHE_LIMIT = 512
_CACHE_TTL = 300
_FAILURE_TTL = 10
_CONCURRENCY = 4


async def get_chat_labels(bot, chat_ids: list[int]) -> dict[int, dict[str, str]]:
    bot_id = getattr(bot, "id", None)
    bot_key = bot_id if isinstance(bot_id, int) else id(bot)
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def resolve(chat_id: int) -> tuple[int, dict[str, str]]:
        key = bot_key, chat_id
        cached = _cache.get(key)
        if cached and cached[0] > time.monotonic():
            _cache.move_to_end(key)
            return chat_id, dict(cached[1])
        async with semaphore:
            try:
                chat = await bot.get_chat(chat_id)
                labels = {
                    "username": str(getattr(chat, "username", None) or "").strip().lstrip("@"),
                    "name": str(getattr(chat, "full_name", None) or getattr(chat, "first_name", None) or "").strip(),
                    "title": str(getattr(chat, "title", None) or "").strip(),
                }
                ttl = _CACHE_TTL
            except Exception:
                labels, ttl = {}, _FAILURE_TTL
            _cache[key] = time.monotonic() + ttl, labels
            _cache.move_to_end(key)
            while len(_cache) > _CACHE_LIMIT:
                _cache.popitem(last=False)
            return chat_id, dict(labels)

    return dict(await asyncio.gather(*(resolve(chat_id) for chat_id in dict.fromkeys(chat_ids))))
