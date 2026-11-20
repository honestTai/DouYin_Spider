import json

from dy_mcp.camoufox_browser import CamoufoxManager, fixed_launch_options, proxy_options, saved_config


def make_manager(tmp_path):
    manager = CamoufoxManager(tmp_path / "camoufox")
    profile = manager.create(
        "firefox-one", 9555, proxy_url="http://user:password@proxy.example:8080",
        os_name="macos", languages=["zh-CN", "zh"],
        screen={"width": 1920, "height": 1080}, window={"width": 1440, "height": 900},
    )
    return manager, profile


def test_profile_has_isolated_directory_and_secret_free_public_output(tmp_path):
    manager, profile = make_manager(tmp_path)

    public = manager.public(profile, running=False)
    serialized = json.dumps(public)

    assert profile["engine"] == "camoufox"
    assert profile["cdp_url"] == "http://127.0.0.1:9555"
    assert profile["user_data_dir"].endswith("firefox-one/userdata")
    assert public["proxy_url"] == "http://***:***@proxy.example:8080"
    assert public["fingerprint_fixed"] is False
    assert "token" not in public
    assert "fingerprint_config" not in public
    assert "password" not in serialized
    assert manager.find_by_cdp(profile["cdp_url"])["name"] == "firefox-one"


def test_main_world_credential_hook_is_limited_to_douyin(tmp_path):
    manager, profile = make_manager(tmp_path)

    extension = manager.profile_dir(profile["name"]) / "credential-hook"
    manifest = json.loads((extension / "manifest.json").read_text())
    script = manifest["content_scripts"][0]

    assert script["world"] == "MAIN"
    assert script["run_at"] == "document_start"
    assert script["matches"] == ["*://*.douyin.com/*"]
    assert script["all_frames"] is True
    assert "DTraitUcAesEncrypt" in (extension / "hook.js").read_text()


def test_launch_options_reuse_fixed_config_and_proxy(tmp_path):
    manager, profile = make_manager(tmp_path)
    profile["fingerprint_config"] = {"navigator.userAgent": "Firefox/158.0"}

    options = manager.launch_options(profile)

    assert options["config"] == {"navigator.userAgent": "Firefox/158.0"}
    assert options["user_data_dir"] == profile["user_data_dir"]
    assert options["main_world_eval"] is True
    assert options["window"] == (1440, 900)
    assert options["screen"].max_width == 1920
    assert options["proxy"] == {
        "server": "http://proxy.example:8080", "username": "user", "password": "password",
    }
    assert options["geoip"] is True


def test_saved_config_reassembles_chunked_camoufox_environment():
    options = {"env": {
        "CAMOU_CONFIG_1": '"MacIntel"}',
        "CAMOU_CONFIG_0": '{"navigator.platform":',
        "OTHER": "ignored",
    }}

    assert saved_config(options) == {"navigator.platform": "MacIntel"}
    assert saved_config({}) == {}


def test_proxy_options_normalizes_remote_dns_socks():
    assert proxy_options("socks5h://127.0.0.1:1080") == {"server": "socks5://127.0.0.1:1080"}


def test_fixed_launch_snapshot_excludes_unrelated_process_environment():
    options = {
        "executable_path": "/camoufox/firefox",
        "args": ["-no-remote"],
        "firefox_user_prefs": {"locale": "zh-CN"},
        "headless": False,
        "user_data_dir": "/profile",
        "env": {
            "CAMOU_CONFIG_1": "{}",
            "CAMOU_PREFS_1": "{}",
            "HOME": "/should-not-be-saved",
            "API_TOKEN": "should-not-be-saved",
        },
        "timeout": 30000,
    }

    fixed = fixed_launch_options(options)

    assert fixed["env"] == {"CAMOU_CONFIG_1": "{}", "CAMOU_PREFS_1": "{}"}
    assert fixed["executable_path"] == "/camoufox/firefox"
    assert "timeout" not in fixed
