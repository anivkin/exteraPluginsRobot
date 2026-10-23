import json
import logging
import os
import stat
import tempfile
from copy import deepcopy
from pathlib import Path


_SECRET_FIELDS = {"userbot": ("api_id", "api_hash"), "bot_mtproto": ("api_id", "api_hash")}
_permission_warnings = set()
logger = logging.getLogger(__name__)


def split_config(config):
    public = deepcopy(config)
    secrets = {}
    if "bot_token" in public:
        secrets["bot_token"] = public.pop("bot_token")
    for section, fields in _SECRET_FIELDS.items():
        values = public.get(section)
        if not isinstance(values, dict):
            continue
        private = {key: values.pop(key) for key in fields if key in values}
        if private:
            secrets[section] = private
    return public, secrets


def merge_secrets(public, secrets, environ=None):
    result = deepcopy(public)
    if "bot_token" in secrets:
        result["bot_token"] = secrets["bot_token"]
    for section, fields in _SECRET_FIELDS.items():
        values = secrets.get(section, {})
        if isinstance(values, dict) and values:
            target = result.setdefault(section, {})
            if not isinstance(target, dict):
                target = result[section] = {}
            target.update({key: values[key] for key in fields if key in values})
    if environ is not None:
        if "BOT_TOKEN" in environ:
            result["bot_token"] = environ["BOT_TOKEN"]
        for section in _SECRET_FIELDS:
            for key, env_key in (("api_id", "TELEGRAM_API_ID"), ("api_hash", "TELEGRAM_API_HASH")):
                if env_key in environ:
                    target = result.setdefault(section, {})
                    if not isinstance(target, dict):
                        target = result[section] = {}
                    target[key] = int(environ[env_key]) if key == "api_id" else environ[env_key]
    return result


def read_secrets(path):
    if path.is_symlink():
        raise ValueError("Runtime secrets must not be a symlink")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {}
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        mode = stat.S_IMODE(os.fstat(stream.fileno()).st_mode)
        warning_key = (str(path), mode)
        if mode & 0o077 and warning_key not in _permission_warnings:
            _permission_warnings.add(warning_key)
            logger.warning(
                "event=runtime_config.permissions path=%s mode=%04o; "
                "prefer 0600 permissions on the host; reading without chmod",
                path, mode,
            )
        result = json.load(stream)
    if not isinstance(result, dict):
        raise ValueError("Runtime secrets must be a JSON object")
    return result


def atomic_write(path, payload):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Runtime secrets must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".runtime-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def write_secrets(path, secrets):
    atomic_write(path, (json.dumps(secrets, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def persisted_secrets(config, existing):
    public, changes = split_config(config)
    for section, values in list(changes.items()):
        if section == "bot_token":
            if "BOT_TOKEN" in os.environ and values == os.environ["BOT_TOKEN"]:
                if section in existing:
                    changes[section] = existing[section]
                else:
                    changes.pop(section)
            continue
        for key, env_key in (("api_id", "TELEGRAM_API_ID"), ("api_hash", "TELEGRAM_API_HASH")):
            if env_key not in os.environ or key not in values:
                continue
            override = int(os.environ[env_key]) if key == "api_id" else os.environ[env_key]
            if values[key] == override:
                previous = existing.get(section, {})
                if isinstance(previous, dict) and key in previous:
                    values[key] = previous[key]
                else:
                    values.pop(key)
    result = deepcopy(existing)
    for section, values in changes.items():
        if isinstance(values, dict):
            if not values:
                continue
            current = result.get(section)
            if not isinstance(current, dict):
                current = result[section] = {}
            current.update(values)
        else:
            result[section] = values
    return public, result
