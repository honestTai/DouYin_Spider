import asyncio
import json
import os
import re
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class AdsPowerMCP:
    def __init__(self, api_key=None, port=None):
        self.api_key = api_key or os.getenv("ADSPOWER_API_KEY", "")
        self.port = port or os.getenv("ADSPOWER_PORT", "50325")
        if not self.api_key:
            raise RuntimeError("需要在 .env 中配置 ADSPOWER_API_KEY")

    @staticmethod
    def _content(result):
        if getattr(result, "isError", False):
            text = "\n".join(getattr(item, "text", "") for item in result.content)
            raise RuntimeError(f"AdsPower MCP 调用失败: {text}")
        texts = [item.text for item in result.content if hasattr(item, "text")]
        text = "\n".join(texts).strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"message": text}

    async def _call(self, name, args):
        env = dict(os.environ)
        env.update({"PORT": self.port, "API_KEY": self.api_key})
        params = StdioServerParameters(
            command=os.getenv("ADSPOWER_MCP_COMMAND", "npx"),
            args=["-y", os.getenv("ADSPOWER_MCP_PACKAGE", "local-api-mcp-typescript")],
            env=env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, args)
                return self._content(result)

    def call(self, name, **args):
        return asyncio.run(self._call(name, args))

    @staticmethod
    def _find_value(value, key):
        if isinstance(value, dict):
            if key in value:
                return value[key]
            for item in value.values():
                found = AdsPowerMCP._find_value(item, key)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = AdsPowerMCP._find_value(item, key)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _profile_args(profile_id="", profile_no=""):
        if profile_id:
            return {"profile_id": profile_id}
        if profile_no:
            return {"profile_no": str(profile_no)}
        raise ValueError("缺少 AdsPower 环境标识")

    async def list_profiles_async(self):
        result = await self._call("get-browser-list", {"page": 1, "limit": 200})
        profiles = self._find_value(result, "list") or []
        return [
            {
                "profile_id": item.get("profile_id", ""),
                "profile_no": str(item.get("profile_no", "")),
                "name": item.get("name", ""),
                "ip_country": item.get("ip_country", ""),
                "last_open_time": item.get("last_open_time", ""),
            }
            for item in profiles
        ]

    def list_profiles(self):
        return asyncio.run(self.list_profiles_async())

    def proxy_url(self, profile_id="", profile_no=""):
        selector = {"profile_id": [profile_id]} if profile_id else {"profile_no": [str(profile_no)]}
        result = self.call("get-browser-list", page=1, limit=1, **selector)
        profiles = self._find_value(result, "list") or []
        if not profiles:
            return ""
        config = profiles[0].get("user_proxy_config") or {}
        host = config.get("proxy_host") or config.get("host") or ""
        port = config.get("proxy_port") or config.get("port") or ""
        if not host or not port:
            return ""
        scheme = (config.get("proxy_type") or "http").lower()
        if scheme not in {"http", "https", "socks5", "socks5h"}:
            scheme = "http"
        username = config.get("proxy_user") or config.get("username") or ""
        password = config.get("proxy_password") or config.get("password") or ""
        credentials = ""
        if username:
            from urllib.parse import quote
            credentials = quote(username, safe="") + ":" + quote(password, safe="") + "@"
        return f"{scheme}://{credentials}{host}:{port}"

    def open_profile(self, profile_id="", profile_no=""):
        args = self._profile_args(profile_id, profile_no)
        args.update({"headless": "0", "last_opened_tabs": "1", "delete_cache": "0"})
        result = self.call("open-browser", **args)
        ws_url = self._find_value(result, "puppeteer")
        if not isinstance(ws_url, str) or not ws_url.startswith("ws"):
            raise RuntimeError(f"AdsPower 未返回浏览器 WebSocket: {result}")
        return ws_url

    def cookie_header(self, profile_id="", profile_no=""):
        result = self.call("get-profile-cookies", **self._profile_args(profile_id, profile_no))
        cookies = self._find_value(result, "cookies") or []
        if isinstance(cookies, str):
            cookies = json.loads(cookies)
        pairs = [
            f"{item['name']}={item['value']}"
            for item in cookies
            if isinstance(item, dict) and item.get("name") and "douyin" in item.get("domain", "")
        ]
        if not pairs:
            raise RuntimeError("该 AdsPower 环境没有抖音 Cookie，请先登录抖音")
        return "; ".join(pairs)


DTRAIT_HOOK = r"""
(() => {
  const calls = [];
  Object.defineProperty(window, "__dtraitCalls", {value: calls, configurable: true});
  let sdk;
  const wrap = obj => {
    if (!obj || obj.__dtraitWrapped) return;
    try {
      const original = obj.encryptData;
      if (typeof original !== "function") return;
      obj.encryptData = function(...args) {
        try {
          calls.push(args.map(arg => typeof arg === "string" ? arg : String(arg)));
        } catch (error) {}
        return original.apply(this, args);
      };
      Object.defineProperty(obj, "__dtraitWrapped", {value: true});
    } catch (error) {}
  };
  Object.defineProperty(window, "DTraitUcAesEncrypt", {
    configurable: true,
    get() { return sdk; },
    set(value) { sdk = value; wrap(value); }
  });
})();
"""

FINGERPRINT_SCRIPT = r"""
(() => {
  const canvas = document.createElement("canvas");
  const gl = canvas.getContext("webgl");
  const ext = gl && gl.getExtension("WEBGL_debug_renderer_info");
  return JSON.stringify({
    ua: navigator.userAgent,
    platform: navigator.platform,
    languages: navigator.languages,
    language: navigator.language,
    cpu: navigator.hardwareConcurrency,
    memory: navigator.deviceMemory || 8,
    screen: {
      width: screen.width, height: screen.height,
      availWidth: screen.availWidth, availHeight: screen.availHeight
    },
    window: {
      innerWidth, innerHeight, outerWidth, outerHeight,
      dpr: devicePixelRatio
    },
    webgl: {
      vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : "",
      renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : ""
    },
    uaData: navigator.userAgentData ? {platform: navigator.userAgentData.platform} : null
  });
})()
"""

CREDENTIAL_SCRIPT = r"""
(() => {
  const calls = (window.__dtraitCalls || []).map(args => {
    try { return JSON.parse(args[1]); } catch (error) { return null; }
  }).filter(Boolean);
  const central = calls.find(item => item.sdkVersion && item.dtrait);
  return JSON.stringify({
    web: localStorage.getItem("security-sdk/s_sdk_sign_data_key/web_protect"),
    keys: localStorage.getItem("security-sdk/s_sdk_crypt_sdk"),
    dtrait: central ? central.dtrait : "",
    callCount: calls.length
  });
})()
"""


class CDPClient:
    def __init__(self, ws_url):
        import websocket

        self.socket = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        self.next_id = 0

    def call(self, method, params=None, session_id=""):
        self.next_id += 1
        request_id = self.next_id
        payload = {"id": request_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        self.socket.send(json.dumps(payload))
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            response = json.loads(self.socket.recv())
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RuntimeError(f"CDP {method} 失败: {response['error']}")
            return response.get("result", {})
        raise TimeoutError(f"CDP {method} 超时")

    def close(self):
        self.socket.close()


def _evaluate(client, session_id, script):
    result = client.call(
        "Runtime.evaluate",
        {"expression": script, "returnByValue": True, "awaitPromise": True},
        session_id,
    )
    details = result.get("exceptionDetails")
    if details:
        raise RuntimeError(f"浏览器脚本执行失败: {details.get('text', '未知错误')}")
    return result.get("result", {}).get("value")


def _decode_wrapped(value, label):
    if not value:
        raise RuntimeError(f"浏览器环境缺少 {label}，请先完成抖音登录")
    outer = json.loads(value)
    return json.loads(outer["data"])


def _accept_language(languages):
    if not languages:
        return "zh-CN,zh;q=0.9"
    return ",".join(
        language if index == 0 else f"{language};q={max(0.1, 0.9 - index * 0.1):.1f}"
        for index, language in enumerate(languages)
    )


def collect_account_runtime(profile_id="", profile_no=""):
    ads = AdsPowerMCP()
    proxy_url = ads.proxy_url(profile_id, profile_no)
    ws_url = ads.open_profile(profile_id, profile_no)
    cookie_header = ads.cookie_header(profile_id, profile_no)
    client = CDPClient(ws_url)
    target_id = ""
    try:
        target = client.call(
            "Target.createTarget",
            {"url": "https://www.douyin.com/user/self?from_tab_name=main"},
        )
        target_id = target["targetId"]
        attached = client.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        session_id = attached["sessionId"]
        client.call("Page.addScriptToEvaluateOnNewDocument", {"source": DTRAIT_HOOK}, session_id)
        client.call("Page.reload", {"ignoreCache": False}, session_id)
        credentials = {}
        for _ in range(20):
            time.sleep(0.5)
            raw = _evaluate(client, session_id, CREDENTIAL_SCRIPT)
            credentials = json.loads(raw or "{}")
            if credentials.get("dtrait"):
                break
        fingerprint = json.loads(_evaluate(client, session_id, FINGERPRINT_SCRIPT) or "{}")
    finally:
        if target_id:
            client.call("Target.closeTarget", {"targetId": target_id})
        client.close()

    if not credentials.get("dtrait"):
        raise RuntimeError("未能从浏览器安全 SDK 获取 dtrait")
    web = _decode_wrapped(credentials.get("web"), "ticket/ts_sign")
    keys = _decode_wrapped(credentials.get("keys"), "浏览器私钥")
    if "sessionid=" not in cookie_header and "sessionid_ss=" not in cookie_header:
        raise RuntimeError("该环境尚未登录抖音")

    ua = fingerprint["ua"]
    browser_version = re.search(r"Chrome/([\d.]+)", ua)
    platform = fingerprint.get("platform", "Win32")
    if platform == "MacIntel":
        os_name = "macOS"
        os_version = re.search(r"Mac OS X ([\d_]+)", ua)
        os_version = os_version.group(1).replace("_", ".") if os_version else "10.15.7"
    elif platform.startswith("Win"):
        os_name, os_version = "Windows", "10"
    else:
        os_name, os_version = platform, ""
    screen = fingerprint["screen"]
    window = fingerprint["window"]
    env = {
        "DY_COOKIES": cookie_header,
        "DY_TICKET": web["ticket"],
        "DY_TS_SIGN": web["ts_sign"],
        "DY_CLIENT_CERT": web["client_cert"],
        "DY_PRIVATE_KEY": keys["ec_privateKey"],
        "DY_DTRAIT_BLOB": credentials["dtrait"],
        "DY_FP_UA": ua,
        "DY_FP_BROWSER_VERSION": browser_version.group(1) if browser_version else "",
        "DY_FP_ENGINE_VERSION": browser_version.group(1) if browser_version else "",
        "DY_FP_OS_NAME": os_name,
        "DY_FP_OS_VERSION": os_version,
        "DY_FP_PLATFORM": platform,
        "DY_FP_CPU_CORE_NUM": str(fingerprint["cpu"]),
        "DY_FP_DEVICE_MEMORY": str(fingerprint["memory"]),
        "DY_FP_SCREEN_WIDTH": str(screen["width"]),
        "DY_FP_SCREEN_HEIGHT": str(screen["height"]),
        "DY_FP_INNER_WIDTH": str(window["innerWidth"]),
        "DY_FP_INNER_HEIGHT": str(window["innerHeight"]),
        "DY_FP_OUTER_WIDTH": str(window["outerWidth"]),
        "DY_FP_OUTER_HEIGHT": str(window["outerHeight"]),
        "DY_FP_AVAIL_WIDTH": str(screen["availWidth"]),
        "DY_FP_AVAIL_HEIGHT": str(screen["availHeight"]),
        "DY_FP_WEBGL_VENDOR": fingerprint["webgl"]["vendor"],
        "DY_FP_WEBGL_RENDERER": fingerprint["webgl"]["renderer"],
        "DY_FP_ACCEPT_LANGUAGE": _accept_language(fingerprint.get("languages", [])),
    }
    if proxy_url:
        env["DY_PROXY_URL"] = proxy_url
    return env, {
        "profile_id": profile_id,
        "profile_no": str(profile_no),
        "browser_version": env["DY_FP_BROWSER_VERSION"],
        "os_name": os_name,
        "platform": platform,
        "ip_managed_by": "AdsPower",
        "proxy": "已配置独立代理" if proxy_url else "环境默认网络",
    }
