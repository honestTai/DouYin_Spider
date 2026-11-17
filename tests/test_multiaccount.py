import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from dy_mcp.engine import MultiAccountEngine
from dy_mcp.store import AccountStore


def work(aweme_id, digg, comments):
    return {
        "aweme_info": {
            "aweme_id": aweme_id,
            "desc": f"作品 {aweme_id}",
            "author": {"uid": "100", "nickname": "作者"},
            "statistics": {"digg_count": digg, "comment_count": comments},
        }
    }


def runtime_loader(_account):
    return {"DY_COOKIES": "sessionid=test"}, {"profile_id": "profile-one"}


def make_account(store, name="账号一", profile_id="profile-one", **overrides):
    values = {
        "keywords": ["Claude"],
        "comment_texts": ["测试评论"],
        "min_digg_count": 1000,
        "max_comment_count": 100,
    }
    values.update(overrides)
    return store.upsert_account(name, profile_id, **values)


def make_engine(store, api):
    auth = Mock()
    for account in store.list_accounts():
        store.save_runtime(
            account["id"], {"DY_COOKIES": "sessionid=test"}, {"profile_id": "profile-one"},
        )
    return MultiAccountEngine(
        store, runtime_loader=runtime_loader, api=api,
        auth_factory=lambda *_args, **_kwargs: auth,
    )


def test_preview_ranks_high_digg_low_comment_without_publishing(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    account = make_account(store)
    api = Mock()
    api.search_some_general_work.return_value = [
        work("low-ratio", 10000, 100),
        work("best", 9000, 1),
        work("too-small", 500, 0),
        work("too-many-comments", 100000, 1000),
    ]
    engine = make_engine(store, api)

    result = engine.run(account["id"])

    assert result["status"] == "preview"
    assert [item["aweme_id"] for item in result["works"]] == ["best", "low-ratio"]
    api.publish_comment.assert_not_called()
    assert store.get_run(result["run_id"])["status"] == "preview"


def test_accounts_independently_comment_same_work_without_self_duplicates(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    first = make_account(store)
    second = make_account(store, "账号二", "profile-two")
    api = Mock()
    api.search_some_general_work.return_value = [work("only-one", 9000, 1)]
    api.publish_comment.return_value = {"status_code": 0}
    engine = make_engine(store, api)

    first_result = engine.run(first["id"], dry_run=False, confirm=True)
    second_result = engine.run(second["id"], dry_run=False, confirm=True)
    duplicate = engine.run(first["id"], dry_run=False, confirm=True)

    assert first_result["status"] == "completed"
    assert second_result["status"] == "completed"
    assert duplicate["status"] == "no_candidates"
    assert store.work_status("only-one", first["id"]) == "published"
    assert store.work_status("only-one", second["id"]) == "published"
    assert store.count_published(first["id"], hours=1) == 1
    assert store.count_published(second["id"], hours=1) == 1
    assert api.publish_comment.call_count == 2


def test_verification_error_pauses_account_for_scheduler(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    account = make_account(store)
    api = Mock()
    api.search_some_general_work.return_value = [work("risk", 9000, 1)]
    api.publish_comment.side_effect = RuntimeError("需要二次身份验证（scene=comment）")
    engine = make_engine(store, api)

    result = engine.run(account["id"], dry_run=False, confirm=True)
    selected, _reason = store.next_account(min_interval_seconds=0)

    assert result["status"] == "failed"
    assert result["account_status"] == "verification_required"
    assert store.work_status("risk") == ""
    assert selected is None


def test_scheduler_rotates_accounts_and_enforces_account_hour_limit(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    first = make_account(store, per_hour_limit=1)
    second = make_account(store, "账号二", "profile-two")
    run_id = store.create_run(first["id"], "Claude", "测试评论", False)
    store.reserve_work("done", first["id"], run_id, 1000, 1)
    store.publish_work("done")
    store.finish_run(run_id, "completed", selected_id="done")

    selected, _reason = store.next_account(global_per_hour=20, min_interval_seconds=0)
    accounts = store.list_accounts()

    assert selected["id"] == second["id"]
    assert accounts[0]["comments_last_hour"] == 1
    assert store.count_published(hours=1) == 1


def test_store_defaults_keep_scheduler_in_dry_run(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")

    settings = store.settings()

    assert settings["enabled"] == "false"
    assert settings["dry_run"] == "true"
    assert settings["global_per_hour"] == "20"
    assert settings["min_interval_seconds"] == "180"


def test_targeted_comment_skips_search(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    account = make_account(store)
    api = Mock()
    api.publish_comment.return_value = {"status_code": 0}
    engine = make_engine(store, api)

    result = engine.run(
        account["id"], dry_run=False, confirm=True, aweme_id="direct-work",
    )

    assert result["status"] == "completed"
    assert result["work"]["aweme_id"] == "direct-work"
    api.search_some_general_work.assert_not_called()
    api.publish_comment.assert_called_once()


def test_legacy_global_engagements_migrate_to_account_scope(tmp_path):
    path = tmp_path / "accounts.db"
    store = AccountStore(path)
    account = make_account(store)
    run_id = store.create_run(account["id"], "Claude", "测试评论", False)
    store.reserve_work("shared-work", account["id"], run_id, 1000, 1)
    store.publish_work("shared-work", account["id"])
    store.finish_run(run_id, "completed", selected_id="shared-work")
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            ALTER TABLE engagements RENAME TO engagements_current;
            CREATE TABLE engagements (
                aweme_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                status TEXT NOT NULL,
                digg_count INTEGER NOT NULL,
                comment_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO engagements SELECT * FROM engagements_current;
            DROP TABLE engagements_current;
            """
        )

    migrated = AccountStore(path)

    assert migrated.work_status("shared-work", account["id"]) == "published"
    with migrated.connect() as db:
        primary_key = {row[1]: row[5] for row in db.execute("PRAGMA table_info(engagements)") if row[5]}
        assert primary_key == {"aweme_id": 2, "account_id": 1}
        assert list(db.execute("PRAGMA foreign_key_check")) == []


def test_latest_strategy_searches_last_day_and_keeps_newest_order(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    account = make_account(store, content_strategy="latest")
    api = Mock()
    api.search_some_general_work.return_value = [
        work("newest", 2000, 50),
        work("older-higher-score", 9000, 1),
    ]
    engine = make_engine(store, api)

    result = engine.run(account["id"])

    assert result["status"] == "preview"
    assert result["content_strategy"] == "latest"
    assert result["publish_time"] == "1"
    assert [item["aweme_id"] for item in result["works"]] == [
        "newest", "older-higher-score",
    ]
    api.search_some_general_work.assert_called_once()
    assert api.search_some_general_work.call_args.args[3:] == ("2", "1")


def test_latest_strategy_falls_back_to_engagement_when_empty(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    account = make_account(store, content_strategy="latest")
    api = Mock()
    api.search_some_general_work.side_effect = [[], [work("fallback", 9000, 1)]]
    engine = make_engine(store, api)

    result = engine.run(account["id"])

    assert result["status"] == "preview"
    assert result["content_strategy"] == "engagement"
    assert result["publish_time"] == "0"
    assert result["works"][0]["aweme_id"] == "fallback"
    assert api.search_some_general_work.call_count == 2
    assert result["searched_keywords"] == [
        {"keyword": "Claude", "strategy": "latest"},
        {"keyword": "Claude", "strategy": "engagement"},
    ]


def test_batch_publishes_distinct_works_within_quota(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    account = make_account(
        store, batch_size=3, batch_interval_seconds=15,
        per_hour_limit=10, per_day_limit=25,
    )
    api = Mock()
    api.search_some_general_work.return_value = [
        work("batch-one", 9000, 1),
        work("batch-two", 8000, 2),
        work("batch-three", 7000, 3),
        work("batch-four", 6000, 4),
    ]
    api.publish_comment.return_value = {"status_code": 0}
    engine = make_engine(store, api)

    with patch("dy_mcp.engine.time.sleep") as sleep:
        result = engine.run(account["id"], dry_run=False, confirm=True)

    assert result["status"] == "completed"
    assert result["completed_count"] == 3
    assert result["failed_count"] == 0
    assert [item["aweme_id"] for item in result["works"]] == [
        "batch-one", "batch-two", "batch-three",
    ]
    assert store.get_run(result["run_id"])["selected_ids"] == [
        "batch-one", "batch-two", "batch-three",
    ]
    assert store.count_published(account["id"], hours=1) == 3
    assert api.publish_comment.call_count == 3
    assert sleep.call_args_list == [((15,),), ((15,),)]


@pytest.mark.parametrize("quota_kind", ["hour", "day"])
def test_batch_respects_remaining_global_hour_and_daily_quotas(tmp_path, quota_kind):
    store = AccountStore(tmp_path / "accounts.db")
    account = make_account(
        store, batch_size=3, per_hour_limit=10, per_day_limit=25,
    )
    store.update_settings(global_per_hour=10)
    existing_count = 9 if quota_kind == "hour" else 24
    for index in range(existing_count):
        run_id = store.create_run(account["id"], "Claude", "测试评论", False)
        store.reserve_work(f"existing-{index}", account["id"], run_id, 1000, 1)
        store.publish_work(f"existing-{index}", account["id"])
        store.finish_run(run_id, "completed", selected_id=f"existing-{index}")
    if quota_kind == "day":
        two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with store.connect() as db:
            db.execute("UPDATE engagements SET created_at=?", (two_hours_ago,))
    api = Mock()
    api.search_some_general_work.return_value = [
        work("quota-one", 9000, 1),
        work("quota-two", 8000, 2),
        work("quota-three", 7000, 3),
    ]
    api.publish_comment.return_value = {"status_code": 0}
    engine = make_engine(store, api)

    result = engine.run(account["id"], dry_run=False, confirm=True)

    assert result["status"] == "completed"
    assert result["completed_count"] == 1
    assert result["work"]["aweme_id"] == "quota-one"
    assert api.publish_comment.call_count == 1
    assert store.count_published(account["id"], hours=24) == existing_count + 1


def test_saved_runtime_is_reused_without_calling_browser_or_exposing_secrets(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    account = make_account(store)
    saved_at = store.save_runtime(
        account["id"],
        {"DY_COOKIES": "sessionid=secret", "DY_TICKET": "private-ticket"},
        {"browser_type": "webbridge"},
    )
    loader = Mock(side_effect=AssertionError("不应访问浏览器"))
    api = Mock()
    api.search_some_general_work.return_value = [work("saved-runtime", 9000, 1)]
    auth = Mock()
    engine = MultiAccountEngine(
        store, runtime_loader=loader, api=api,
        auth_factory=lambda *_args, **_kwargs: auth,
    )

    result = engine.run(account["id"])
    public_account = store.list_accounts()[0]

    assert result["status"] == "preview"
    assert result["profile"]["credential_source"] == "saved"
    assert result["profile"]["runtime_saved_at"] == saved_at
    assert public_account["runtime_status"] == "saved"
    assert public_account["runtime_saved_at"] == saved_at
    assert "secret" not in str(public_account)
    assert "private-ticket" not in str(result)
    loader.assert_not_called()


def test_missing_saved_runtime_reports_rebind_and_skips_scheduler(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    account = make_account(store)
    loader = Mock()
    engine = MultiAccountEngine(
        store, runtime_loader=loader, api=Mock(),
        auth_factory=lambda *_args, **_kwargs: Mock(),
    )

    result = engine.run(account["id"])
    selected, _reason = store.next_account(min_interval_seconds=0)

    assert result["status"] == "failed"
    assert result["account_status"] == "authentication_required"
    assert "refresh_account_runtime" in result["error"]
    assert store.get_account(account["id"])["status"] == "authentication_required"
    assert selected is None
    loader.assert_not_called()


def test_hashtag_strategy_keeps_top_five_ranking_without_engagement_filters(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    account = make_account(
        store, keywords=["ai", "ai知识", "vibecoding大赏"],
        content_strategy="hashtag", candidate_pool_size=5, batch_size=5,
        min_digg_count=1000000, max_comment_count=0,
    )
    api = Mock()
    api.search_some_general_work.return_value = [
        work(f"rank-{index}", 0, 100000) for index in range(1, 7)
    ]
    engine = make_engine(store, api)

    result = engine.run(account["id"])

    assert result["status"] == "preview"
    assert result["content_strategy"] == "hashtag"
    assert result["publish_time"] == "0"
    assert [item["aweme_id"] for item in result["works"]] == [
        "rank-1", "rank-2", "rank-3", "rank-4", "rank-5",
    ]
    assert result["planned_count"] == 5
    assert result["searched_keywords"] == [{"keyword": "ai", "strategy": "hashtag"}]
    api.search_some_general_work.assert_called_once()
    assert api.search_some_general_work.call_args.args[1:] == ("#ai", 5, "0", "0")


def test_keyword_override_only_affects_current_search(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    account = make_account(store, keywords=["默认关键词"])
    api = Mock()
    api.search_some_general_work.return_value = [work("custom", 9000, 1)]
    engine = make_engine(store, api)

    result = engine.run(account["id"], keyword="临时关键词")

    assert result["status"] == "preview"
    assert result["keyword"] == "临时关键词"
    assert api.search_some_general_work.call_args.args[1] == "临时关键词"
    assert store.get_account(account["id"])["keywords"] == ["默认关键词"]
