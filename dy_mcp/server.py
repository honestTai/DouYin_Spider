from mcp.server.fastmcp import FastMCP

from .session import DouyinSession
from .workflow import EngagementWorkflow


mcp = FastMCP(
    "douyin-engagement",
    instructions=(
        "只提供关键词搜索作品、发布评论和私信作品作者的串行流程。"
        "默认 dry_run=true，只返回预览；真实执行必须显式传入 dry_run=false、confirm=true。"
    ),
)
workflow = EngagementWorkflow(DouyinSession())


@mcp.tool()
def run_engagement(
    query: str,
    comment_text: str,
    message_text: str,
    limit: int = 3,
    dry_run: bool = True,
    confirm: bool = False,
    sort_type: str = "0",
    publish_time: str = "0",
    interval_seconds: float = 3.0,
) -> dict:
    """搜索相关抖音作品，逐个评论并私信作者。

    query: 搜索关键词。
    comment_text: 发布到每个作品评论区的相同文本。
    message_text: 发送给每个作品作者的相同私信文本。
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
        limit=limit,
        dry_run=dry_run,
        confirm=confirm,
        sort_type=sort_type,
        publish_time=publish_time,
        interval_seconds=interval_seconds,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
