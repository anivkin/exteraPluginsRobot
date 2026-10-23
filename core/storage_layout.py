import fcntl
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing, contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_TABLES = frozenset(("plugins_items", "icons_items"))
ADMIN_TABLES = frozenset(("documents", "requests_items", "users_items", "subscriptions_items", "updated_items", "joinly_items"))
MIGRATION_KEY = "migration:storage_layout:v1"
APPLICATION_ID = 1162891825


class StorageError(RuntimeError):
    pass


class StorageCorruptError(StorageError):
    pass


def resolve_path(value, fallback):
    path = Path(value) if value else Path(fallback)
    return (path if path.is_absolute() else ROOT / path).resolve()


def table_exists(conn, table, schema="main"):
    return conn.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


@contextmanager
def legacy_snapshot(path):
    if not path.exists():
        yield None
        return
    with tempfile.TemporaryDirectory(prefix="robot-legacy-") as directory:
        files = [path, Path(str(path) + "-wal"), Path(str(path) + "-journal")]
        def signatures():
            result = []
            for file in files:
                try:
                    stat = file.stat()
                    result.append((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
                except FileNotFoundError:
                    result.append(None)
            return result
        before = signatures()
        if before[2] is not None and before[2][2]:
            raise StorageError("Legacy database has a rollback journal; recover a copy before migration")
        target = Path(directory) / "legacy.sqlite3"
        shutil.copyfile(path, target)
        if before[1] is not None and before[1][2]:
            shutil.copyfile(files[1], Path(str(target) + "-wal"))
        if before != signatures():
            raise StorageError("Legacy database changed during snapshot; stop its writer and retry")
        try:
            with closing(sqlite3.connect(target)) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("BEGIN")
                check_integrity(conn, path)
                yield conn
        except sqlite3.DatabaseError as exc:
            raise StorageCorruptError(f"Legacy SQLite database is unreadable: {path}") from exc
        if before != signatures():
            raise StorageError("Legacy database changed during migration; stop its writer and retry")


def check_integrity(conn, path):
    try:
        rows = conn.execute("PRAGMA quick_check").fetchall()
    except sqlite3.DatabaseError as exc:
        raise StorageCorruptError(f"SQLite database is unreadable: {path}") from exc
    if len(rows) != 1 or rows[0][0] != "ok":
        raise StorageCorruptError(f"SQLite integrity check failed: {path}")


def read_config(conn):
    if conn is None:
        return {}
    for table in ("documents", "meta_store", "kv_store"):
        if not table_exists(conn, table):
            continue
        row = conn.execute(f"SELECT CAST(value AS BLOB) FROM {table} WHERE key='app_config'").fetchone()
        if row:
            try:
                config = json.loads(row[0])
            except (ValueError, UnicodeError) as exc:
                raise StorageError("Legacy app_config is invalid") from exc
            if not isinstance(config, dict):
                raise StorageError("Legacy app_config is not an object")
            return config
    return {}


def bootstrap_config(path):
    with legacy_snapshot(path) as conn:
        return read_config(conn)


def discover_paths():
    overrides = any(os.environ.get(key) for key in ("DATA_DIR", "SQLITE_PATH", "LEGACY_SQLITE_PATH", "ADMIN_SQLITE_PATH", "CATALOG_SQLITE_PATH"))
    config = {}
    selected = None
    if not overrides:
        for candidate in (ROOT / "data/data/admin.sqlite3", ROOT / "data/admin.sqlite3", ROOT / "data/data/storage.sqlite3", ROOT / "data/storage.sqlite3", Path("/app/data/admin.sqlite3"), Path("/app/data/data/storage.sqlite3"), Path("/app/data/storage.sqlite3")):
            if candidate.exists():
                config = bootstrap_config(candidate)
                if config:
                    selected = candidate
                    break
    storage = config.get("storage", {})
    if not isinstance(storage, dict):
        storage = {}
    old_env = os.environ.get("SQLITE_PATH")
    inferred_dir = next((Path(os.environ[key]).parent for key in ("ADMIN_SQLITE_PATH", "CATALOG_SQLITE_PATH", "SQLITE_PATH", "LEGACY_SQLITE_PATH") if os.environ.get(key)), Path("/app/data"))
    data_dir = resolve_path(os.environ.get("DATA_DIR") or storage.get("data_dir"), inferred_dir if overrides else (selected.parent if selected else Path("/app/data")))
    catalog = resolve_path(os.environ.get("CATALOG_SQLITE_PATH") or storage.get("catalog_sqlite_path"), data_dir / "catalog.sqlite3")
    admin = resolve_path(os.environ.get("ADMIN_SQLITE_PATH") or storage.get("admin_sqlite_path"), data_dir / "admin.sqlite3")
    legacy = resolve_path(os.environ.get("LEGACY_SQLITE_PATH") or old_env or storage.get("legacy_sqlite_path") or storage.get("sqlite_path"), selected if selected and selected.name == "storage.sqlite3" else data_dir / "storage.sqlite3")
    secrets = resolve_path(os.environ.get("BOT_SECRETS_FILE"), data_dir / "private/runtime.json")
    paths = [catalog, admin, legacy, secrets]
    for i, first in enumerate(paths):
        for second in paths[i + 1:]:
            if first == second or (first.exists() and second.exists() and os.path.samefile(first, second)):
                raise StorageError("Catalog, admin, legacy and secrets paths must be distinct")
    return data_dir, catalog, admin, legacy, secrets


DATA_DIR, CATALOG_SQLITE_PATH, ADMIN_SQLITE_PATH, LEGACY_SQLITE_PATH, SECRETS_PATH = discover_paths()
SQLITE_PATH = ADMIN_SQLITE_PATH


def connect():
    conn = sqlite3.connect(ADMIN_SQLITE_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("ATTACH DATABASE ? AS catalog", (str(CATALOG_SQLITE_PATH),))
        return conn
    except BaseException:
        conn.close()
        raise


def _tables(conn, schema):
    return {row[0] for row in conn.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _validate(conn):
    for schema, allowed in (("main", ADMIN_TABLES), ("catalog", CATALOG_TABLES)):
        extra = _tables(conn, schema) - allowed
        if extra:
            raise StorageError(f"Unexpected tables in {schema}: {sorted(extra)}; refusing to overwrite existing storage")
    versions = [conn.execute(f"PRAGMA {schema}.user_version").fetchone()[0] for schema in ("main", "catalog")]
    applications = [conn.execute(f"PRAGMA {schema}.application_id").fetchone()[0] for schema in ("main", "catalog")]
    if versions != [0, 0] or applications != [0, 0]:
        if not versions[0] or versions[0] != versions[1] or applications != [APPLICATION_ID, APPLICATION_ID]:
            raise StorageError("Storage migration markers disagree; restore both databases from the same snapshot")
        if _tables(conn, "main") != ADMIN_TABLES or _tables(conn, "catalog") != CATALOG_TABLES:
            raise StorageError("Storage schema is incomplete")
        row = conn.execute("SELECT value FROM documents WHERE key=?", (MIGRATION_KEY,)).fetchone()
        if not row or json.loads(row[0]).get("id") != versions[0]:
            raise StorageError("Storage migration marker is missing or inconsistent")
        return json.loads(row[0])
    for schema in ("main", "catalog"):
        for table in _tables(conn, schema):
            if conn.execute(f'SELECT 1 FROM {schema}."{table}" LIMIT 1').fetchone():
                raise StorageError("Unmarked target database contains data; refusing to import over it")
    return None


@contextmanager
def _migration_lock(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def initialize(import_legacy, prepare_config):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ADMIN_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _migration_lock(ADMIN_SQLITE_PATH.parent):
        with closing(connect()) as conn:
            marker = _validate(conn)
            if marker is not None:
                return marker
            for schema in ("main", "catalog"):
                mode = conn.execute(f"PRAGMA {schema}.journal_mode=DELETE").fetchone()[0]
                if mode != "delete":
                    raise StorageError("Atomic storage migration requires rollback journals")
                conn.execute(f"PRAGMA {schema}.synchronous=FULL")
            try:
                conn.execute("BEGIN IMMEDIATE")
                for statement in SCHEMA:
                    conn.execute(statement)
                with legacy_snapshot(LEGACY_SQLITE_PATH) as source:
                    import_legacy(conn, source)
                    prepare_config(conn, source)
                marker = {"id": uuid.uuid4().int % 2147483646 + 1, "legacy": str(LEGACY_SQLITE_PATH), "imported": LEGACY_SQLITE_PATH.exists()}
                conn.execute("INSERT INTO documents VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (MIGRATION_KEY, json.dumps(marker)))
                for schema in ("main", "catalog"):
                    conn.execute(f"PRAGMA {schema}.application_id={APPLICATION_ID}")
                    conn.execute(f"PRAGMA {schema}.user_version={marker['id']}")
                conn.commit()
                return marker
            except BaseException:
                conn.rollback()
                raise


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS documents (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""",
    """CREATE TABLE IF NOT EXISTS catalog.plugins_items (
                    sort_order INTEGER PRIMARY KEY,
                    slug TEXT,
                    status TEXT,
                    category TEXT,
                    updated_at TEXT,
                    published_at TEXT,
                    payload TEXT NOT NULL
                )""",
    """CREATE INDEX IF NOT EXISTS catalog.idx_plugins_slug ON plugins_items(slug)""",
    """CREATE INDEX IF NOT EXISTS catalog.idx_plugins_status ON plugins_items(status)""",
    """CREATE INDEX IF NOT EXISTS catalog.idx_plugins_category ON plugins_items(category)""",
    """CREATE TABLE IF NOT EXISTS catalog.icons_items (
                    sort_order INTEGER PRIMARY KEY,
                    slug TEXT,
                    status TEXT,
                    category TEXT,
                    updated_at TEXT,
                    published_at TEXT,
                    payload TEXT NOT NULL
                )""",
    """CREATE INDEX IF NOT EXISTS catalog.idx_icons_slug ON icons_items(slug)""",
    """CREATE INDEX IF NOT EXISTS catalog.idx_icons_status ON icons_items(status)""",
    """CREATE TABLE IF NOT EXISTS requests_items (
                    sort_order INTEGER PRIMARY KEY,
                    request_id TEXT,
                    status TEXT,
                    request_type TEXT,
                    submitted_at TEXT,
                    updated_at TEXT,
                    payload_user_id INTEGER,
                    payload TEXT NOT NULL
                )""",
    """CREATE INDEX IF NOT EXISTS idx_requests_id ON requests_items(request_id)""",
    """CREATE INDEX IF NOT EXISTS idx_requests_status ON requests_items(status)""",
    """CREATE INDEX IF NOT EXISTS idx_requests_type ON requests_items(request_type)""",
    """CREATE INDEX IF NOT EXISTS idx_requests_user ON requests_items(payload_user_id)""",
    """CREATE TABLE IF NOT EXISTS users_items (
                    user_id TEXT PRIMARY KEY,
                    language TEXT,
                    banned INTEGER,
                    ban_reason TEXT,
                    payload TEXT NOT NULL
                )""",
    """CREATE INDEX IF NOT EXISTS idx_users_language ON users_items(language)""",
    """CREATE INDEX IF NOT EXISTS idx_users_banned ON users_items(banned)""",
    """CREATE TABLE IF NOT EXISTS subscriptions_items (
                    user_id TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (user_id, slug)
                )""",
    """CREATE INDEX IF NOT EXISTS idx_subscriptions_slug ON subscriptions_items(slug)""",
    """CREATE TABLE IF NOT EXISTS updated_items (
                    sort_order INTEGER PRIMARY KEY,
                    link TEXT,
                    name TEXT,
                    added_at TEXT,
                    payload TEXT NOT NULL
                )""",
    """CREATE INDEX IF NOT EXISTS idx_updated_link ON updated_items(link)""",
    """CREATE TABLE IF NOT EXISTS joinly_items (
                    chat_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )""",
)
