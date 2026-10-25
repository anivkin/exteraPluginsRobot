import asyncio
import logging
import re
import time
from collections import OrderedDict
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter


_cache: OrderedDict[tuple[int, int], tuple[float, dict[str, str]]] = OrderedDict()
_CACHE_LIMIT = 512
_CACHE_TTL = 300
_FAILURE_TTL = 10
_CONCURRENCY = 4
_LOOKUP_TIMEOUT = 3
logger = logging.getLogger(__name__)


def _bot_key(bot):
    bot_id = getattr(bot, "id", None)
    return bot_id if isinstance(bot_id, int) else id(bot)


def _usernames(profile) -> tuple[str, str]:
    primary = str(getattr(profile, "username", None) or "").strip().lstrip("@")
    primary = primary if re.fullmatch(r"[A-Za-z0-9_]{1,32}", primary) else ""
    aliases = getattr(profile, "active_usernames", None)
    aliases = aliases if isinstance(aliases, (list, tuple)) else []
    active = [value.strip().lstrip("@") for value in aliases if isinstance(value, str)]
    active = [value for value in active if re.fullmatch(r"[A-Za-z0-9_]{1,32}", value)]
    return primary or next(iter(active), ""), primary


def _store_identity(user_id: int, username: str, primary: str, name: str) -> None:
    from core.user_store import get_user, update_user

    stored = get_user(user_id)
    fields = {"username": username, "primary_username": primary, "full_name": name or stored.get("full_name") or ""}
    try:
        fresh = 0 <= time.time() - float(stored.get("identity_checked_at") or 0) < _CACHE_TTL
    except (TypeError, ValueError):
        fresh = False
    if not fresh or any(stored.get(key) != value for key, value in fields.items()):
        update_user(user_id, **fields, identity_checked_at=time.time())


def observe_user_identity(user, bot=None) -> None:
    from core.user_store import get_user, update_user

    if not user or user.is_bot:
        return
    username, primary = _usernames(user)
    name = str(user.full_name or "").strip()
    key = _bot_key(bot), int(user.id)
    if username:
        _store_identity(int(user.id), username, primary, name)
        if bot is not None:
            _cache[key] = time.monotonic() + _CACHE_TTL, {"username": username, "name": name, "title": ""}
            _cache.move_to_end(key)
    else:
        stored = get_user(user.id)
        changes = {}
        if stored.get("full_name") != name:
            changes["full_name"] = name
        if stored.get("primary_username") or ("primary_username" not in stored and stored.get("username")):
            changes.update(identity_checked_at=0, primary_username="")
            _cache.pop(key, None)
        if changes:
            update_user(user.id, **changes)
    while len(_cache) > _CACHE_LIMIT:
        _cache.popitem(last=False)


async def get_chat_labels(bot, chat_ids: list[int], *, resolve_members: bool = False) -> dict[int, dict[str, str]]:
    bot_key = _bot_key(bot)
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def fetch(chat_id):
        try:
            return await bot.get_chat(chat_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            if not resolve_members or chat_id <= 0:
                raise
            from bot.cache import get_config

            forum_id = int((get_config().get("moderation") or {}).get("forum_chat_id") or 0)
            if not forum_id:
                raise
            forum_id = forum_id if forum_id < 0 else int(f"-100{forum_id}")
            member = await bot.get_chat_member(forum_id, chat_id)
            user = member.user
            if user.id != chat_id:
                raise ValueError("Unexpected member identity")
            return user

    async def resolve(chat_id: int) -> tuple[int, dict[str, str]]:
        key = bot_key, chat_id
        cached = _cache.get(key)
        if cached and cached[0] > time.monotonic():
            _cache.move_to_end(key)
            return chat_id, dict(cached[1])
        async with semaphore:
            current = _cache.get(key)
            if current and current[0] > time.monotonic():
                return chat_id, dict(current[1])
            try:
                chat = await asyncio.wait_for(fetch(chat_id), timeout=_LOOKUP_TIMEOUT)
                current = _cache.get(key)
                if current and current is not cached and current[0] > time.monotonic():
                    return chat_id, dict(current[1])
                username, primary = _usernames(chat)
                labels = {
                    "username": username,
                    "name": str(getattr(chat, "full_name", None) or getattr(chat, "first_name", None) or "").strip(),
                    "title": str(getattr(chat, "title", None) or "").strip(),
                }
                ttl = _CACHE_TTL if username else _FAILURE_TTL
                if resolve_members and chat_id > 0:
                    _store_identity(chat_id, username, primary, labels["name"])
            except TelegramRetryAfter as exc:
                labels, ttl = {}, max(_FAILURE_TTL, float(exc.retry_after))
            except Exception as exc:
                if resolve_members:
                    logger.info("event=admin.identity_unavailable user_id=%s error_type=%s", chat_id, type(exc).__name__)
                labels, ttl = {}, _FAILURE_TTL
            _cache[key] = time.monotonic() + ttl, labels
            _cache.move_to_end(key)
            while len(_cache) > _CACHE_LIMIT:
                _cache.popitem(last=False)
            return chat_id, dict(labels)

    return dict(await asyncio.gather(*(resolve(chat_id) for chat_id in dict.fromkeys(chat_ids))))
