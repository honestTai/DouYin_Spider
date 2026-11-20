import re
import sys
from dataclasses import asdict


def host_operating_system(platform=""):
    value = platform or ("MacIntel" if sys.platform == "darwin" else "Win32" if sys.platform == "win32" else "Linux x86_64")
    if value == "MacIntel":
        return "macos"
    if value.startswith("Win"):
        return "windows"
    return "linux"


def chrome_version(user_agent):
    match = re.search(r"Chrome/(\d+(?:\.\d+)+)", user_agent or "")
    if not match:
        raise ValueError("User-Agent 必须包含 Chrome/完整版本号")
    return match.group(1)


def align_chrome_version(navigator, version):
    user_agent = re.sub(r"Chrome/\d+(?:\.\d+)+", f"Chrome/{version}", navigator["userAgent"])
    navigator["userAgent"] = user_agent
    navigator["appVersion"] = re.sub(r"Chrome/\d+(?:\.\d+)+", f"Chrome/{version}", navigator["appVersion"])
    metadata = navigator.get("userAgentData") or {}
    if metadata:
        metadata["uaFullVersion"] = version
        for item in metadata.get("fullVersionList") or []:
            if item.get("brand") in {"Chromium", "Google Chrome", "Microsoft Edge"}:
                item["version"] = version
    return user_agent


def generate_fingerprint(installed_version="", overrides=None):
    from browserforge.fingerprints import FingerprintGenerator, Screen
    from browserforge.headers import Browser

    overrides = overrides or {}
    custom_user_agent = overrides.get("ua") or ""
    version = chrome_version(custom_user_agent) if custom_user_agent else installed_version
    if not version:
        raise ValueError("无法确定 Chrome 版本")
    major = int(version.split(".")[0])
    platform = overrides.get("platform") or ""
    if not platform and custom_user_agent:
        if "Windows NT" in custom_user_agent:
            platform = "Win32"
        elif "Macintosh" in custom_user_agent:
            platform = "MacIntel"
        elif "Linux" in custom_user_agent:
            platform = "Linux x86_64"
    languages = overrides.get("languages") or ["zh-CN", "zh"]
    screen_override = overrides.get("screen") or {}
    width = screen_override.get("width")
    height = screen_override.get("height")
    constraints = Screen(
        min_width=width, max_width=width,
        min_height=height, max_height=height,
    )
    generated = FingerprintGenerator().generate(
        browser=Browser(name="chrome", min_version=major, max_version=major),
        os=host_operating_system(platform),
        device="desktop",
        locale=languages,
        screen=constraints,
        strict=True,
    )
    data = asdict(generated)
    navigator = data["navigator"]
    user_agent = align_chrome_version(navigator, version)
    if custom_user_agent:
        user_agent = custom_user_agent
        navigator["userAgent"] = custom_user_agent
        navigator["appVersion"] = custom_user_agent.replace("Mozilla/", "")
    source_screen = data["screen"]
    outer_width = source_screen["outerWidth"] or source_screen["availWidth"] or source_screen["width"]
    outer_height = source_screen["outerHeight"] or source_screen["availHeight"] or source_screen["height"]
    fingerprint = {
        "ua": user_agent,
        "platform": navigator["platform"],
        "languages": [language.strip() for language in navigator["languages"]],
        "cpu": navigator["hardwareConcurrency"],
        "memory": navigator["deviceMemory"] or 8,
        "screen": {
            key: source_screen[key] for key in (
                "width", "height", "availWidth", "availHeight", "availTop", "availLeft",
                "colorDepth", "pixelDepth",
            )
        },
        "window": {
            "innerWidth": outer_width,
            "innerHeight": max(1, outer_height - 88),
            "outerWidth": outer_width,
            "outerHeight": outer_height,
            "devicePixelRatio": source_screen["devicePixelRatio"],
            "screenX": source_screen["screenX"],
            "screenY": source_screen["availTop"],
        },
        "webgl": dict(data.get("videoCard") or {}),
        "timezone": "Asia/Shanghai",
        "user_agent_data": navigator.get("userAgentData") or {},
        "navigator": {
            key: navigator[key] for key in (
                "appCodeName", "appName", "appVersion", "product", "productSub",
                "vendor", "vendorSub", "maxTouchPoints",
            ) if navigator.get(key) is not None
        },
        "audio_codecs": data["audioCodecs"],
        "video_codecs": data["videoCodecs"],
        "battery": data.get("battery"),
        "generator": "browserforge",
    }
    if not fingerprint["webgl"]:
        fingerprint["webgl"] = {"vendor": "Google Inc.", "renderer": ""}
    for key in ("languages", "cpu", "memory", "timezone"):
        if overrides.get(key) is not None:
            fingerprint[key] = overrides[key]
    for section in ("screen", "window", "webgl"):
        values = overrides.get(section) or {}
        fingerprint[section].update({key: value for key, value in values.items() if value is not None})
    return fingerprint
