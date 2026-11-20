import json
from unittest.mock import Mock

import pytest

from dy_mcp import browser_runtime


def wrapped(value):
    return json.dumps({"data": json.dumps(value)})


def material():
    fingerprint = {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/157.0.0.0",
        "platform": "MacIntel",
        "languages": ["zh-CN", "en-US"],
        "cpu": 10,
        "memory": 16,
        "screen": {"width": 1728, "height": 1117, "availWidth": 1728, "availHeight": 1005},
        "window": {"innerWidth": 1728, "innerHeight": 862, "outerWidth": 1728, "outerHeight": 1005},
        "webgl": {"vendor": "Apple", "renderer": "M1 Pro"},
    }
    credentials = {
        "web": wrapped({"ticket": "ticket", "ts_sign": "sign", "client_cert": "cert"}),
        "keys": wrapped({"ec_privateKey": "private"}),
        "dtrait": "blob",
    }
    return fingerprint, credentials


def test_build_runtime_uses_browser_material_and_proxy():
    fingerprint, credentials = material()

    env, info = browser_runtime.build_runtime(
        "sessionid=secret", fingerprint, credentials,
        {"browser_type": "webbridge", "proxy": "环境默认网络"},
    )

    assert env["DY_COOKIES"] == "sessionid=secret"
    assert env["DY_FP_OS_NAME"] == "macOS"
    assert env["DY_FP_BROWSER_VERSION"] == "157.0.0.0"
    assert env["DY_DTRAIT_BLOB"] == "blob"
    assert info["platform"] == "MacIntel"


@pytest.mark.parametrize("browser_type,collector_name", [
    ("webbridge", "collect_webbridge"),
    ("chrome", "collect_chromium"),
    ("edge", "collect_chromium"),
    ("firefox", "collect_firefox"),
    ("camoufox", "collect_camoufox"),
])
def test_local_browser_runtime_dispatch(monkeypatch, browser_type, collector_name):
    fingerprint, credentials = material()
    expected = ({"DY_COOKIES": "sessionid=test"}, {"browser_type": browser_type})
    collector = Mock(return_value=expected)
    monkeypatch.setattr(browser_runtime, collector_name, collector)
    account = {"id": "account", "browser_type": browser_type, "cdp_url": "ws://browser"}

    env, _info = browser_runtime.collect_runtime_for_account(account)

    assert env["DY_COOKIES"] == "sessionid=test"
    assert collector.call_count == 1


def test_bidi_evaluate_reads_string_result():
    client = Mock()
    client.call.return_value = {"type": "success", "result": {"type": "string", "value": '{"ok":true}'}}

    assert browser_runtime.bidi_evaluate(client, "context", "expression") == '{"ok":true}'


def test_local_profile_fingerprint_is_applied_before_runtime_collection(monkeypatch):
    expected = ({"DY_COOKIES": "sessionid=test"}, {"browser_type": "chrome"})
    collector = Mock(return_value=expected)
    profile = {"name": "local-one", "fingerprint": {"ua": "fixed"}}
    monkeypatch.setattr(browser_runtime, "collect_chromium", collector)
    monkeypatch.setattr(
        "dy_mcp.local_browser.LocalBrowserManager.find_by_cdp", lambda self, _url: profile,
    )
    account = {"id": "account", "browser_type": "chrome", "cdp_url": "http://127.0.0.1:9333"}

    _env, info = browser_runtime.collect_runtime_for_account(account)

    assert collector.call_args.kwargs["fingerprint"] == {"ua": "fixed"}
    assert info["local_profile"] == "local-one"


def test_camoufox_context_collects_main_world_credentials_and_cookies(monkeypatch):
    fingerprint, credentials = material()
    fingerprint["ua"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:158.0) Gecko/20100101 Firefox/158.0"
    context = Mock()
    page = context.new_page.return_value
    page.evaluate.side_effect = [json.dumps(credentials), json.dumps(fingerprint)]
    context.cookies.return_value = [{"name": "sessionid", "value": "secret", "domain": ".douyin.com"}]
    monkeypatch.setattr(browser_runtime.time, "sleep", lambda _seconds: None)

    env, info = browser_runtime.collect_camoufox_context(context)

    assert env["DY_COOKIES"] == "sessionid=secret"
    assert env["DY_FP_BROWSER_VERSION"] == "158.0"
    assert info["browser_type"] == "camoufox"
    assert page.evaluate.call_args_list[0].args[0].startswith("mw:")
    assert page.evaluate.call_args_list[1].args[0].startswith("mw:")
    page.close.assert_called_once()
