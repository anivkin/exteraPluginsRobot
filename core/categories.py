from collections.abc import Mapping


CATEGORY_KEYS = (
    "appearance", "chats", "media", "privacy", "tools", "integrations", "fun", "libraries",
)
MAX_CATEGORIES = 3
LEGACY_CATEGORIES = {
    "customization": "appearance", "utilities": "tools", "informational": "tools", "library": "libraries",
}


def normalize_categories(value, *, strict=False):
    if value is None:
        return []
    if isinstance(value, str) and not strict:
        value = [value]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("__category__ must be a list of category names")
    result = []
    for item in value:
        key = item.strip().lower()
        if not strict:
            key = LEGACY_CATEGORIES.get(key, key)
        if key not in CATEGORY_KEYS:
            if strict:
                raise ValueError("Unknown plugin category: " + item)
            continue
        if key not in result:
            result.append(key)
    if len(result) > MAX_CATEGORIES:
        if strict:
            raise ValueError("A plugin can have at most 3 categories")
        result = result[:MAX_CATEGORIES]
    return result


def categories_for(value):
    if isinstance(value, Mapping):
        for key in ("category_keys", "categories", "category_key", "category"):
            raw = value.get(key)
            if raw:
                return normalize_categories(raw)
        plugin = value.get("plugin")
        if isinstance(plugin, Mapping):
            return categories_for(plugin)
        return []
    return normalize_categories(value)


def category_fields(value):
    keys = categories_for(value)
    return {
        "category_keys": keys,
        "category_key": keys[0] if keys else "",
        "category_label": ", ".join(keys),
    }
