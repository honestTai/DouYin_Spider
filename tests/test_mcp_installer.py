import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

from dy_mcp import install


def test_launcher_uses_current_python_and_absolute_project_entrypoint():
    command = install.launch_command()

    assert command[0] == str(Path(sys.executable).absolute())
    assert command[1] == str(install.ROOT / "mcp_server.py")
    assert Path(command[1]).is_absolute()


def test_kimi_install_merges_existing_servers(tmp_path):
    path = tmp_path / ".kimi-code" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"existing": {"command": "existing"}}}))

    message = install.install_kimi(tmp_path)

    config = json.loads(path.read_text())
    assert config["mcpServers"]["existing"] == {"command": "existing"}
    server = config["mcpServers"][install.SERVER_NAME]
    assert server["args"] == [str(tmp_path / "mcp_server.py")]
    assert server["enabledTools"] == ["run_engagement"]
    assert str(path) in message


def test_generic_config_contains_only_portable_stdio_fields():
    config = json.loads(install.generic_config())
    server = config["mcpServers"][install.SERVER_NAME]

    assert set(server) == {"command", "args", "cwd"}


@patch("dy_mcp.install.subprocess.run")
@patch("dy_mcp.install.shutil.which", return_value="/usr/local/bin/codex")
def test_codex_install_uses_official_mcp_add_command(_which, run):
    assert install.install_codex().startswith("Codex:")

    command = run.call_args.args[0]
    assert command[:4] == ["/usr/local/bin/codex", "mcp", "add", install.SERVER_NAME]
    assert command[4] == "--"
    assert command[5:] == install.launch_command()
    run.assert_called_once_with(command, cwd=install.ROOT, check=True)


@patch("dy_mcp.install.subprocess.run")
@patch("dy_mcp.install.shutil.which", return_value="/usr/local/bin/claude")
def test_claude_install_uses_project_local_stdio_scope(_which, run):
    assert install.install_claude().startswith("Claude Code:")

    command = run.call_args.args[0]
    assert command[:7] == [
        "/usr/local/bin/claude", "mcp", "add", "--transport", "stdio",
        "--scope", "local",
    ]
    assert command[7:10] == [install.SERVER_NAME, "--", sys.executable]
    run.assert_called_once_with(command, cwd=install.ROOT, check=True)


@patch("dy_mcp.install.shutil.which", return_value=None)
def test_missing_agent_cli_has_clear_error(_which):
    try:
        install.install_codex()
    except RuntimeError as error:
        assert "未找到 codex CLI" in str(error)
    else:
        raise AssertionError("missing CLI should fail")


@patch("dy_mcp.install.install_claude", side_effect=subprocess.CalledProcessError(1, "claude"))
@patch("dy_mcp.install.install_codex", side_effect=RuntimeError("missing"))
@patch("dy_mcp.install.install_kimi", return_value="Kimi Code: installed")
def test_all_continues_after_unavailable_agents(kimi, _codex, _claude):
    assert install.main(["--agent", "all"]) == 1
    kimi.assert_called_once_with()
