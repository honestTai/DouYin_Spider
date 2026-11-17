import os
import threading

from dotenv import load_dotenv

from .proxy_pool import ProxyPool


class DouyinSession:
    def __init__(self):
        load_dotenv()
        self._pool = ProxyPool()
        self._auth = None
        self._session_key = None
        self._proxy = None
        self._lock = threading.Lock()

    def get_auth(self):
        from builder.auth import DouyinAuth

        with self._lock:
            cookie = (os.getenv("DY_COOKIES") or "").strip()
            if not cookie:
                raise RuntimeError("MCP 服务需要在 .env 中配置 DY_COOKIES")
            proxy = self._pool.for_session(cookie)
            if self._auth is not None and self._session_key == cookie and self._proxy == proxy:
                return self._auth
            if self._auth is not None:
                self._auth.close()
            self._auth = DouyinAuth.from_cookie(
                cookie,
                bootstrap_creator=False,
                proxies=ProxyPool.request_config(proxy),
            )
            self._session_key = cookie
            self._proxy = proxy
            return self._auth

    @property
    def proxy_label(self):
        return ProxyPool.display_name(self._proxy)
