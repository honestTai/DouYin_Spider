import json
import re
import time
import urllib.request

from .adspower import (
    CDPClient,
    CREDENTIAL_SCRIPT,
    DTRAIT_HOOK,
    FINGERPRINT_SCRIPT,
    _accept_language,
    _decode_wrapped,
    collect_account_runtime,
)


DOUYIN_URL = "https://www.douyin.com/user/self?from_tab_name=main"


def build_runtime(cookie_header, fingerprint, credentials, runtime_info):
    if "sessionid=" not in cookie_header and "sessionid_ss=" not in cookie_header:
        raise RuntimeError("该浏览器环境尚未登录抖音")
    if not credentials.get("dtrait"):
        raise RuntimeError("未能从浏览器安全 SDK 获取 dtrait")
    web = _decode_wrapped(credentials.get("web"), "ticket/ts_sign")
    keys = _decode_wrapped(credentials.get("keys"), "浏览器私钥")
    ua = fingerprint["ua"]
    browser_version = re.search(r"(?:Chrome|Firefox)/([\d.]+)", ua)
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
    version = browser_version.group(1) if browser_version else ""
    env = {
        "DY_COOKIES": cookie_header,
        "DY_TICKET": web["ticket"],
        "DY_TS_SIGN": web["ts_sign"],
        "DY_CLIENT_CERT": web["client_cert"],
        "DY_PRIVATE_KEY": keys["ec_privateKey"],
        "DY_DTRAIT_BLOB": credentials["dtrait"],
        "DY_FP_UA": ua,
        "DY_FP_BROWSER_VERSION": version,
        "DY_FP_ENGINE_VERSION": version,
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
    runtime_info.update({
        "browser_version": version,
        "os_name": os_name,
        "platform": platform,
    })
    return env, runtime_info


def cookie_header(cookies):
    return "; ".join(
        f"{item['name']}={item['value']}"
        for item in cookies
        if item.get("name") and "douyin" in item.get("domain", "").lower()
    )


def collect_cdp_page(client, session_id=""):
    client.call("Page.addScriptToEvaluateOnNewDocument", {"source": DTRAIT_HOOK}, session_id)
    client.call("Page.reload", {"ignoreCache": False}, session_id)
    credentials = {}
    for _ in range(20):
        time.sleep(0.5)
        result = client.call(
            "Runtime.evaluate",
            {"expression": CREDENTIAL_SCRIPT, "returnByValue": True},
            session_id,
        )
        credentials = json.loads(result.get("result", {}).get("value") or "{}")
        if credentials.get("dtrait"):
            break
    fingerprint_result = client.call(
        "Runtime.evaluate",
        {"expression": FINGERPRINT_SCRIPT, "returnByValue": True},
        session_id,
    )
    fingerprint = json.loads(fingerprint_result.get("result", {}).get("value") or "{}")
    return fingerprint, credentials


def collect_chromium(cdp_url, browser_type, fingerprint=None):
    if cdp_url.startswith("http"):
        with urllib.request.urlopen(cdp_url.rstrip("/") + "/json/version", timeout=10) as response:
            cdp_url = json.load(response)["webSocketDebuggerUrl"]
    client = CDPClient(cdp_url)
    target_id = ""
    try:
        target = client.call("Target.createTarget", {"url": DOUYIN_URL})
        target_id = target["targetId"]
        attached = client.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        session_id = attached["sessionId"]
        if fingerprint:
            from .local_browser import apply_fingerprint

            apply_fingerprint(client, session_id, fingerprint)
        fingerprint, credentials = collect_cdp_page(client, session_id)
        result = client.call("Network.getCookies", {"urls": [DOUYIN_URL]}, session_id)
        header = cookie_header(result.get("cookies", []))
    finally:
        if target_id:
            client.call("Target.closeTarget", {"targetId": target_id})
        client.close()
    return build_runtime(header, fingerprint, credentials, {
        "browser_type": browser_type,
        "connection": cdp_url.split("?")[0],
    })


def webbridge_command(session, action, args=None):
    payload = {"action": action, "args": args or {}, "session": session}
    request = urllib.request.Request(
        "http://127.0.0.1:10086/command",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError(result.get("error", {}).get("message", "WebBridge 调用失败"))
    return result["data"]


def collect_webbridge(account_id):
    session = f"douyin-account-{account_id}"
    try:
        webbridge_command(session, "find_tab", {"url": DOUYIN_URL})
    except RuntimeError:
        webbridge_command(session, "navigate", {
            "url": DOUYIN_URL, "newTab": True, "group_title": "抖音账号环境",
        })
    webbridge_command(session, "cdp", {
        "method": "Page.addScriptToEvaluateOnNewDocument",
        "params": {"source": DTRAIT_HOOK},
    })
    webbridge_command(session, "cdp", {"method": "Page.reload", "params": {"ignoreCache": False}})
    credentials = {}
    for _ in range(20):
        time.sleep(0.5)
        result = webbridge_command(session, "evaluate", {"code": CREDENTIAL_SCRIPT})
        credentials = json.loads(result.get("value") or "{}")
        if credentials.get("dtrait"):
            break
    fingerprint = json.loads(webbridge_command(session, "evaluate", {"code": FINGERPRINT_SCRIPT})["value"])
    result = webbridge_command(session, "cdp", {
        "method": "Network.getCookies", "params": {"urls": [DOUYIN_URL]},
    })
    header = cookie_header(result.get("cookies", []))
    return build_runtime(header, fingerprint, credentials, {
        "browser_type": "webbridge",
        "connection": "http://127.0.0.1:10086",
    })


def bidi_evaluate(client, context, script):
    result = client.call("script.evaluate", {
        "expression": script,
        "target": {"context": context},
        "awaitPromise": True,
    })
    if result.get("type") == "exception":
        raise RuntimeError(f"Firefox 脚本执行失败: {result.get('text', '未知错误')}")
    return result.get("result", {}).get("value")


def collect_firefox(cdp_url):
    client = CDPClient(cdp_url)
    context = ""
    try:
        client.call("session.new", {"capabilities": {}})
        context = client.call("browsingContext.create", {"type": "tab"})["context"]
        client.call("browsingContext.navigate", {
            "context": context, "url": DOUYIN_URL, "wait": "complete",
        })
        client.call("script.addPreloadScript", {
            "functionDeclaration": f"() => {{ eval({json.dumps(DTRAIT_HOOK)}) }}",
            "contexts": [context],
        })
        client.call("browsingContext.reload", {"context": context, "wait": "complete"})
        credentials = {}
        for _ in range(20):
            time.sleep(0.5)
            credentials = json.loads(bidi_evaluate(client, context, CREDENTIAL_SCRIPT) or "{}")
            if credentials.get("dtrait"):
                break
        fingerprint = json.loads(bidi_evaluate(client, context, FINGERPRINT_SCRIPT) or "{}")
        result = client.call("storage.getCookies", {})
        header = cookie_header(result.get("cookies", []))
    finally:
        if context:
            client.call("browsingContext.close", {"context": context})
        try:
            client.call("session.end", {})
        finally:
            client.close()
    return build_runtime(header, fingerprint, credentials, {
        "browser_type": "firefox",
        "connection": cdp_url,
    })


def collect_camoufox_context(context):
    page = context.new_page()
    try:
        page.goto(DOUYIN_URL, wait_until="domcontentloaded", timeout=60000)
        credentials = {}
        for _ in range(20):
            time.sleep(0.5)
            raw = page.evaluate("mw:" + CREDENTIAL_SCRIPT)
            credentials = json.loads(raw or "{}")
            if credentials.get("dtrait"):
                break
        fingerprint = json.loads(page.evaluate("mw:" + FINGERPRINT_SCRIPT) or "{}")
        header = cookie_header(context.cookies([DOUYIN_URL]))
    finally:
        page.close()
    return build_runtime(header, fingerprint, credentials, {
        "browser_type": "camoufox",
        "connection": "Camoufox local control",
    })


def collect_camoufox(control_url):
    from urllib.error import HTTPError

    from .camoufox_browser import CamoufoxManager

    profile = CamoufoxManager().find_by_cdp(control_url)
    if not profile:
        raise ValueError("找不到对应的 Camoufox 本地环境")
    try:
        result = CamoufoxManager()._request(profile, "/collect", method="POST", timeout=90)
    except HTTPError as error:
        detail = json.loads(error.read().decode() or "{}").get("error") or str(error)
        raise RuntimeError(f"Camoufox 凭证采集失败: {detail}") from error
    info = result["runtime_info"]
    info["local_profile"] = profile["name"]
    return result["runtime_env"], info


def collect_runtime_for_account(account):
    browser_type = account.get("browser_type") or "adspower"
    if browser_type == "adspower":
        env, info = collect_account_runtime(
            account.get("profile_id") or "", account.get("profile_no") or "",
        )
    elif browser_type == "webbridge":
        env, info = collect_webbridge(account["id"])
    elif browser_type in {"chrome", "edge"}:
        from .local_browser import LocalBrowserManager

        local_profile = LocalBrowserManager().find_by_cdp(account["cdp_url"])
        env, info = collect_chromium(
            account["cdp_url"], browser_type,
            fingerprint=local_profile["fingerprint"] if local_profile else None,
        )
        if local_profile:
            info["local_profile"] = local_profile["name"]
    elif browser_type == "firefox":
        env, info = collect_firefox(account["cdp_url"])
    elif browser_type == "camoufox":
        env, info = collect_camoufox(account["cdp_url"])
    else:
        raise ValueError(f"不支持的浏览器环境类型: {browser_type}")
    if account.get("proxy_url"):
        env["DY_PROXY_URL"] = account["proxy_url"]
        info["proxy"] = "已配置独立代理"
    else:
        info["proxy"] = "环境默认网络"
    return env, info
