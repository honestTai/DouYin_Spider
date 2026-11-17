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
