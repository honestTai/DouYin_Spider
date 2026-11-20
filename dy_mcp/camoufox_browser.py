import hmac
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .adspower import DTRAIT_HOOK
from .local_browser import redact_proxy, validate_profile_name, validate_proxy
from .store import ROOT


CAMOUFOX_ROOT = ROOT / ".kimi-code" / "camoufox-browsers"


def proxy_options(value):
    if not value:
        return None
    parsed = urlsplit(value)
    scheme = "socks5" if parsed.scheme == "socks5h" else parsed.scheme
    result = {"server": f"{scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        result["username"] = unquote(parsed.username)
    if parsed.password:
        result["password"] = unquote(parsed.password)
    return result


def saved_config(options):
    environment = options.get("env") or {}
    chunks = []
    for key, value in environment.items():
        if key.startswith("CAMOU_CONFIG_"):
            chunks.append((int(key.rsplit("_", 1)[1]), value))
    if not chunks:
        return {}
    return json.loads("".join(value for _index, value in sorted(chunks)))


def fixed_launch_options(options):
    result = {
        key: value for key, value in options.items()
        if key in {
            "executable_path", "args", "firefox_user_prefs", "headless",
            "user_data_dir", "proxy",
        }
    }
    result["env"] = {
        key: value for key, value in (options.get("env") or {}).items()
        if key.startswith(("CAMOU_CONFIG_", "CAMOU_PREFS_")) or key == "FONTCONFIG_FILE"
    }
    return result


def ensure_camoufox_installed(executable=""):
    if executable:
        path = Path(executable).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Camoufox 可执行文件不存在: {path}")
        return str(path.resolve())
    from camoufox.pkgman import camoufox_path, launch_path

    return launch_path(camoufox_path(download_if_missing=False))


class CamoufoxManager:
    def __init__(self, root=CAMOUFOX_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def profile_dir(self, name):
        return self.root / validate_profile_name(name)

    def config_path(self, name):
        return self.profile_dir(name) / "profile.json"

    def get(self, name):
        path = self.config_path(name)
        if not path.is_file():
            raise ValueError(f"Camoufox 环境不存在: {name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, profile):
        self.config_path(profile["name"]).write_text(
            json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    def create(self, name, port, *, executable="", proxy_url="", os_name="macos",
               languages=None, screen=None, window=None):
        name = validate_profile_name(name)
        if not 1024 <= int(port) <= 65535:
            raise ValueError("控制端口必须在 1024 到 65535 之间")
        if os_name not in {"macos", "windows", "linux"}:
            raise ValueError("Camoufox 系统只支持 macos、windows 或 linux")
        if self.config_path(name).exists():
            raise ValueError(f"Camoufox 环境已存在: {name}")
        for existing in self.list():
            if existing["port"] == int(port):
                raise ValueError(f"控制端口 {port} 已被环境 {existing['name']} 使用")
        directory = self.profile_dir(name)
        directory.mkdir(parents=True, exist_ok=False)
        profile = {
            "name": name,
            "engine": "camoufox",
            "port": int(port),
            "cdp_url": f"http://127.0.0.1:{int(port)}",
            "executable": str(Path(executable).expanduser().resolve()) if executable else "",
            "proxy_url": validate_proxy(proxy_url),
            "user_data_dir": str(directory / "userdata"),
            "os": os_name,
            "languages": languages or ["zh-CN", "zh"],
            "screen": screen or {},
            "window": window or {},
            "fingerprint_config": {},
        }
        import secrets

        profile["token"] = secrets.token_urlsafe(32)
        self.save(profile)
        self._write_extension(profile)
        return profile

    def list(self):
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.root.glob("*/profile.json"))
        ]

    def find_by_cdp(self, cdp_url):
        normalized = str(cdp_url or "").rstrip("/")
        for profile in self.list():
            if profile["cdp_url"] == normalized:
                return profile
        return None

    def public(self, profile, *, running=None):
        result = {
            key: value for key, value in profile.items()
            if key not in {"token", "fingerprint_config", "launch_config"}
        }
        result["proxy_url"] = redact_proxy(profile.get("proxy_url") or "")
        result["fingerprint_fixed"] = bool(profile.get("fingerprint_config"))
        if running is not None:
            result["running"] = running
            result["pid"] = self._pid(profile["name"]) if running else None
        return result

    def _pid(self, name):
        try:
            return int((self.profile_dir(name) / "service.pid").read_text().strip())
        except (OSError, ValueError):
            return 0

    def _request(self, profile, path, *, method="GET", timeout=10):
        request = urllib.request.Request(
            profile["cdp_url"] + path, method=method,
            headers={"Authorization": f"Bearer {profile['token']}"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def status(self, name):
        profile = self.get(name)
        try:
            self._request(profile, "/status", timeout=1)
            running = True
        except (OSError, ValueError):
            running = False
        if not running:
            (self.profile_dir(name) / "service.pid").unlink(missing_ok=True)
        return self.public(profile, running=running)

    def list_status(self):
        return [self.status(profile["name"]) for profile in self.list()]

    def _write_extension(self, profile):
        directory = self.profile_dir(profile["name"]) / "credential-hook"
        directory.mkdir(parents=True, exist_ok=True)
        manifest = {
            "manifest_version": 3,
            "name": f"Douyin credential collector {profile['name']}",
            "version": "1.0.0",
            "browser_specific_settings": {"gecko": {"id": f"douyin-{profile['name']}@localhost"}},
            "content_scripts": [{
                "matches": ["*://*.douyin.com/*"],
                "js": ["hook.js"],
                "run_at": "document_start",
                "all_frames": True,
                "world": "MAIN",
                "match_about_blank": True,
                "match_origin_as_fallback": True,
            }],
        }
        (directory / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        (directory / "hook.js").write_text(DTRAIT_HOOK, encoding="utf-8")

    def launch_options(self, profile):
        from camoufox.fingerprints import Screen

        screen = profile.get("screen") or {}
        window = profile.get("window") or {}
        options = {
            "config": profile.get("fingerprint_config") or {},
            "os": profile["os"],
            "locale": profile["languages"],
            "addons": [str(self.profile_dir(profile["name"]) / "credential-hook")],
            "main_world_eval": True,
            "enable_cache": True,
            "headless": False,
            "user_data_dir": profile["user_data_dir"],
        }
        if profile.get("executable"):
            options["executable_path"] = profile["executable"]
        if screen:
            options["screen"] = Screen(
                min_width=screen.get("width"), max_width=screen.get("width"),
                min_height=screen.get("height"), max_height=screen.get("height"),
            )
        if window:
            options["window"] = (window["width"], window["height"])
        if profile.get("proxy_url"):
            options["proxy"] = proxy_options(profile["proxy_url"])
            options["geoip"] = True
        return options

    def start(self, name):
        profile = self.get(name)
        try:
            self._request(profile, "/status", timeout=1)
            return self.public(self.get(name), running=True)
        except (OSError, ValueError):
            pass
        ensure_camoufox_installed(profile.get("executable") or "")
        Path(profile["user_data_dir"]).mkdir(parents=True, exist_ok=True)
        log_path = self.profile_dir(name) / "service.log"
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "dy_mcp.camoufox_browser", "--serve", name, "--root", str(self.root)],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        (self.profile_dir(name) / "service.pid").write_text(str(process.pid), encoding="utf-8")
        for _ in range(120):
            try:
                self._request(profile, "/status", timeout=1)
                return self.public(self.get(name), running=True)
            except (OSError, ValueError):
                if process.poll() is not None:
                    raise RuntimeError(f"Camoufox 启动失败，请查看日志: {log_path}")
                time.sleep(0.25)
        process.terminate()
        raise RuntimeError(f"Camoufox 控制服务未就绪，请查看日志: {log_path}")

    def stop(self, name):
        profile = self.get(name)
        try:
            self._request(profile, "/shutdown", method="POST", timeout=5)
        except (OSError, ValueError):
            (self.profile_dir(name) / "service.pid").unlink(missing_ok=True)
            return self.public(profile, running=False)
        pid = self._pid(name)
        for _ in range(40):
            running = True
            try:
                self._request(profile, "/status", timeout=1)
            except (OSError, ValueError):
                running = False
            alive = False
            if pid:
                try:
                    os.kill(pid, 0)
                    alive = True
                except OSError:
                    pass
            if not running and not alive:
                (self.profile_dir(name) / "service.pid").unlink(missing_ok=True)
                return self.public(profile, running=False)
            time.sleep(0.25)
        if pid:
            os.kill(pid, signal.SIGTERM)
        raise RuntimeError("Camoufox 停止超时")


def run_service(name, root=CAMOUFOX_ROOT):
    from camoufox.sync_api import Camoufox
    from camoufox.utils import launch_options

    manager = CamoufoxManager(root)
    profile = manager.get(name)
    if profile.get("launch_config"):
        from copy import deepcopy

        options = deepcopy(profile["launch_config"])
        options["env"] = {**os.environ, **(options.get("env") or {})}
    else:
        options = launch_options(**manager.launch_options(profile))
        profile["fingerprint_config"] = saved_config(options)
        if not profile["fingerprint_config"]:
            raise RuntimeError("未能保存 Camoufox 固定指纹配置")
        profile["launch_config"] = fixed_launch_options(options)
        manager.save(profile)
    with Camoufox(from_options=options, persistent_context=True) as context:
        if not context.pages:
            context.new_page()

        class Handler(BaseHTTPRequestHandler):
            def authorize(self):
                expected = f"Bearer {profile['token']}"
                return hmac.compare_digest(self.headers.get("Authorization", ""), expected)

            def respond(self, value, status=200):
                body = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not self.authorize():
                    self.respond({"error": "unauthorized"}, 401)
                elif self.path == "/status":
                    self.respond({"status": "running", "name": name})
                else:
                    self.respond({"error": "not_found"}, 404)

            def do_POST(self):
                if not self.authorize():
                    self.respond({"error": "unauthorized"}, 401)
                    return
                try:
                    if self.path == "/collect":
                        from .browser_runtime import collect_camoufox_context

                        env, info = collect_camoufox_context(context)
                        self.respond({"runtime_env": env, "runtime_info": info})
                    elif self.path == "/shutdown":
                        self.respond({"status": "stopping"})
                        threading.Thread(target=self.server.shutdown, daemon=True).start()
                    else:
                        self.respond({"error": "not_found"}, 404)
                except Exception as error:
                    self.respond({"error": str(error)}, 500)

            def log_message(self, _format, *args):
                return

        server = HTTPServer(("127.0.0.1", profile["port"]), Handler)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", required=True)
    parser.add_argument("--root", default=str(CAMOUFOX_ROOT))
    arguments = parser.parse_args()
    run_service(arguments.serve, arguments.root)
