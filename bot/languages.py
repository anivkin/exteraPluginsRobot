SUPPORTED_LANGUAGES = ("ru", "en", "uk", "zh")
LANGUAGE_NAMES = {"ru": "Русский", "en": "English", "uk": "Українська", "zh": "简体中文"}
LANGUAGE_FLAGS = {"ru": "🇷🇺", "en": "🇺🇸", "uk": "🇺🇦", "zh": "🇨🇳"}


def normalize_language(value, default="ru"):
    code = str(value or "").strip().lower().replace("_", "-").split("-", 1)[0]
    code = "uk" if code == "ua" else code
    return code if code in SUPPORTED_LANGUAGES else default


def language_fallbacks(value):
    language = normalize_language(value)
    return tuple(dict.fromkeys((language, "en" if language == "zh" else "ru", "en", "ru", *SUPPORTED_LANGUAGES)))


def localized_value(values, language, default=None):
    if not isinstance(values, dict):
        return default
    return next((values[key] for key in language_fallbacks(language) if values.get(key)), default)


def category_label(category, language):
    from bot.texts import t
    from core.categories import categories_for

    keys = categories_for(category.get("key"))
    if keys:
        return t(f"category_{keys[0]}_label_btn", language)
    return localized_value(category, language, category.get("key"))


def category_labels(value, language):
    from core.categories import categories_for

    return ", ".join(category_label({"key": key}, language) for key in categories_for(value))
