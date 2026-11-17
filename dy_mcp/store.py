import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / ".kimi-code" / "douyin.db"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_json(value):
    return json.loads(value)


class AccountStore:
    def __init__(self, path=DEFAULT_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    profile_id TEXT UNIQUE,
                    profile_no TEXT UNIQUE,
                    browser_type TEXT NOT NULL DEFAULT 'adspower',
                    cdp_url TEXT,
                    proxy_url TEXT,
                    keywords TEXT NOT NULL,
                    comment_texts TEXT NOT NULL,
                    image_paths TEXT NOT NULL DEFAULT '[]',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'active',
                    per_hour_limit INTEGER NOT NULL DEFAULT 5,
                    per_day_limit INTEGER NOT NULL DEFAULT 20,
                    min_digg_count INTEGER NOT NULL DEFAULT 100,
                    max_comment_count INTEGER NOT NULL DEFAULT 100,
                    candidate_pool_size INTEGER NOT NULL DEFAULT 20,
                    content_strategy TEXT NOT NULL DEFAULT 'engagement',
                    batch_size INTEGER NOT NULL DEFAULT 1,
                    batch_interval_seconds INTEGER NOT NULL DEFAULT 15,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    keyword TEXT NOT NULL,
                    comment_text TEXT NOT NULL,
                    dry_run INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    selected_id TEXT,
                    selected_ids TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_runs_account_time
                    ON runs(account_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_runs_time ON runs(started_at);
                CREATE TABLE IF NOT EXISTS engagements (
                    aweme_id TEXT NOT NULL,
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    status TEXT NOT NULL,
                    digg_count INTEGER NOT NULL DEFAULT 0,
                    comment_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, aweme_id)
                );
                CREATE INDEX IF NOT EXISTS idx_engagements_account_time
                    ON engagements(account_id, created_at);
                CREATE TABLE IF NOT EXISTS account_runtime (
                    account_id TEXT PRIMARY KEY REFERENCES accounts(id),
                    runtime_env TEXT NOT NULL,
                    runtime_info TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            engagement_pk = {
                row[1]: row[5] for row in db.execute("PRAGMA table_info(engagements)")
            }
            if engagement_pk.get("aweme_id") == 1 and not engagement_pk.get("account_id"):
                db.executescript(
                    """
                    PRAGMA foreign_keys=OFF;
                    DROP TABLE IF EXISTS engagements_account;
                    CREATE TABLE engagements_account (
                        aweme_id TEXT NOT NULL,
                        account_id TEXT NOT NULL REFERENCES accounts(id),
                        run_id TEXT NOT NULL REFERENCES runs(id),
                        status TEXT NOT NULL,
                        digg_count INTEGER NOT NULL DEFAULT 0,
                        comment_count INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (account_id, aweme_id)
                    );
                    INSERT OR IGNORE INTO engagements_account
                        SELECT aweme_id, account_id, run_id, status,
                               digg_count, comment_count, created_at
                        FROM engagements;
                    DROP TABLE engagements;
                    ALTER TABLE engagements_account RENAME TO engagements;
                    CREATE INDEX idx_engagements_account_time
                        ON engagements(account_id, created_at);
                    PRAGMA foreign_keys=ON;
                    """
                )
            columns = {row[1] for row in db.execute("PRAGMA table_info(accounts)")}
            for name, definition in (
                ("browser_type", "TEXT NOT NULL DEFAULT 'adspower'"),
                ("cdp_url", "TEXT"),
                ("proxy_url", "TEXT"),
                ("image_paths", "TEXT NOT NULL DEFAULT '[]'"),
                ("content_strategy", "TEXT NOT NULL DEFAULT 'engagement'"),
                ("batch_size", "INTEGER NOT NULL DEFAULT 1"),
                ("batch_interval_seconds", "INTEGER NOT NULL DEFAULT 15"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE accounts ADD COLUMN {name} {definition}")
            run_columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
            if "selected_ids" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN selected_ids TEXT NOT NULL DEFAULT '[]'")
            defaults = {
                "enabled": "false",
                "dry_run": "true",
                "global_per_hour": "20",
                "min_interval_seconds": "180",
                "poll_seconds": "15",
            }
            for key, value in defaults.items():
                db.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                    (key, value),
                )

    @staticmethod
    def _account(row):
        if row is None:
            return None
        item = dict(row)
        item["keywords"] = parse_json(item["keywords"])
        item["comment_texts"] = parse_json(item["comment_texts"])
        item["image_paths"] = parse_json(item.get("image_paths") or "[]")
        item["enabled"] = bool(item["enabled"])
        return item

    def upsert_account(self, name, profile_id="", profile_no="", *, account_id="",
                       browser_type="adspower", cdp_url="", proxy_url="",
                       keywords=None, comment_texts=None, image_paths=None, enabled=True,
                       per_hour_limit=5, per_day_limit=20, min_digg_count=100,
                       max_comment_count=100, candidate_pool_size=20,
                       content_strategy="engagement", batch_size=1, batch_interval_seconds=15):
        name = str(name or "").strip()
        profile_id = str(profile_id or "").strip()
        profile_no = str(profile_no or "").strip()
        browser_type = str(browser_type or "adspower").strip().lower()
        cdp_url = str(cdp_url or "").strip()
        proxy_url = str(proxy_url or "").strip()
        content_strategy = str(content_strategy or "engagement").strip().lower()
        keywords = [str(item).strip() for item in (keywords or []) if str(item).strip()]
        comment_texts = [str(item).strip() for item in (comment_texts or []) if str(item).strip()]
        image_paths = [str(item).strip() for item in (image_paths or []) if str(item).strip()]
        if not name:
            raise ValueError("账号名称不能为空")
        if browser_type not in {"adspower", "webbridge", "chrome", "edge", "firefox"}:
            raise ValueError("browser_type 只支持 adspower、webbridge、chrome、edge、firefox")
        if browser_type == "adspower" and not profile_id and not profile_no:
            raise ValueError("AdsPower 账号必须配置 profile_id 或 profile_no")
        if browser_type in {"chrome", "edge", "firefox"} and not cdp_url:
            raise ValueError("本地浏览器账号必须配置 cdp_url；Firefox 使用 BiDi WebSocket 地址")
        if content_strategy not in {"engagement", "latest", "hashtag"}:
            raise ValueError("content_strategy 只支持 engagement、latest 或 hashtag")
        if not 1 <= batch_size <= 10:
            raise ValueError("batch_size 必须在 1 到 10 之间")
        if not 0 <= batch_interval_seconds <= 300:
            raise ValueError("batch_interval_seconds 必须在 0 到 300 之间")
        if not keywords:
            raise ValueError("至少配置一个搜索关键词")
        if not comment_texts and not image_paths:
            raise ValueError("至少配置一条评论内容或一条图片路径")
        if not 1 <= per_hour_limit <= 100 or not 1 <= per_day_limit <= 1000:
            raise ValueError("账号限额超出范围")
        if not 0 <= min_digg_count or not 0 <= max_comment_count:
            raise ValueError("点赞和评论筛选值不能为负数")
        if not 1 <= candidate_pool_size <= 50:
            raise ValueError("candidate_pool_size 必须在 1 到 50 之间")
        now = utc_now()
        account_id = account_id or uuid.uuid4().hex[:12]
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO accounts(
                    id, name, profile_id, profile_no, browser_type, cdp_url, proxy_url,
                    keywords, comment_texts, image_paths, enabled, per_hour_limit, per_day_limit,
                    min_digg_count, max_comment_count, candidate_pool_size, content_strategy,
                    batch_size, batch_interval_seconds, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, profile_id=excluded.profile_id,
                    profile_no=excluded.profile_no, browser_type=excluded.browser_type,
                    cdp_url=excluded.cdp_url, proxy_url=excluded.proxy_url,
                    keywords=excluded.keywords, comment_texts=excluded.comment_texts,
                    image_paths=excluded.image_paths, enabled=excluded.enabled,
                    per_hour_limit=excluded.per_hour_limit,
                    per_day_limit=excluded.per_day_limit,
                    min_digg_count=excluded.min_digg_count,
                    max_comment_count=excluded.max_comment_count,
                    candidate_pool_size=excluded.candidate_pool_size,
                    content_strategy=excluded.content_strategy,
                    batch_size=excluded.batch_size,
                    batch_interval_seconds=excluded.batch_interval_seconds,
                    status='active', last_error=NULL, updated_at=excluded.updated_at
                """,
                (
                    account_id, name, profile_id or None, profile_no or None,
                    browser_type, cdp_url or None, proxy_url or None,
                    json.dumps(keywords, ensure_ascii=False),
                    json.dumps(comment_texts, ensure_ascii=False),
                    json.dumps(image_paths, ensure_ascii=False), int(enabled),
                    per_hour_limit, per_day_limit, min_digg_count,
                    max_comment_count, candidate_pool_size, content_strategy,
                    batch_size, batch_interval_seconds, now, now,
                ),
            )
        return self.get_account(account_id)

    def get_account(self, account_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        return self._account(row)

    def save_runtime(self, account_id, runtime_env, runtime_info):
        now = utc_now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO account_runtime(account_id, runtime_env, runtime_info, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET "
                "runtime_env=excluded.runtime_env, runtime_info=excluded.runtime_info, "
                "updated_at=excluded.updated_at",
                (account_id, json.dumps(runtime_env), json.dumps(runtime_info, ensure_ascii=False), now),
            )
        return now

    def get_runtime(self, account_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT runtime_env, runtime_info, updated_at FROM account_runtime WHERE account_id=?",
                (account_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "env": parse_json(row["runtime_env"]),
            "info": parse_json(row["runtime_info"]),
            "saved_at": row["updated_at"],
        }

    def list_accounts(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM accounts ORDER BY name").fetchall()
            accounts = [self._account(row) for row in rows]
            for account in accounts:
                runtime = db.execute(
                    "SELECT updated_at FROM account_runtime WHERE account_id=?", (account["id"],),
                ).fetchone()
                account["runtime_status"] = "saved" if runtime else "missing"
                account["runtime_saved_at"] = runtime["updated_at"] if runtime else None
                account["comments_last_hour"] = self._count_published(
                    db, account["id"], self._cutoff(timedelta(hours=1)),
                )
                account["comments_today"] = self._count_published(
                    db, account["id"], self._cutoff(timedelta(days=1)),
                )
                last = db.execute(
                    "SELECT status, started_at, finished_at, error FROM runs "
                    "WHERE account_id=? ORDER BY started_at DESC LIMIT 1",
                    (account["id"],),
                ).fetchone()
                account["last_run"] = dict(last) if last else None
        return accounts

    def set_account_status(self, account_id, status, error=None):
        with self.connect() as db:
            db.execute(
                "UPDATE accounts SET status=?, last_error=?, updated_at=? WHERE id=?",
                (status, error, utc_now(), account_id),
            )

    def create_run(self, account_id, keyword, comment_text, dry_run):
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs(id, account_id, keyword, comment_text, dry_run, status, started_at) "
                "VALUES (?, ?, ?, ?, ?, 'running', ?)",
                (run_id, account_id, keyword, comment_text, int(dry_run), utc_now()),
            )
        return run_id

    def update_run_keyword(self, run_id, keyword):
        with self.connect() as db:
            db.execute("UPDATE runs SET keyword=? WHERE id=?", (keyword, run_id))

    def finish_run(self, run_id, status, *, candidate_count=0, selected_id="",
                   selected_ids=None, error=None):
        selected_ids = selected_ids if selected_ids is not None else ([selected_id] if selected_id else [])
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET status=?, candidate_count=?, selected_id=?, selected_ids=?, "
                "error=?, finished_at=? WHERE id=?",
                (status, candidate_count, selected_id or None,
                 json.dumps(selected_ids, ensure_ascii=False), error, utc_now(), run_id),
            )

    @staticmethod
    def _run(row):
        if row is None:
            return None
        item = dict(row)
        item["selected_ids"] = parse_json(item.get("selected_ids") or "[]")
        return item

    def get_run(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return self._run(row)

    def recent_runs(self, limit=50, account_id=""):
        with self.connect() as db:
            if account_id:
                rows = db.execute(
                    "SELECT * FROM runs WHERE account_id=? ORDER BY started_at DESC LIMIT ?",
                    (account_id, limit),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._run(row) for row in rows]

    @staticmethod
    def _cutoff(delta):
        return (datetime.now(timezone.utc) - delta).isoformat()

    @staticmethod
    def _count_published(db, account_id, since):
        if account_id:
            return db.execute(
                "SELECT COUNT(*) FROM engagements WHERE account_id=? AND status='published' AND created_at>=?",
                (account_id, since),
            ).fetchone()[0]
        return db.execute(
            "SELECT COUNT(*) FROM engagements WHERE status='published' AND created_at>=?",
            (since,),
        ).fetchone()[0]

    def count_published(self, account_id="", *, hours=1):
        since = self._cutoff(timedelta(hours=hours))
        with self.connect() as db:
            return self._count_published(db, account_id, since)

    def last_run_at(self):
        with self.connect() as db:
            row = db.execute("SELECT MAX(started_at) FROM runs WHERE status != 'running'").fetchone()
        return row[0] or ""

    def reserve_work(self, aweme_id, account_id, run_id, digg_count, comment_count):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO engagements(aweme_id, account_id, run_id, status, "
                "digg_count, comment_count, created_at) VALUES (?, ?, ?, 'pending', ?, ?, ?)",
                (aweme_id, account_id, run_id, digg_count, comment_count, utc_now()),
            )
            return cursor.rowcount == 1

    def release_work(self, aweme_id, account_id=""):
        with self.connect() as db:
            if account_id:
                db.execute(
                    "DELETE FROM engagements WHERE aweme_id=? AND account_id=? AND status='pending'",
                    (aweme_id, account_id),
                )
            else:
                db.execute("DELETE FROM engagements WHERE aweme_id=? AND status='pending'", (aweme_id,))

    def publish_work(self, aweme_id, account_id=""):
        with self.connect() as db:
            if account_id:
                db.execute(
                    "UPDATE engagements SET status='published', created_at=? "
                    "WHERE aweme_id=? AND account_id=?",
                    (utc_now(), aweme_id, account_id),
                )
            else:
                db.execute(
                    "UPDATE engagements SET status='published', created_at=? WHERE aweme_id=?",
                    (utc_now(), aweme_id),
                )

    def work_status(self, aweme_id, account_id=""):
        with self.connect() as db:
            if account_id:
                row = db.execute(
                    "SELECT status FROM engagements WHERE aweme_id=? AND account_id=?",
                    (aweme_id, account_id),
                ).fetchone()
            else:
                row = db.execute("SELECT status FROM engagements WHERE aweme_id=?", (aweme_id,)).fetchone()
        return row[0] if row else ""

    def next_account(self, global_per_hour=20, min_interval_seconds=180):
        if self.count_published(hours=1) >= global_per_hour:
            return None, "已达到全局每小时限额"
        last_run = self.last_run_at()
        if last_run:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last_run)).total_seconds()
            if elapsed < min_interval_seconds:
                return None, "尚未达到全局最小执行间隔"
        with self.connect() as db:
            rows = db.execute(
                "SELECT a.*, MAX(r.started_at) AS last_attempt "
                "FROM accounts a LEFT JOIN runs r ON a.id=r.account_id "
                "WHERE a.enabled=1 AND a.status='active' "
                "GROUP BY a.id ORDER BY last_attempt IS NOT NULL, last_attempt ASC"
            ).fetchall()
            for row in rows:
                account = self._account(row)
                running = db.execute(
                    "SELECT 1 FROM runs WHERE account_id=? AND status='running'",
                    (account["id"],),
                ).fetchone()
                if running:
                    continue
                hour = self._count_published(db, account["id"], self._cutoff(timedelta(hours=1)))
                day = self._count_published(db, account["id"], self._cutoff(timedelta(days=1)))
                if hour >= account["per_hour_limit"] or day >= account["per_day_limit"]:
                    continue
                return account, ""
        return None, "没有可执行的账号"

    def settings(self):
        with self.connect() as db:
            rows = db.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def update_settings(self, **values):
        with self.connect() as db:
            for key, value in values.items():
                if value is None:
                    continue
                if isinstance(value, bool):
                    value = "true" if value else "false"
                db.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value)),
                )
        return self.settings()
