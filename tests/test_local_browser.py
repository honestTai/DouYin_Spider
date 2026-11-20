import json
from unittest.mock import Mock, patch

import pytest

from dy_mcp.local_browser import LocalBrowserManager, apply_fingerprint, fingerprint_script


def make_manager(tmp_path):
    manager = LocalBrowserManager(tmp_path / "browsers")
    with (
        patch("dy_mcp.local_browser.find_browser", return_value="/fake/chrome"),
        patch("dy_mcp.local_browser.browser_version", return_value="157.0.8103.79"),
    ):
        manager.create("account1", 9333)
    return manager


def test_profile_persists_fixed_fingerprint_and_isolated_command(tmp_path):
    manager = make_manager(tmp_path)

    first = manager.get("account1")
    second = manager.get("account1")
    command = manager.command(first)

    assert first["fingerprint"] == second["fingerprint"]
    assert "Chrome/157.0.8103.79" in first["fingerprint"]["ua"]
    assert first["user_data_dir"].endswith("account1/userdata")
    assert f"--user-data-dir={first['user_data_dir']}" in command
    assert "--remote-debugging-port=9333" in command
    assert "--load-extension=" in " ".join(command)
    assert manager.find_by_cdp("http://127.0.0.1:9333")["name"] == "account1"


def test_profiles_reject_duplicate_names_and_ports(tmp_path):
    manager = make_manager(tmp_path)

    with pytest.raises(ValueError, match="已存在"):
        manager.create("account1", 9444, executable="/fake/chrome")
    with pytest.raises(ValueError, match="已被环境"):
        manager.create("account2", 9333, executable="/fake/chrome")


def test_proxy_credentials_are_not_exposed_in_public_status(tmp_path):
    manager = LocalBrowserManager(tmp_path / "browsers")
    with patch("dy_mcp.local_browser.find_browser", return_value="/fake/chrome"):
        profile = manager.create(
            "account1", 9333, executable="/fake/chrome",
            proxy_url="http://user:password@proxy.example:8080",
            fingerprint={"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"},
        )

    public = manager.public(profile)
    command = manager.command(profile)
    manifest = json.loads((manager.profile_dir("account1") / "extension/manifest.json").read_text())

    assert public["proxy_url"] == "http://***:***@proxy.example:8080"
    assert "user:password" not in json.dumps(public)
    assert "--proxy-server=http://proxy.example:8080" in command
    assert "proxy" in manifest["permissions"]
    assert (manager.profile_dir("account1") / "extension/proxy.js").is_file()


def test_fingerprint_script_overrides_collected_fields(tmp_path):
    fingerprint = make_manager(tmp_path).get("account1")["fingerprint"]
    fingerprint["cpu"] = 6
    fingerprint["webgl"]["renderer"] = "Test Renderer"

    script = fingerprint_script(fingerprint)

    assert "hardwareConcurrency" in script
    assert "Test Renderer" in script
    assert "userAgentData" in script
    assert "document_start" not in script


def test_apply_fingerprint_preloads_script_and_cdp_overrides():
    client = Mock()
    fingerprint = {
        "ua": "Mozilla/5.0 Chrome/157.0.0.0",
        "platform": "MacIntel",
        "languages": ["zh-CN", "zh"],
        "cpu": 8,
        "memory": 8,
        "screen": {"width": 1920, "height": 1080},
        "window": {"innerWidth": 1440, "innerHeight": 900},
        "webgl": {"vendor": "Apple", "renderer": "M1"},
        "timezone": "Asia/Shanghai",
    }

    apply_fingerprint(client, "session", fingerprint)

    methods = [call.args[0] for call in client.call.call_args_list]
    assert methods == [
        "Emulation.setUserAgentOverride", "Emulation.setLocaleOverride",
        "Emulation.setTimezoneOverride", "Emulation.setDeviceMetricsOverride",
        "Page.enable", "Page.addScriptToEvaluateOnNewDocument",
    ]
    assert all(call.args[2] == "session" for call in client.call.call_args_list)


def test_daemon_applies_current_document_before_resuming_page(tmp_path):
    from dy_mcp.local_browser import FingerprintDaemon

    daemon = FingerprintDaemon.__new__(FingerprintDaemon)
    daemon.sessions = set()
    daemon.fingerprint = make_manager(tmp_path).get("account1")["fingerprint"]
    daemon.proxy_url = ""
    daemon.call = Mock()
    with patch("dy_mcp.local_browser.apply_fingerprint") as apply:
        daemon.attach("session", {"type": "page"})

    apply.assert_called_once()
    methods = [call.args[0] for call in daemon.call.call_args_list]
    assert methods == ["Runtime.evaluate", "Runtime.runIfWaitingForDebugger"]
