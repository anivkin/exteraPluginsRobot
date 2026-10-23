import json
from pathlib import Path

from bot.languages import SUPPORTED_LANGUAGES, language_fallbacks

DEFAULT_LANGUAGE = "ru"
TEXTS: dict[str, dict[str, str]] = {}

for _language in SUPPORTED_LANGUAGES:
    _translations = json.loads((Path(__file__).parent / "locales" / f"{_language}.json").read_text(encoding="utf-8"))
    for _key, _value in _translations.items():
        if not isinstance(_value, str):
            raise ValueError(f"Invalid translation: {_language}:{_key}")
        TEXTS.setdefault(_key, {})[_language] = _value


def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    texts = TEXTS.get(key, {})
    text = next((texts[language] for language in language_fallbacks(lang) if texts.get(language)), key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except KeyError:
            return text
    return text
