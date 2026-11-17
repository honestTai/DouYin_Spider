import json
import subprocess
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

from .scheduler import SchedulerController
from .session import DouyinSession
from .store import AccountStore, ROOT
from .workflow import EngagementWorkflow


mcp = FastMCP(
    "douyin-engagement",
    instructions=(
        "提供抖音搜索评论、AdsPower 多账号管理、SQLite 数据查询和定时调度。"
        "默认 dry_run=true；真实评论或真实调度必须显式传入 dry_run=false、confirm=true。"
    ),
)
workflow = EngagementWorkflow(DouyinSession())
store = AccountStore()
scheduler = SchedulerController(store)


@mcp.tool()
async def list_adspower_profiles() -> dict:
    """列出 AdsPower 浏览器环境，用于绑定账号；不返回代理密码或 Cookie。"""
    from .adspower import AdsPowerMCP

    profiles = await AdsPowerMCP().list_profiles_async()
    return {"count": len(profiles), "profiles": profiles}


@mcp.tool()
def upsert_account(
    name: str,
    keywords: list[str],
    comment_texts: list[str] = [],
    image_paths: list[str] = [],
    profile_id: str = "",
    profile_no: str = "",
    account_id: str = "",
    browser_type: str = "adspower",
    cdp_url: str = "",
    proxy_url: str = "",
    enabled: bool = True,
    per_hour_limit: int = 5,
    per_day_limit: int = 20,
    min_digg_count: int = 100,
    max_comment_count: int = 100,
    candidate_pool_size: int = 20,
    content_strategy: str = "engagement",
    batch_size: int = 1,
    batch_interval_seconds: int = 15,
) -> dict:
    """新增或更新账号，绑定 AdsPower、WebBridge、Chrome、Edge 或 Firefox 环境。"""
    account = store.upsert_account(
        name, profile_id, profile_no, account_id=account_id,
        browser_type=browser_type, cdp_url=cdp_url, proxy_url=proxy_url,
        keywords=keywords, comment_texts=comment_texts, image_paths=image_paths, enabled=enabled,
        per_hour_limit=per_hour_limit, per_day_limit=per_day_limit,
        min_digg_count=min_digg_count, max_comment_count=max_comment_count,
        candidate_pool_size=candidate_pool_size, content_strategy=content_strategy,
        batch_size=batch_size, batch_interval_seconds=batch_interval_seconds,
    )
    return {"status": "saved", "account": account}


@mcp.tool()
def refresh_account_runtime(account_id: str) -> dict:
    """从已登录浏览器刷新并保存账号凭证；日常调度不会访问浏览器，也不返回凭证内容。"""
    from .browser_runtime import collect_runtime_for_account

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
        "message": "登录凭证已保存；后续调度直接复用，Cookie 失效时重新调用本工具",
    }


@mcp.tool()
def list_accounts() -> dict:
    """显示所有账号的环境绑定、状态、小时/每日评论数和最近执行结果。"""
    accounts = store.list_accounts()
    return {"count": len(accounts), "accounts": accounts, "scheduler": scheduler.status()}


@mcp.tool()
def run_account_once(account_id: str, dry_run: bool = True, confirm: bool = False,
                     aweme_id: str = "") -> dict:
    """用指定账号执行一次搜索或 aweme_id 定向图片评论；默认只预览。"""
    if not dry_run and not confirm:
        raise ValueError("真实评论必须同时设置 dry_run=false 和 confirm=true")
    command = [sys.executable, "-m", "dy_mcp.worker", account_id]
    if not dry_run:
        command.append("--live")
    if aweme_id:
        command.extend(["--aweme-id", aweme_id])
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=360)
    lines = result.stdout.strip().splitlines()
    if not lines:
        raise RuntimeError(f"账号工作进程没有返回结果: {result.stderr[-2000:]}")
    response = json.loads(lines[-1])
    if result.returncode != 0:
        raise RuntimeError(f"账号工作进程失败: {response}")
    return response


@mcp.tool()
def configure_scheduler(
    action: str = "status",
    enabled: bool | None = None,
    dry_run: bool | None = None,
    global_per_hour: int | None = None,
    min_interval_seconds: int | None = None,
    poll_seconds: int | None = None,
    confirm: bool = False,
) -> dict:
    """查询、启动或停止独立定时调度；真实评论调度需要 dry_run=false、confirm=true。"""
    return scheduler.configure(
        action, enabled=enabled, dry_run=dry_run,
        global_per_hour=global_per_hour, min_interval_seconds=min_interval_seconds,
        poll_seconds=poll_seconds, confirm=confirm,
    )


@mcp.tool()
def list_activity(account_id: str = "", limit: int = 50) -> dict:
    """查询账号搜索评论历史、候选数量、选中作品和失败原因。"""
    if not 1 <= limit <= 200:
        raise ValueError("limit 必须在 1 到 200 之间")
    runs = store.recent_runs(limit=limit, account_id=account_id)
    return {"count": len(runs), "runs": runs}


@mcp.tool()
def run_engagement(
    query: str,
    comment_text: str = "",
    message_text: str = "",
    image_path: str = "",
    limit: int = 3,
    dry_run: bool = True,
    confirm: bool = False,
    sort_type: str = "0",
    publish_time: str = "0",
    interval_seconds: float = 3.0,
) -> dict:
    """搜索相关抖音作品，逐个评论，并可选择私信作者。

    query: 搜索关键词。
    comment_text: 发布到每个作品评论区的相同文本；使用图片评论时可留空。
    message_text: 发送给每个作品作者的相同私信文本；留空则只评论，不私信。
    image_path: 可选图片路径，支持 png、jpeg、webp、bmp，最大 10MB。
    limit: 本次最多处理的作品数，范围 1-20。
    dry_run: true 时只搜索并预览，不产生任何写操作。
    confirm: 真实执行确认；必须同时设置 dry_run=false 和 confirm=true。
    sort_type: 0 综合排序、1 最多点赞、2 最新发布。
    publish_time: 0 不限、1 一天内、7 一周内、180 半年内。
    interval_seconds: 每个作品之间的等待秒数，范围 0-60。
    任一作品执行失败后立即停止；结果会标明评论和私信各自的状态。
    """
    return workflow.run(
        query,
        comment_text,
        message_text,
        image_path=image_path,
        limit=limit,
        dry_run=dry_run,
        confirm=confirm,
        sort_type=sort_type,
        publish_time=publish_time,
        interval_seconds=interval_seconds,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
