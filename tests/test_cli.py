import json
import subprocess
import sys
from unittest.mock import patch

from dy_mcp import cli


def test_cli_import_does_not_load_mcp_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from dy_mcp import cli; assert 'mcp.server.fastmcp' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_start_live_requires_explicit_confirmation(tmp_path, capsys):
    returncode = cli.main(["--db", str(tmp_path / "cli.db"), "start", "--live"])

    assert returncode == 2
    assert "--live --confirm" in capsys.readouterr().err


def test_start_configures_detached_live_scheduler(tmp_path, capsys):
    with patch.object(cli.SchedulerController, "configure", return_value={"running": True}) as configure:
        returncode = cli.main([
            "--db", str(tmp_path / "cli.db"), "start", "--live", "--confirm",
            "--global-per-hour", "12", "--min-interval-seconds", "400", "--poll-seconds", "20",
        ])

    assert returncode == 0
    configure.assert_called_once_with(
        "start", enabled=True, dry_run=False, confirm=True,
        global_per_hour=12, min_interval_seconds=400, poll_seconds=20,
    )
    assert json.loads(capsys.readouterr().out) == {"running": True}


def test_run_uses_foreground_scheduler_without_starting_daemon(tmp_path):
    with (
        patch.object(cli.SchedulerController, "configure", return_value={}) as configure,
        patch.object(cli, "run_scheduler") as run_scheduler,
    ):
        returncode = cli.main(["--db", str(tmp_path / "cli.db"), "run", "--dry-run"])

    assert returncode == 0
    configure.assert_called_once_with(
        "status", enabled=True, dry_run=True, confirm=False,
        global_per_hour=None, min_interval_seconds=None, poll_seconds=None,
    )
    run_scheduler.assert_called_once()


def test_status_uses_selected_database(tmp_path, capsys):
    database = tmp_path / "custom.db"

    with patch("dy_mcp.scheduler.PID_PATH", tmp_path / "scheduler.pid"):
        returncode = cli.main(["--db", str(database), "status"])

    assert returncode == 0
    result = json.loads(capsys.readouterr().out)
    assert result["database"] == str(database)
    assert result["settings"]["dry_run"] == "true"
    assert result["running"] is False


def test_once_defaults_to_preview(tmp_path):
    with patch.object(cli, "run_once", return_value={"status": "preview"}) as run_once:
        returncode = cli.main(["--db", str(tmp_path / "cli.db"), "once", "account-one"])

    assert returncode == 0
    run_once.assert_called_once()
    assert run_once.call_args.kwargs["dry_run"] is True
    assert run_once.call_args.kwargs["confirm"] is False


def test_activity_rejects_invalid_limit(tmp_path, capsys):
    returncode = cli.main(["--db", str(tmp_path / "cli.db"), "activity", "--limit", "201"])

    assert returncode == 2
    assert "1 到 200" in capsys.readouterr().err


def test_account_create_supports_image_only_configuration(tmp_path, capsys):
    returncode = cli.main([
        "--db", str(tmp_path / "cli.db"), "account", "create",
        "--account-id", "account-one", "--name", "测试账号",
        "--browser-type", "webbridge", "--keywords", "AI,Claude Code，vibecoding",
        "--comment-texts", "", "--image-paths", "/tmp/poster.png",
        "--per-hour-limit", "8", "--per-day-limit", "50", "--batch-size", "3",
    ])

    assert returncode == 0
    account = json.loads(capsys.readouterr().out)["account"]
    assert account["keywords"] == ["AI", "Claude Code", "vibecoding"]
    assert account["comment_texts"] == []
    assert account["image_paths"] == ["/tmp/poster.png"]
    assert account["per_hour_limit"] == 8
    assert account["per_day_limit"] == 50
    assert account["batch_size"] == 3


def test_account_set_only_changes_supplied_fields(tmp_path, capsys):
    store = cli.AccountStore(tmp_path / "cli.db")
    original = store.upsert_account(
        "测试账号", browser_type="webbridge", keywords=["旧关键词"],
        comment_texts=[], image_paths=["/tmp/poster.png"], per_day_limit=50,
    )

    returncode = cli.main([
        "--db", str(store.path), "account", "set", original["id"],
        "--keywords", "新关键词,Claude Code",
    ])

    assert returncode == 0
    account = json.loads(capsys.readouterr().out)["account"]
    assert account["keywords"] == ["新关键词", "Claude Code"]
    assert account["comment_texts"] == []
    assert account["image_paths"] == ["/tmp/poster.png"]
    assert account["per_day_limit"] == 50
    assert account["browser_type"] == "webbridge"


def test_once_forwards_keyword_and_aweme_id(tmp_path):
    completed = subprocess.CompletedProcess([], 0, stdout='{"status": "preview"}\n', stderr="")
    with patch.object(cli.subprocess, "run", return_value=completed) as run:
        returncode = cli.main([
            "--db", str(tmp_path / "cli.db"), "once", "account-one",
            "--keyword", "Claude Code", "--aweme-id", "12345",
        ])

    assert returncode == 0
    command = run.call_args.args[0]
    assert command[-4:] == ["--aweme-id", "12345", "--keyword", "Claude Code"]
    assert "--live" not in command


def test_engage_maps_search_comment_and_message_options(tmp_path):
    with (
        patch("dy_mcp.session.DouyinSession"),
        patch("dy_mcp.workflow.EngagementWorkflow") as workflow,
    ):
        workflow.return_value.run.return_value = {"status": "preview"}
        returncode = cli.main([
            "--db", str(tmp_path / "cli.db"), "engage", "Claude Code",
            "--comment-text", "测试评论", "--message-text", "测试私信",
            "--image-paths", "/tmp/poster.png", "--limit", "5",
            "--sort-type", "1", "--publish-time", "7", "--interval-seconds", "2.5",
        ])

    assert returncode == 0
    workflow.return_value.run.assert_called_once_with(
        "Claude Code", "测试评论", "测试私信", image_path="/tmp/poster.png",
        limit=5, dry_run=True, confirm=False, sort_type="1", publish_time="7",
        interval_seconds=2.5,
    )


def test_profiles_command_returns_adspower_profiles(tmp_path, capsys):
    expected = {"count": 1, "profiles": [{"profile_no": "11"}]}
    with patch.object(cli, "list_adspower_profiles", return_value=expected):
        returncode = cli.main(["--db", str(tmp_path / "cli.db"), "profiles"])

    assert returncode == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_config_updates_scheduler_without_starting_process(tmp_path):
    with patch.object(cli.SchedulerController, "configure", return_value={"running": False}) as configure:
        returncode = cli.main([
            "--db", str(tmp_path / "cli.db"), "config", "--dry-run", "--disable",
            "--global-per-hour", "15", "--min-interval-seconds", "600",
        ])

    assert returncode == 0
    configure.assert_called_once_with(
        "status", enabled=False, dry_run=True, confirm=False,
        global_per_hour=15, min_interval_seconds=600, poll_seconds=None,
    )


def test_browser_create_and_bind_existing_account(tmp_path, capsys):
    from dy_mcp.local_browser import LocalBrowserManager

    manager = LocalBrowserManager(tmp_path / "browsers")
    store = cli.AccountStore(tmp_path / "cli.db")
    account = store.upsert_account(
        "本地账号", browser_type="webbridge", keywords=["AI"],
        comment_texts=[], image_paths=["/tmp/poster.png"], per_day_limit=30,
    )
    with (
        patch.object(cli, "local_browser_manager", return_value=manager),
        patch("dy_mcp.local_browser.find_browser", return_value="/fake/chrome"),
        patch("dy_mcp.local_browser.browser_version", return_value="157.0.8103.79"),
    ):
        created = cli.main([
            "--db", str(store.path), "browser", "create", "local-one", "--port", "9333",
        ])
        capsys.readouterr()
        bound = cli.main([
            "--db", str(store.path), "browser", "bind", "local-one", account["id"],
        ])

    assert created == 0
    assert bound == 0
    result = json.loads(capsys.readouterr().out)
    saved = store.get_account(account["id"])
    assert result["local_profile"] == "local-one"
    assert saved["browser_type"] == "chrome"
    assert saved["cdp_url"] == "http://127.0.0.1:9333"
    assert saved["image_paths"] == ["/tmp/poster.png"]
    assert saved["per_day_limit"] == 30


def test_camoufox_create_and_bind_existing_account(tmp_path, capsys):
    from dy_mcp.camoufox_browser import CamoufoxManager
    from dy_mcp.local_browser import LocalBrowserManager

    local_manager = LocalBrowserManager(tmp_path / "chrome")
    camoufox_manager = CamoufoxManager(tmp_path / "camoufox")
    store = cli.AccountStore(tmp_path / "cli.db")
    account = store.upsert_account(
        "Firefox 账号", browser_type="webbridge", keywords=["AI"],
        comment_texts=[], image_paths=["/tmp/poster.png"], per_day_limit=40,
    )
    with (
        patch.object(cli, "local_browser_manager", return_value=local_manager),
        patch.object(cli, "camoufox_browser_manager", return_value=camoufox_manager),
    ):
        created = cli.main([
            "--db", str(store.path), "browser", "create", "firefox-one",
            "--engine", "camoufox", "--port", "9555", "--platform", "MacIntel",
            "--screen-width", "1920", "--screen-height", "1080",
            "--window-width", "1440", "--window-height", "900",
        ])
        output = capsys.readouterr().out
        bound = cli.main([
            "--db", str(store.path), "browser", "bind", "firefox-one", account["id"],
        ])

    assert created == 0
    assert bound == 0
    assert '"token"' not in output
    saved = store.get_account(account["id"])
    profile = camoufox_manager.get("firefox-one")
    assert saved["browser_type"] == "camoufox"
    assert saved["cdp_url"] == "http://127.0.0.1:9555"
    assert saved["image_paths"] == ["/tmp/poster.png"]
    assert saved["per_day_limit"] == 40
    assert profile["os"] == "macos"
    assert profile["fingerprint_config"] == {}


def test_camoufox_rejects_chrome_only_overrides(tmp_path, capsys):
    from dy_mcp.camoufox_browser import CamoufoxManager
    from dy_mcp.local_browser import LocalBrowserManager

    with (
        patch.object(cli, "local_browser_manager", return_value=LocalBrowserManager(tmp_path / "chrome")),
        patch.object(cli, "camoufox_browser_manager", return_value=CamoufoxManager(tmp_path / "camoufox")),
    ):
        returncode = cli.main([
            "--db", str(tmp_path / "cli.db"), "browser", "create", "firefox-one",
            "--engine", "camoufox", "--port", "9555", "--cpu", "8",
        ])

    assert returncode == 2
    assert "--cpu" in capsys.readouterr().err
