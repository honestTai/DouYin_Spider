import json
from unittest.mock import Mock

from dy_mcp.adspower import AdsPowerMCP


def test_cookie_header_accepts_json_string_and_filters_douyin():
    ads = AdsPowerMCP(api_key="test")
    ads.call = Mock(return_value={
        "cookies": json.dumps([
            {"name": "sessionid", "value": "secret", "domain": ".douyin.com"},
            {"name": "other", "value": "value", "domain": ".google.com"},
        ])
    })

    assert ads.cookie_header(profile_no="11") == "sessionid=secret"


def test_cookie_header_rejects_profile_without_douyin_login():
    ads = AdsPowerMCP(api_key="test")
    ads.call = Mock(return_value={"cookies": "[]"})

    try:
        ads.cookie_header(profile_no="11")
    except RuntimeError as error:
        assert "没有抖音 Cookie" in str(error)
    else:
        raise AssertionError("missing Douyin cookies should fail")
