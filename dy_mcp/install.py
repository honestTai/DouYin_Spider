import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SERVER_NAME = "douyin-engagement"


def launch_command(root=ROOT):
    return [str(Path(sys.executable).absolute()), str(root / "mcp_server.py")]


def server_config(root=ROOT):
    command = launch_command(root)
    return {
        "command": command[0],
        "args": command[1:],
        "cwd": str(root),
        "enabled": True,
        "enabledTools": ["run_engagement"],
        "startupTimeoutMs": 30000,
        "toolTimeoutMs": 120000,
    }


def install_kimi(root=ROOT):
    path = root / ".kimi-code" / "mcp.json"
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8"))
    else:
        config = {}
    servers = config.setdefault("mcpServers", {})
    servers[SERVER_NAME] = server_config(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"Kimi Code: {path}"


def install_codex():
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError("未找到 codex CLI，请先安装并配置 Codex")
    command = [
        executable, "mcp", "add", SERVER_NAME, "--", *launch_command(),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    return "Codex: 已写入用户级 MCP 配置"


def install_claude():
    executable = shutil.which("claude")
    if not executable:
        raise RuntimeError("未找到 claude CLI，请先安装并配置 Claude Code")
    command = [
        executable, "mcp", "add", "--transport", "stdio", "--scope", "local",
        SERVER_NAME, "--", *launch_command(),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    return "Claude Code: 已写入当前项目的 local 配置"


def generic_config():
    config = server_config()
    portable = {key: config[key] for key in ("command", "args", "cwd")}
    return json.dumps(
        {"mcpServers": {SERVER_NAME: portable}},
        ensure_ascii=False, indent=2,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="安装抖音评论私信 MCP 到 Agent")
    parser.add_argument(
        "--agent",
        choices=("kimi", "codex", "claude", "all", "json"),
        required=True,
        help="目标 Agent；json 仅打印通用 MCP 配置",
    )
    args = parser.parse_args(argv)
    if args.agent == "json":
        print(generic_config())
        return 0

    agents = ("kimi", "codex", "claude") if args.agent == "all" else (args.agent,)
    installers = {"kimi": install_kimi, "codex": install_codex, "claude": install_claude}
    failed = False
    for agent in agents:
        try:
            print(installers[agent]())
        except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
            failed = True
            print(f"{agent} 安装失败: {error}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
