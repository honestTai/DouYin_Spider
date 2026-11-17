import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .store import AccountStore, ROOT


PID_PATH = ROOT / ".kimi-code" / "scheduler.pid"
LOG_PATH = ROOT / ".kimi-code" / "scheduler.log"


class SchedulerController:
    def __init__(self, store=None):
        self.store = store or AccountStore()

    def _pid(self):
        try:
            return int(PID_PATH.read_text().strip())
        except (OSError, ValueError):
            return 0

    def status(self):
        pid = self._pid()
        running = False
        if pid:
            try:
                os.kill(pid, 0)
                command = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    capture_output=True, text=True, timeout=5,
                ).stdout
                running = "dy_mcp.scheduler" in command
            except (OSError, subprocess.SubprocessError):
                running = False
        if pid and not running:
            PID_PATH.unlink(missing_ok=True)
            pid = 0
        return {
            "running": running,
            "pid": pid or None,
            "settings": self.store.settings(),
            "database": str(self.store.path),
            "log": str(LOG_PATH),
        }

    def configure(self, action="status", *, enabled=None, dry_run=None,
                  global_per_hour=None, min_interval_seconds=None,
                  poll_seconds=None, confirm=False):
        if global_per_hour is not None and not 1 <= global_per_hour <= 100:
            raise ValueError("global_per_hour 必须在 1 到 100 之间")
        if min_interval_seconds is not None and not 30 <= min_interval_seconds <= 86400:
            raise ValueError("min_interval_seconds 必须在 30 到 86400 之间")
        if poll_seconds is not None and not 5 <= poll_seconds <= 3600:
            raise ValueError("poll_seconds 必须在 5 到 3600 之间")
        if action == "start":
            enabled = True if enabled is None else enabled
            current = self.store.settings()
            live = dry_run if dry_run is not None else current.get("dry_run") != "false"
            if not live and not confirm:
                raise ValueError("启动真实评论调度必须显式设置 confirm=true")
        self.store.update_settings(
            enabled=enabled, dry_run=dry_run, global_per_hour=global_per_hour,
            min_interval_seconds=min_interval_seconds, poll_seconds=poll_seconds,
        )
        if action == "start":
            self.start()
        elif action == "stop":
            self.stop()
            self.store.update_settings(enabled=False)
        elif action != "status":
            raise ValueError("action 只支持 start、stop、status")
        return self.status()

    def start(self):
        current = self.status()
        if current["running"]:
            return current
        PID_PATH.parent.mkdir(parents=True, exist_ok=True)
        log = LOG_PATH.open("a", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, "-m", "dy_mcp.scheduler", "--db", str(self.store.path)],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log.close()
        PID_PATH.write_text(str(process.pid), encoding="utf-8")
        return self.status()

    def stop(self):
        pid = self._pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        PID_PATH.unlink(missing_ok=True)


def run_scheduler(store):
    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        settings = store.settings()
        if settings.get("enabled") != "true":
            time.sleep(int(settings.get("poll_seconds", "15")))
            continue
        account, reason = store.next_account(
            int(settings.get("global_per_hour", "20")),
            int(settings.get("min_interval_seconds", "180")),
        )
        if not account:
            time.sleep(int(settings.get("poll_seconds", "15")))
            continue
        command = [sys.executable, "-m", "dy_mcp.worker", account["id"]]
        if settings.get("dry_run") == "false":
            command.append("--live")
        started = time.time()
        try:
            result = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True, timeout=300,
            )
            output = result.stdout.strip().splitlines()
            print(json.dumps({
                "time": started,
                "account_id": account["id"],
                "returncode": result.returncode,
                "result": json.loads(output[-1]) if output else {},
                "stderr": result.stderr[-2000:],
            }, ensure_ascii=False), flush=True)
        except Exception as error:
            store.set_account_status(account["id"], "active", str(error))
            print(json.dumps({"account_id": account["id"], "error": str(error)}, ensure_ascii=False), flush=True)
        if running:
            time.sleep(int(settings.get("poll_seconds", "15")))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)
    store = AccountStore(args.db) if args.db else AccountStore()
    run_scheduler(store)


if __name__ == "__main__":
    main()
