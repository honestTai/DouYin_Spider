import pytest

from dy_mcp.proxy_pool import ProxyPool


def test_proxy_pool_assigns_one_stable_proxy_per_session():
    pool = ProxyPool('["http://user:pass@proxy-one:8080", "http://proxy-two:8081"]')

    selected = pool.for_session("same-login-session")

    assert selected in pool.proxies
    assert pool.for_session("same-login-session") == selected
    assert ProxyPool.request_config(selected) == {"http": selected, "https": selected}


def test_proxy_display_does_not_expose_credentials():
    proxy = "http://user:secret@proxy-one:8080"

    assert ProxyPool.display_name(proxy) == "proxy-one:8080"
    assert ProxyPool.display_name(None) == "direct"


def test_proxy_pool_accepts_comma_separated_values_and_rejects_invalid_urls():
    pool = ProxyPool("http://proxy-one:8080, socks5://proxy-two:1080")

    assert pool.proxies == ["http://proxy-one:8080", "socks5://proxy-two:1080"]
    with pytest.raises(ValueError):
        ProxyPool("not-a-proxy")


def test_mcp_session_reuses_auth_and_its_assigned_proxy():
    from unittest.mock import Mock, patch

    from dy_mcp.session import DouyinSession

    environment = {
        "DY_COOKIES": "sessionid=test-session",
        "DY_PROXY_POOL": '["http://proxy-one:8080", "http://proxy-two:8080"]',
    }
    with patch.dict("os.environ", environment, clear=True), \
            patch("builder.auth.DouyinAuth.from_cookie") as from_cookie:
        from_cookie.return_value = Mock()
        session = DouyinSession()
        first = session.get_auth()
        second = session.get_auth()

    assert first is second
    from_cookie.assert_called_once()
    proxies = from_cookie.call_args.kwargs["proxies"]
    assert proxies["http"] in ProxyPool(environment["DY_PROXY_POOL"]).proxies
    assert proxies["https"] == proxies["http"]
    assert from_cookie.call_args.kwargs["bootstrap_creator"] is False
