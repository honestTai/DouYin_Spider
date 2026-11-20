import pytest

from dy_mcp.fingerprint_generator import generate_fingerprint


def test_browserforge_generates_coherent_fixed_device_sample():
    fingerprint = generate_fingerprint("157.0.8103.79", {
        "platform": "MacIntel",
        "languages": ["zh-CN", "zh"],
        "screen": {"width": 1920, "height": 1080},
    })

    assert fingerprint["generator"] == "browserforge"
    assert "Chrome/157.0.8103.79" in fingerprint["ua"]
    assert fingerprint["platform"] == "MacIntel"
    assert fingerprint["languages"] == ["zh-CN", "zh"]
    assert fingerprint["screen"]["width"] == 1920
    assert fingerprint["screen"]["height"] == 1080
    assert fingerprint["screen"]["colorDepth"] == fingerprint["screen"]["pixelDepth"]
    assert fingerprint["window"]["devicePixelRatio"] > 0
    assert fingerprint["user_agent_data"]["platform"] == "macOS"
    assert fingerprint["user_agent_data"]["uaFullVersion"] == "157.0.8103.79"
    assert all(
        item["version"] == "157.0.8103.79"
        for item in fingerprint["user_agent_data"]["fullVersionList"]
        if item["brand"] in {"Chromium", "Google Chrome"}
    )
    assert fingerprint["webgl"]["vendor"]
    assert fingerprint["webgl"]["renderer"]


def test_explicit_hardware_and_rendering_overrides_are_preserved():
    fingerprint = generate_fingerprint("157.0.8103.79", {
        "platform": "Win32",
        "languages": ["zh-CN"],
        "cpu": 12,
        "memory": 16,
        "timezone": "Asia/Shanghai",
        "screen": {"availWidth": 1900, "availHeight": 1040},
        "window": {"innerWidth": 1400, "innerHeight": 800},
        "webgl": {"vendor": "Test Vendor", "renderer": "Test Renderer"},
    })

    assert fingerprint["platform"] == "Win32"
    assert fingerprint["user_agent_data"]["platform"] == "Windows"
    assert fingerprint["cpu"] == 12
    assert fingerprint["memory"] == 16
    assert fingerprint["screen"]["availWidth"] == 1900
    assert fingerprint["screen"]["availHeight"] == 1040
    assert fingerprint["window"]["innerWidth"] == 1400
    assert fingerprint["window"]["innerHeight"] == 800
    assert fingerprint["webgl"] == {"vendor": "Test Vendor", "renderer": "Test Renderer"}


def test_custom_user_agent_is_exact_and_infers_operating_system():
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/157.0.8103.79 Safari/537.36"
    )

    fingerprint = generate_fingerprint(overrides={"ua": user_agent})

    assert fingerprint["ua"] == user_agent
    assert fingerprint["platform"] == "Win32"
    assert fingerprint["navigator"]["appVersion"] == user_agent.replace("Mozilla/", "")
    assert fingerprint["user_agent_data"]["uaFullVersion"] == "157.0.8103.79"


def test_custom_user_agent_must_contain_chrome_version():
    with pytest.raises(ValueError, match="Chrome/完整版本号"):
        generate_fingerprint(overrides={"ua": "Mozilla/5.0"})
