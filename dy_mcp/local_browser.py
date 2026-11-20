import json
import os
import platform as host_platform
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .adspower import CDPClient
from .store import ROOT


LOCAL_BROWSER_ROOT = ROOT / ".kimi-code" / "local-browsers"


def validate_profile_name(value):
    name = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        raise ValueError("环境名称只能包含字母、数字、下划线和连字符，最长 64 位")
    return name


def find_browser(executable=""):
    if executable:
        path = Path(executable).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"浏览器不存在: {path}")
        return str(path.resolve())
    candidates = []
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    elif os.name == "nt":
        roots = [os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)"), os.getenv("LOCALAPPDATA")]
        for root in filter(None, roots):
            candidates.extend([
                str(Path(root) / "Google/Chrome/Application/chrome.exe"),
                str(Path(root) / "Chromium/Application/chrome.exe"),
                str(Path(root) / "Microsoft/Edge/Application/msedge.exe"),
            ])
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for candidate in candidates:
        if Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise RuntimeError("未找到 Chrome/Chromium/Edge，请使用 --executable 指定浏览器路径")


def browser_version(executable):
    result = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, timeout=10,
    )
    match = re.search(r"(?:Chrome|Chromium|Edge)[ /](\d+(?:\.\d+)+)", result.stdout.strip())
    if not match:
        raise RuntimeError("无法识别浏览器版本，请使用 --user-agent 显式指定 UA")
    return match.group(1)


def default_fingerprint(executable, overrides=None):
    from .fingerprint_generator import generate_fingerprint

    overrides = overrides or {}
    installed_version = "" if overrides.get("ua") else browser_version(executable)
    return generate_fingerprint(installed_version, overrides)


def user_agent_metadata(fingerprint):
    match = re.search(r"Chrome/(\d+(?:\.\d+)+)", fingerprint["ua"])
    version = match.group(1) if match else ""
    major = version.split(".")[0] if version else ""
    platform = {"MacIntel": "macOS", "Win32": "Windows"}.get(fingerprint["platform"], fingerprint["platform"])
    metadata = dict(fingerprint.get("user_agent_data") or {})
    metadata.update({
        "brands": metadata.get("brands") or [
            {"brand": "Chromium", "version": major},
            {"brand": "Google Chrome", "version": major},
            {"brand": "Not_A Brand", "version": "99"},
        ],
        "fullVersionList": metadata.get("fullVersionList") or [
            {"brand": "Chromium", "version": version},
            {"brand": "Google Chrome", "version": version},
            {"brand": "Not_A Brand", "version": "99.0.0.0"},
        ],
        "fullVersion": version,
        "platform": metadata.get("platform") or platform,
        "platformVersion": metadata.get("platformVersion") or "",
        "architecture": metadata.get("architecture") or (
            "arm" if host_platform.machine().lower() in {"arm64", "aarch64"} else "x86"
        ),
        "model": metadata.get("model") or "",
        "mobile": False,
        "bitness": metadata.get("bitness") or "64",
    })
    return metadata


def fingerprint_script(fingerprint):
    config = json.dumps(fingerprint, ensure_ascii=False)
    metadata = json.dumps(user_agent_metadata(fingerprint), ensure_ascii=False)
    return f"""
(() => {{
  const config = {config};
  const metadata = {metadata};
  const define = (object, key, value) => {{
    if (value === undefined || value === null) return;
    try {{ Object.defineProperty(object, key, {{configurable: true, get: () => value}}); }} catch (_) {{}}
  }};
  const navigatorTarget = window.Navigator ? Navigator.prototype : navigator;
  define(navigatorTarget, 'userAgent', config.ua);
  define(navigatorTarget, 'appVersion', config.navigator?.appVersion || config.ua.replace('Mozilla/', ''));
  define(navigatorTarget, 'platform', config.platform);
  define(navigatorTarget, 'hardwareConcurrency', Number(config.cpu));
  define(navigatorTarget, 'deviceMemory', Number(config.memory));
  define(navigatorTarget, 'languages', Object.freeze([...config.languages]));
  define(navigatorTarget, 'language', config.languages[0]);
  for (const [key, value] of Object.entries(config.navigator || {{}})) {{
    if (!['userAgent', 'appVersion', 'platform', 'languages'].includes(key)) define(navigatorTarget, key, value);
  }}
  const uaData = Object.create(window.NavigatorUAData ? NavigatorUAData.prototype : Object.prototype);
  for (const key of ['brands', 'mobile', 'platform']) define(uaData, key, metadata[key]);
  define(uaData, 'getHighEntropyValues', async hints => {{
    const result = {{brands: metadata.brands, mobile: false, platform: metadata.platform}};
    for (const hint of hints || []) if (hint in metadata) result[hint] = metadata[hint];
    return result;
  }});
  define(uaData, 'toJSON', () => ({{brands: metadata.brands, mobile: false, platform: metadata.platform}}));
  define(navigatorTarget, 'userAgentData', uaData);
  const screenTarget = window.Screen ? Screen.prototype : screen;
  for (const key of ['width', 'height', 'availWidth', 'availHeight', 'availTop', 'availLeft', 'colorDepth', 'pixelDepth']) {{
    if (config.screen[key] !== undefined) define(screenTarget, key, Number(config.screen[key]));
  }}
  for (const key of ['innerWidth', 'innerHeight', 'outerWidth', 'outerHeight', 'devicePixelRatio', 'screenX', 'screenY']) {{
    if (config.window[key] !== undefined) define(window, key, Number(config.window[key]));
  }}
  for (const type of [window.WebGLRenderingContext, window.WebGL2RenderingContext]) {{
    if (!type) continue;
    const original = type.prototype.getParameter;
    type.prototype.getParameter = function(parameter) {{
      if (parameter === 0x9245) return config.webgl.vendor;
      if (parameter === 0x9246) return config.webgl.renderer;
      return original.call(this, parameter);
    }};
  }}
  const canPlayType = HTMLMediaElement.prototype.canPlayType;
  HTMLMediaElement.prototype.canPlayType = function(type) {{
    const match = /^(audio|video)\\/([^;]+)/.exec(type || '');
    const values = match ? config[`${{match[1]}}_codecs`] : null;
    if (values && match[2] in values) return values[match[2]];
    return canPlayType.call(this, type);
  }};
  const resolvedOptions = Intl.DateTimeFormat.prototype.resolvedOptions;
  Intl.DateTimeFormat.prototype.resolvedOptions = function(...args) {{
    const result = resolvedOptions.apply(this, args);
    if (config.timezone) result.timeZone = config.timezone;
    if (config.languages.length) result.locale = config.languages[0];
    return result;
  }};
}})();
"""


def redact_proxy(value):
    if not value:
        return ""
    parsed = urlsplit(value)
    if not parsed.username and not parsed.password:
        return value
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = f"***:***@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def validate_proxy(value):
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https", "socks5", "socks5h"} or not parsed.hostname or not parsed.port:
        raise ValueError("代理 URL 应类似 http://user:pass@127.0.0.1:8080 或 socks5://127.0.0.1:1080")
    return value


class FingerprintDaemon:
    def __init__(self, ws_url, fingerprint, proxy_url=""):
        import websocket

        self.socket = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        self.socket.settimeout(None)
        self.fingerprint = fingerprint
        self.proxy_url = proxy_url
        self.next_id = 0
        self.pending = []
        self.sessions = set()

    def call(self, method, params=None, session_id=""):
        self.next_id += 1
        request_id = self.next_id
        payload = {"id": request_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        self.socket.send(json.dumps(payload))
        while True:
            message = json.loads(self.socket.recv())
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {method} 失败: {message['error']}")
                return message.get("result", {})
            self.pending.append(message)

    def attach(self, session_id, target_info):
        if session_id in self.sessions:
            return
        self.sessions.add(session_id)
        if target_info.get("type") == "page":
            apply_fingerprint(self, session_id, self.fingerprint)
            self.call("Runtime.evaluate", {
                "expression": fingerprint_script(self.fingerprint),
            }, session_id)
            parsed = urlsplit(self.proxy_url)
            if parsed.username or parsed.password:
                self.call("Fetch.enable", {"handleAuthRequests": True}, session_id)
        self.call("Runtime.runIfWaitingForDebugger", session_id=session_id)

    def handle(self, message):
        if message.get("method") == "Target.attachedToTarget":
            params = message["params"]
            self.attach(params["sessionId"], params.get("targetInfo") or {})
        elif message.get("method") == "Fetch.authRequired":
            parsed = urlsplit(self.proxy_url)
            self.call("Fetch.continueWithAuth", {
                "requestId": message["params"]["requestId"],
                "authChallengeResponse": {
                    "response": "ProvideCredentials",
                    "username": parsed.username or "",
                    "password": parsed.password or "",
                },
            }, message.get("sessionId", ""))
        elif message.get("method") == "Target.detachedFromTarget":
            self.sessions.discard(message.get("params", {}).get("sessionId", ""))

    def run(self):
        self.call("Target.setAutoAttach", {
            "autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True,
        })
        while True:
            if self.pending:
                message = self.pending.pop(0)
            else:
                message = json.loads(self.socket.recv())
            self.handle(message)


class LocalBrowserManager:
    def __init__(self, root=LOCAL_BROWSER_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def profile_dir(self, name):
        return self.root / validate_profile_name(name)

    def config_path(self, name):
        return self.profile_dir(name) / "profile.json"

    def get(self, name):
        path = self.config_path(name)
        if not path.is_file():
            raise ValueError(f"本地浏览器环境不存在: {name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def create(self, name, port, *, executable="", proxy_url="", fingerprint=None):
        name = validate_profile_name(name)
        if not 1024 <= int(port) <= 65535:
            raise ValueError("CDP 端口必须在 1024 到 65535 之间")
        if self.config_path(name).exists():
            raise ValueError(f"本地浏览器环境已存在: {name}")
        for existing in self.list():
            if existing["port"] == int(port):
                raise ValueError(f"CDP 端口 {port} 已被环境 {existing['name']} 使用")
        directory = self.profile_dir(name)
        executable = find_browser(executable)
        profile = {
            "name": name,
            "port": int(port),
            "cdp_url": f"http://127.0.0.1:{int(port)}",
            "executable": executable,
            "proxy_url": validate_proxy(proxy_url),
            "user_data_dir": str(directory / "userdata"),
            "fingerprint": default_fingerprint(executable, fingerprint),
        }
        directory.mkdir(parents=True, exist_ok=False)
        self.config_path(name).write_text(
            json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        self._write_extension(profile)
        return profile

    def list(self):
        profiles = []
        for path in sorted(self.root.glob("*/profile.json")):
            profiles.append(json.loads(path.read_text(encoding="utf-8")))
        return profiles

    def find_by_cdp(self, cdp_url):
        normalized = str(cdp_url or "").rstrip("/")
        for profile in self.list():
            if profile["cdp_url"] == normalized:
                return profile
        return None

    def public(self, profile, *, running=None):
        result = {**profile, "proxy_url": redact_proxy(profile.get("proxy_url") or "")}
        if running is not None:
            result["running"] = running
            result["pid"] = self._pid(profile["name"]) if running else None
        return result

    def _pid(self, name):
        try:
            return int((self.profile_dir(name) / "browser.pid").read_text().strip())
        except (OSError, ValueError):
            return 0

    def _version(self, profile, timeout=1):
        with urllib.request.urlopen(profile["cdp_url"] + "/json/version", timeout=timeout) as response:
            return json.load(response)

    def status(self, name):
        profile = self.get(name)
        try:
            self._version(profile)
            running = True
        except (OSError, ValueError):
            running = False
        if not running:
            (self.profile_dir(name) / "browser.pid").unlink(missing_ok=True)
        return self.public(profile, running=running)

    def list_status(self):
        return [self.status(profile["name"]) for profile in self.list()]

    def _write_extension(self, profile):
        directory = self.profile_dir(profile["name"]) / "extension"
        directory.mkdir(parents=True, exist_ok=True)
        manifest = {
            "manifest_version": 3,
            "name": f"Local profile {profile['name']}",
            "version": "1.0.0",
            "content_scripts": [{
                "matches": ["<all_urls>"],
                "js": ["fingerprint.js"],
                "run_at": "document_start",
                "world": "MAIN",
                "all_frames": True,
            }],
        }
        proxy_url = profile.get("proxy_url") or ""
        parsed = urlsplit(proxy_url)
        if parsed.username or parsed.password:
            manifest.update({
                "permissions": ["proxy", "webRequest", "webRequestAuthProvider"],
                "host_permissions": ["<all_urls>"],
                "background": {"service_worker": "proxy.js"},
            })
            proxy = {
                "scheme": "socks5" if parsed.scheme == "socks5h" else parsed.scheme,
                "host": parsed.hostname,
                "port": parsed.port,
                "username": parsed.username or "",
                "password": parsed.password or "",
            }
            (directory / "proxy.js").write_text(f"""
const config = {json.dumps(proxy, ensure_ascii=False)};
chrome.proxy.settings.set({{
  value: {{mode: 'fixed_servers', rules: {{singleProxy: {{
    scheme: config.scheme, host: config.host, port: config.port
  }}, bypassList: ['<local>']}}}},
  scope: 'regular'
}});
chrome.webRequest.onAuthRequired.addListener(
  (_details, callback) => callback({{authCredentials: {{username: config.username, password: config.password}}}}),
  {{urls: ['<all_urls>']}}, ['blocking']
);
""", encoding="utf-8")
        (directory / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        (directory / "fingerprint.js").write_text(
            fingerprint_script(profile["fingerprint"]), encoding="utf-8",
        )

    def command(self, profile):
        fingerprint = profile["fingerprint"]
        command = [
            profile["executable"],
            f"--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={profile['port']}",
            f"--user-data-dir={profile['user_data_dir']}",
            f"--load-extension={self.profile_dir(profile['name']) / 'extension'}",
            f"--user-agent={fingerprint['ua']}",
            f"--lang={fingerprint['languages'][0]}",
            f"--window-size={fingerprint['window']['outerWidth']},{fingerprint['window']['outerHeight']}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ]
        if profile.get("proxy_url"):
            command.insert(5, f"--proxy-server={self._proxy_server(profile['proxy_url'])}")
        return command

    @staticmethod
    def _proxy_server(proxy_url):
        parsed = urlsplit(proxy_url)
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        scheme = "socks5" if parsed.scheme == "socks5h" else parsed.scheme
        return f"{scheme}://{host}:{parsed.port}"

    def _daemon_pid(self, name):
        try:
            return int((self.profile_dir(name) / "daemon.pid").read_text().strip())
        except (OSError, ValueError):
            return 0

    def _start_daemon(self, name, profile):
        pid = self._daemon_pid(name)
        if pid:
            try:
                os.kill(pid, 0)
                return
            except OSError:
                pass
        self._version(profile)
        log_path = self.profile_dir(name) / "daemon.log"
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    sys.executable, "-m", "dy_mcp.local_browser", "--daemon", name,
                    "--root", str(self.root),
                ],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        (self.profile_dir(name) / "daemon.pid").write_text(str(process.pid), encoding="utf-8")
        time.sleep(0.3)
        if process.poll() is not None:
            raise RuntimeError(f"指纹守护进程启动失败，请查看日志: {log_path}")

    def _stop_daemon(self, name):
        pid = self._daemon_pid(name)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        (self.profile_dir(name) / "daemon.pid").unlink(missing_ok=True)

    def start(self, name):
        profile = self.get(name)
        try:
            self._version(profile)
            self._start_daemon(name, profile)
            return self.public(profile, running=True)
        except (OSError, ValueError):
            pass
        self._write_extension(profile)
        Path(profile["user_data_dir"]).mkdir(parents=True, exist_ok=True)
        log_path = self.profile_dir(name) / "browser.log"
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                self.command(profile), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        (self.profile_dir(name) / "browser.pid").write_text(str(process.pid), encoding="utf-8")
        for _ in range(60):
            try:
                self._version(profile)
                self._start_daemon(name, profile)
                return self.public(profile, running=True)
            except (OSError, ValueError):
                if process.poll() is not None:
                    raise RuntimeError(f"浏览器启动失败，请查看日志: {log_path}")
                time.sleep(0.25)
        process.terminate()
        raise RuntimeError(f"浏览器 CDP 未就绪，请查看日志: {log_path}")

    def stop(self, name):
        profile = self.get(name)
        pid = self._pid(name)
        self._stop_daemon(name)
        try:
            version = self._version(profile)
        except (OSError, ValueError):
            (self.profile_dir(name) / "browser.pid").unlink(missing_ok=True)
            return self.public(profile, running=False)
        client = None
        try:
            client = CDPClient(version["webSocketDebuggerUrl"])
            client.call("Browser.close")
        except Exception:
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        finally:
            if client is not None:
                client.close()
        for _ in range(20):
            try:
                self._version(profile)
            except (OSError, ValueError):
                (self.profile_dir(name) / "browser.pid").unlink(missing_ok=True)
                return self.public(profile, running=False)
            time.sleep(0.25)
        if pid:
            os.kill(pid, signal.SIGTERM)
        raise RuntimeError("浏览器停止超时")


def apply_fingerprint(client, session_id, fingerprint):
    metadata = user_agent_metadata(fingerprint)
    client.call("Emulation.setUserAgentOverride", {
        "userAgent": fingerprint["ua"],
        "acceptLanguage": ",".join(fingerprint["languages"]),
        "platform": fingerprint["platform"],
        "userAgentMetadata": metadata,
    }, session_id)
    client.call("Emulation.setLocaleOverride", {"locale": fingerprint["languages"][0]}, session_id)
    if fingerprint.get("timezone"):
        client.call("Emulation.setTimezoneOverride", {"timezoneId": fingerprint["timezone"]}, session_id)
    client.call("Emulation.setDeviceMetricsOverride", {
        "width": int(fingerprint["window"]["innerWidth"]),
        "height": int(fingerprint["window"]["innerHeight"]),
        "deviceScaleFactor": float(fingerprint["window"].get("devicePixelRatio") or 1),
        "mobile": False,
        "screenWidth": int(fingerprint["screen"]["width"]),
        "screenHeight": int(fingerprint["screen"]["height"]),
    }, session_id)
    client.call("Page.enable", {}, session_id)
    client.call("Page.addScriptToEvaluateOnNewDocument", {
        "source": fingerprint_script(fingerprint),
    }, session_id)


def run_daemon(name, root=LOCAL_BROWSER_ROOT):
    manager = LocalBrowserManager(root)
    profile = manager.get(name)
    version = manager._version(profile, timeout=10)
    FingerprintDaemon(
        version["webSocketDebuggerUrl"], profile["fingerprint"], profile.get("proxy_url") or "",
    ).run()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", required=True)
    parser.add_argument("--root", default=str(LOCAL_BROWSER_ROOT))
    arguments = parser.parse_args()
    run_daemon(arguments.daemon, arguments.root)
