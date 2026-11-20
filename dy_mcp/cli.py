import argparse
import json
import subprocess
import sys

from .scheduler import SchedulerController, run_scheduler
from .store import AccountStore, ROOT


def print_json(value, *, stream=None):
    output = sys.stdout if stream is None else stream
    print(json.dumps(value, ensure_ascii=False, indent=2), file=output)


def add_execution_options(parser):
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="真实发布评论")
    mode.add_argument("--dry-run", action="store_true", help="只预览，不发布评论")
    parser.add_argument("--confirm", action="store_true", help="确认真实发布；必须配合 --live")


def add_scheduler_options(parser):
    add_execution_options(parser)
    parser.add_argument("--global-per-hour", type=int, help="全局每小时评论上限")
    parser.add_argument("--min-interval-seconds", type=int, help="两次任务之间的最小秒数")
    parser.add_argument("--poll-seconds", type=int, help="调度轮询秒数")


def selected_dry_run(args):
    if args.live:
        return False
    if args.dry_run:
        return True
    return None


def validate_live_confirmation(store, args, dry_run):
    live = dry_run is False or (dry_run is None and store.settings().get("dry_run") == "false")
    if live and not args.confirm:
        raise ValueError("真实评论必须同时使用 --live --confirm")


def scheduler_values(args):
    return {
        "global_per_hour": args.global_per_hour,
        "min_interval_seconds": args.min_interval_seconds,
        "poll_seconds": args.poll_seconds,
    }


def string_list(values, *, split_commas=False):
    if values is None:
        return None
    result = []
    for value in values:
        items = value.replace("，", ",").split(",") if split_commas else [value]
        result.extend(item.strip() for item in items if item.strip())
    return result


def add_account_options(parser, *, creating=False):
    parser.add_argument("--name", required=creating, help="账号名称")
    parser.add_argument("--profile-id", help="AdsPower profile ID")
    parser.add_argument("--profile-no", help="AdsPower 环境编号")
    parser.add_argument(
        "--browser-type",
        choices=["adspower", "webbridge", "chrome", "edge", "firefox", "camoufox"],
        help="浏览器环境类型",
    )
    parser.add_argument("--cdp-url", help="Chrome/Edge CDP 或 Firefox BiDi 地址")
    parser.add_argument("--proxy-url", help="账号独立代理 URL")
    parser.add_argument(
        "--keywords", action="append", required=creating,
        help="搜索关键词，逗号分隔或重复传入",
    )
    parser.add_argument(
        "--comment-texts", action="append",
        help="评论文字，重复传入可配置多条；传空字符串可清空",
    )
    parser.add_argument(
        "--image-paths", action="append",
        help="评论图片绝对路径，重复传入可配置多张；传空字符串可清空",
    )
    state = parser.add_mutually_exclusive_group()
    state.add_argument("--enable", dest="enabled", action="store_true", help="启用账号")
    state.add_argument("--disable", dest="enabled", action="store_false", help="停用账号")
    parser.set_defaults(enabled=True if creating else None)
    parser.add_argument("--per-hour-limit", type=int, help="账号每小时评论上限")
    parser.add_argument("--per-day-limit", type=int, help="账号每日评论上限")
    parser.add_argument("--min-digg-count", type=int, help="候选作品最低点赞数")
    parser.add_argument("--max-comment-count", type=int, help="候选作品最高评论数")
    parser.add_argument("--candidate-pool-size", type=int, help="候选池大小")
    parser.add_argument(
        "--content-strategy", choices=["engagement", "latest", "hashtag"],
        help="内容策略：互动、最新或话题",
    )
    parser.add_argument("--batch-size", type=int, help="每次任务评论作品数")
    parser.add_argument("--batch-interval-seconds", type=int, help="批量评论间隔秒数")


def upsert_account(store, args):
    existing = store.get_account(args.account_id) if args.command == "set" else None
    if args.command == "set" and not existing:
        raise ValueError("账号不存在")
    values = {
        "name": existing["name"] if existing else args.name,
        "profile_id": existing.get("profile_id") or "" if existing else "",
        "profile_no": existing.get("profile_no") or "" if existing else "",
        "browser_type": existing["browser_type"] if existing else "adspower",
        "cdp_url": existing.get("cdp_url") or "" if existing else "",
        "proxy_url": existing.get("proxy_url") or "" if existing else "",
        "keywords": existing["keywords"] if existing else [],
        "comment_texts": existing["comment_texts"] if existing else [],
        "image_paths": existing["image_paths"] if existing else [],
        "enabled": existing["enabled"] if existing else True,
        "per_hour_limit": existing["per_hour_limit"] if existing else 5,
        "per_day_limit": existing["per_day_limit"] if existing else 20,
        "min_digg_count": existing["min_digg_count"] if existing else 100,
        "max_comment_count": existing["max_comment_count"] if existing else 100,
        "candidate_pool_size": existing["candidate_pool_size"] if existing else 20,
        "content_strategy": existing["content_strategy"] if existing else "engagement",
        "batch_size": existing["batch_size"] if existing else 1,
        "batch_interval_seconds": existing["batch_interval_seconds"] if existing else 15,
    }
    for field in (
        "name", "profile_id", "profile_no", "browser_type", "cdp_url", "proxy_url",
        "enabled", "per_hour_limit", "per_day_limit", "min_digg_count",
        "max_comment_count", "candidate_pool_size", "content_strategy", "batch_size",
        "batch_interval_seconds",
    ):
        incoming = getattr(args, field, None)
        if incoming is not None:
            values[field] = incoming
    for field, split_commas in (
        ("keywords", True), ("comment_texts", False), ("image_paths", False),
    ):
        parsed = string_list(getattr(args, field), split_commas=split_commas)
        if parsed is not None:
            values[field] = parsed
    account_id = args.account_id or (existing["id"] if existing else "")
    account = store.upsert_account(
        values["name"], values["profile_id"], values["profile_no"],
        account_id=account_id, browser_type=values["browser_type"],
        cdp_url=values["cdp_url"], proxy_url=values["proxy_url"],
        keywords=values["keywords"], comment_texts=values["comment_texts"],
        image_paths=values["image_paths"], enabled=values["enabled"],
        per_hour_limit=values["per_hour_limit"], per_day_limit=values["per_day_limit"],
        min_digg_count=values["min_digg_count"], max_comment_count=values["max_comment_count"],
        candidate_pool_size=values["candidate_pool_size"],
        content_strategy=values["content_strategy"], batch_size=values["batch_size"],
        batch_interval_seconds=values["batch_interval_seconds"],
    )
    return {"status": "saved", "account": account}


def run_once(store, account_id, *, dry_run=True, confirm=False, aweme_id="", keyword=""):
    if not dry_run and not confirm:
        raise ValueError("真实评论必须同时使用 --live --confirm")
    command = [sys.executable, "-m", "dy_mcp.worker", account_id]
    if not dry_run:
        command.append("--live")
    if aweme_id:
        command.extend(["--aweme-id", aweme_id])
    if keyword:
        command.extend(["--keyword", keyword])
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=360)
    lines = result.stdout.strip().splitlines()
    if not lines:
        raise RuntimeError(f"账号工作进程没有返回结果: {result.stderr[-2000:]}")
    response = json.loads(lines[-1])
    if result.returncode != 0:
        raise RuntimeError(f"账号工作进程失败: {response}")
    return response


def run_engagement(args):
    from .session import DouyinSession
    from .workflow import EngagementWorkflow

    return EngagementWorkflow(DouyinSession()).run(
        args.query, args.comment_text, args.message_text,
        image_path=args.image_path, limit=args.limit, dry_run=not args.live,
        confirm=args.confirm, sort_type=args.sort_type, publish_time=args.publish_time,
        interval_seconds=args.interval_seconds,
    )


def refresh_runtime(store, account_id):
    from dotenv import load_dotenv

    from .browser_runtime import collect_runtime_for_account

    load_dotenv()
    account = store.get_account(account_id)
    if not account:
        raise ValueError("账号不存在")
    runtime_env, runtime_info = collect_runtime_for_account(account)
    saved_at = store.save_runtime(account_id, runtime_env, runtime_info)
    store.set_account_status(account_id, "active")
    return {
        "status": "saved",
        "account_id": account_id,
        "account_name": account["name"],
        "runtime_saved_at": saved_at,
        "profile": runtime_info,
    }


def list_adspower_profiles():
    from dotenv import load_dotenv

    from .adspower import AdsPowerMCP

    load_dotenv()
    profiles = AdsPowerMCP().list_profiles()
    return {"count": len(profiles), "profiles": profiles}


def local_browser_manager():
    from .local_browser import LocalBrowserManager

    return LocalBrowserManager()


def camoufox_browser_manager():
    from .camoufox_browser import CamoufoxManager

    return CamoufoxManager()


def browser_managers():
    return [local_browser_manager(), camoufox_browser_manager()]


def find_browser_profile(name):
    matches = []
    for manager in browser_managers():
        try:
            matches.append((manager, manager.get(name)))
        except ValueError:
            continue
    if not matches:
        raise ValueError(f"本地浏览器环境不存在: {name}")
    if len(matches) > 1:
        raise ValueError(f"多个后端存在同名环境: {name}")
    return matches[0]


def browser_fingerprint(args):
    languages = args.languages.replace("，", ",").split(",") if args.languages else None
    return {
        "ua": args.user_agent,
        "platform": args.platform,
        "languages": [item.strip() for item in languages if item.strip()] if languages else None,
        "cpu": args.cpu,
        "memory": args.memory,
        "timezone": args.timezone,
        "screen": {
            "width": args.screen_width, "height": args.screen_height,
            "availWidth": args.avail_width, "availHeight": args.avail_height,
        },
        "window": {
            "innerWidth": args.window_width, "innerHeight": args.window_height,
            "outerWidth": args.window_width, "outerHeight": args.window_height,
        },
        "webgl": {"vendor": args.webgl_vendor, "renderer": args.webgl_renderer},
    }


def bind_browser_account(store, account_id, profile):
    account = store.get_account(account_id)
    if not account:
        raise ValueError("账号不存在")
    saved = store.upsert_account(
        account["name"], account_id=account_id, browser_type=profile.get("engine", "chrome"),
        cdp_url=profile["cdp_url"], proxy_url=profile["proxy_url"],
        keywords=account["keywords"], comment_texts=account["comment_texts"],
        image_paths=account["image_paths"], enabled=account["enabled"],
        per_hour_limit=account["per_hour_limit"], per_day_limit=account["per_day_limit"],
        min_digg_count=account["min_digg_count"], max_comment_count=account["max_comment_count"],
        candidate_pool_size=account["candidate_pool_size"],
        content_strategy=account["content_strategy"], batch_size=account["batch_size"],
        batch_interval_seconds=account["batch_interval_seconds"],
    )
    return {"status": "saved", "local_profile": profile["name"], "account": saved}


def create_camoufox_profile(manager, args):
    unsupported = {
        "--user-agent": args.user_agent,
        "--cpu": args.cpu,
        "--memory": args.memory,
        "--avail-width": args.avail_width,
        "--avail-height": args.avail_height,
        "--webgl-vendor": args.webgl_vendor,
        "--webgl-renderer": args.webgl_renderer,
        "--timezone": args.timezone,
    }
    used = [name for name, value in unsupported.items() if value is not None]
    if used:
        raise ValueError(f"Camoufox 由内核统一管理这些字段，请勿使用: {', '.join(used)}")
    if bool(args.window_width) != bool(args.window_height):
        raise ValueError("Camoufox 的 --window-width 和 --window-height 必须同时设置")
    from .fingerprint_generator import host_operating_system

    languages = args.languages.replace("，", ",").split(",") if args.languages else None
    return manager.create(
        args.name, args.port, executable=args.executable or "",
        proxy_url=args.proxy_url or "", os_name=host_operating_system(args.platform),
        languages=[item.strip() for item in languages if item.strip()] if languages else None,
        screen={key: value for key, value in {
            "width": args.screen_width, "height": args.screen_height,
        }.items() if value is not None},
        window={"width": args.window_width, "height": args.window_height} if args.window_width else None,
    )


def browser_command(store, args):
    action = args.browser_command
    if action == "create":
        manager = camoufox_browser_manager() if args.engine == "camoufox" else local_browser_manager()
        for backend in browser_managers():
            for existing in backend.list():
                if existing["name"] == args.name or existing["port"] == args.port:
                    raise ValueError("环境名称或端口已被其他本地环境使用")
        if args.engine == "camoufox":
            profile = create_camoufox_profile(manager, args)
        else:
            profile = manager.create(
                args.name, args.port, executable=args.executable or "",
                proxy_url=args.proxy_url or "", fingerprint=browser_fingerprint(args),
            )
        if args.start:
            profile = manager.start(args.name)
            return {"status": "started", "profile": profile}
        return {"status": "created", "profile": manager.public(profile, running=False)}
    if action == "list":
        profiles = []
        for manager in browser_managers():
            profiles.extend(manager.list_status())
        return {"count": len(profiles), "profiles": profiles}
    manager, _profile = find_browser_profile(args.name)
    if action == "start":
        return {"status": "started", "profile": manager.start(args.name)}
    if action == "stop":
        return {"status": "stopped", "profile": manager.stop(args.name)}
    if action in {"show", "status"}:
        return {"profile": manager.status(args.name)}
    if action == "bind":
        return bind_browser_account(store, args.account_id, manager.get(args.name))
    raise ValueError("未知浏览器命令")


def account_list(store, scheduler):
    accounts = store.list_accounts()
    return {"count": len(accounts), "accounts": accounts, "scheduler": scheduler.status()}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="douyin-cli",
        description="独立配置和运行抖音评论，不需要启动 Agent 或 MCP。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python douyin_cli.py account set 账号ID --keywords 'AI,Claude Code'\n"
            "  python douyin_cli.py once 账号ID --keyword 'Claude Code'\n"
            "  python douyin_cli.py engage 'Claude Code' --image-paths poster.png\n"
            "  python douyin_cli.py start --live --confirm\n"
            "  python douyin_cli.py status"
        ),
    )
    parser.add_argument("--db", help="可选 SQLite 数据库路径")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="启动独立后台调度")
    add_scheduler_options(start)

    run = commands.add_parser("run", help="在前台运行调度，Ctrl+C 停止")
    add_scheduler_options(run)

    config = commands.add_parser("config", help="修改调度配置，不启动新进程")
    add_scheduler_options(config)
    state = config.add_mutually_exclusive_group()
    state.add_argument("--enable", dest="enabled", action="store_true", help="启用定时执行")
    state.add_argument("--disable", dest="enabled", action="store_false", help="禁用定时执行")
    config.set_defaults(enabled=None)

    commands.add_parser("stop", help="停止后台调度并禁用定时执行")
    commands.add_parser("status", help="查看后台进程与调度配置")
    commands.add_parser("accounts", help="查看账号、限额和最近执行状态")
    commands.add_parser("profiles", help="列出 AdsPower 浏览器环境")

    browser = commands.add_parser("browser", help="管理不依赖 AdsPower 的本地指纹浏览器")
    browser_commands = browser.add_subparsers(dest="browser_command", required=True)
    browser_create = browser_commands.add_parser("create", help="创建固定指纹和独立目录")
    browser_create.add_argument("name", help="环境名称，字母/数字/下划线/连字符")
    browser_create.add_argument("--engine", choices=["chrome", "camoufox"], default="chrome", help="浏览器后端")
    browser_create.add_argument("--port", type=int, required=True, help="独立 CDP 或 Camoufox 控制端口")
    browser_create.add_argument("--executable", help="浏览器可执行文件路径")
    browser_create.add_argument("--proxy-url", help="独立代理，可包含用户名和密码")
    browser_create.add_argument("--user-agent", help="固定 User-Agent")
    browser_create.add_argument("--platform", help="navigator.platform，例如 MacIntel 或 Win32")
    browser_create.add_argument("--languages", help="语言，逗号分隔，例如 zh-CN,zh")
    browser_create.add_argument("--cpu", type=int, help="navigator.hardwareConcurrency")
    browser_create.add_argument("--memory", type=int, help="navigator.deviceMemory")
    browser_create.add_argument("--screen-width", type=int, help="屏幕宽度")
    browser_create.add_argument("--screen-height", type=int, help="屏幕高度")
    browser_create.add_argument("--avail-width", type=int, help="可用屏幕宽度")
    browser_create.add_argument("--avail-height", type=int, help="可用屏幕高度")
    browser_create.add_argument("--window-width", type=int, help="窗口宽度")
    browser_create.add_argument("--window-height", type=int, help="窗口高度")
    browser_create.add_argument("--webgl-vendor", help="WebGL vendor")
    browser_create.add_argument("--webgl-renderer", help="WebGL renderer")
    browser_create.add_argument("--timezone", help="时区，例如 Asia/Shanghai")
    browser_create.add_argument("--start", action="store_true", help="创建后立即启动")
    for action in ("start", "stop", "show", "status"):
        browser_action = browser_commands.add_parser(action, help=f"{action} 本地浏览器环境")
        browser_action.add_argument("name")
    browser_commands.add_parser("list", help="列出本地浏览器环境")
    browser_bind = browser_commands.add_parser("bind", help="把本地环境绑定到现有评论账号")
    browser_bind.add_argument("name")
    browser_bind.add_argument("account_id")

    account = commands.add_parser("account", help="创建或修改账号配置")
    account_commands = account.add_subparsers(dest="command", required=True)
    create = account_commands.add_parser("create", help="创建账号")
    create.add_argument("--account-id", default="", help="可选自定义账号 ID")
    add_account_options(create, creating=True)
    update = account_commands.add_parser("set", help="更新账号，未填参数保持原值")
    update.add_argument("account_id")
    add_account_options(update)
    account_commands.add_parser("list", help="列出账号")
    show = account_commands.add_parser("show", help="查看单个账号")
    show.add_argument("account_id")

    activity = commands.add_parser("activity", help="查看评论执行历史")
    activity.add_argument("--account-id", default="", help="只查看指定账号")
    activity.add_argument("--limit", type=int, default=20, help="返回条数，1 到 200")

    once = commands.add_parser("once", help="用指定账号执行一次，默认只预览")
    once.add_argument("account_id")
    once.add_argument("--keyword", default="", help="临时指定本次搜索关键词")
    once.add_argument("--aweme-id", default="", help="可选指定抖音作品 ID")
    add_execution_options(once)

    engage = commands.add_parser("engage", help="使用 .env 单账号搜索、评论和可选私信")
    engage.add_argument("query", help="搜索关键词")
    engage.add_argument("--comment-text", default="", help="评论文字")
    engage.add_argument("--message-text", default="", help="可选私信作者文字")
    engage.add_argument("--image-path", "--image-paths", dest="image_path", default="", help="评论图片路径")
    engage.add_argument("--limit", type=int, default=3, help="最多处理作品数，1 到 20")
    engage.add_argument("--sort-type", choices=["0", "1", "2"], default="0", help="0 综合、1 点赞、2 最新")
    engage.add_argument(
        "--publish-time", choices=["0", "1", "7", "180"], default="0",
        help="0 不限、1 一天、7 一周、180 半年",
    )
    engage.add_argument("--interval-seconds", type=float, default=3.0, help="作品间隔秒数")
    add_execution_options(engage)

    refresh = commands.add_parser("refresh", help="从已登录浏览器刷新账号凭证")
    refresh.add_argument("account_id")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        store = AccountStore(args.db) if args.db else AccountStore()
        scheduler = SchedulerController(store)
        if args.command == "start":
            dry_run = selected_dry_run(args)
            validate_live_confirmation(store, args, dry_run)
            result = scheduler.configure(
                "start", enabled=True, dry_run=dry_run,
                confirm=args.confirm, **scheduler_values(args),
            )
        elif args.command == "run":
            dry_run = selected_dry_run(args)
            validate_live_confirmation(store, args, dry_run)
            scheduler.configure(
                "status", enabled=True, dry_run=dry_run,
                confirm=args.confirm, **scheduler_values(args),
            )
            print_json({
                "status": "started",
                "foreground": True,
                "settings": store.settings(),
                "database": str(store.path),
            })
            run_scheduler(store)
            return 0
        elif args.command == "config":
            dry_run = selected_dry_run(args)
            if dry_run is not None or args.enabled is True:
                validate_live_confirmation(store, args, dry_run)
            result = scheduler.configure(
                "status", enabled=args.enabled, dry_run=dry_run,
                confirm=args.confirm, **scheduler_values(args),
            )
        elif args.command == "stop":
            result = scheduler.configure("stop")
        elif args.command == "status":
            result = scheduler.status()
        elif args.command in {"accounts", "list"}:
            result = account_list(store, scheduler)
        elif args.command == "profiles":
            result = list_adspower_profiles()
        elif args.command == "browser":
            result = browser_command(store, args)
        elif args.command in {"create", "set"}:
            result = upsert_account(store, args)
        elif args.command == "show":
            account = store.get_account(args.account_id)
            if not account:
                raise ValueError("账号不存在")
            result = {"account": account}
        elif args.command == "activity":
            if not 1 <= args.limit <= 200:
                raise ValueError("--limit 必须在 1 到 200 之间")
            runs = store.recent_runs(limit=args.limit, account_id=args.account_id)
            result = {"count": len(runs), "runs": runs}
        elif args.command == "once":
            result = run_once(
                store, args.account_id, dry_run=not args.live,
                confirm=args.confirm, aweme_id=args.aweme_id, keyword=args.keyword,
            )
        elif args.command == "engage":
            result = run_engagement(args)
        elif args.command == "refresh":
            result = refresh_runtime(store, args.account_id)
        else:
            raise ValueError("未知命令")
        print_json(result)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print_json({"status": "error", "error": str(error)}, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
