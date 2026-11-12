"""macOS LaunchAgents: the daily `jobhunt fetch` (every account, one after another) and, optionally, the dashboard
kept running in the background."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .core import ROOT, USERS, data_dir, multi_user

LABEL = "local.jobhunt.fetch"
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"


def _logs() -> Path:
    return USERS if multi_user() else data_dir()


def install(hour: int) -> str:
    uv = shutil.which("uv") or "/opt/homebrew/bin/uv"
    DATA = _logs()
    PLIST.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{uv}</string><string>run</string><string>--project</string><string>{ROOT}</string>
    <string>jobhunt</string><string>fetch</string>
  </array>
  <key>WorkingDirectory</key><string>{ROOT}</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>{DATA}/fetch.log</string>
  <key>StandardErrorPath</key><string>{DATA}/fetch.log</string>
</dict></plist>
""")
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
    subprocess.run(["launchctl", "load", str(PLIST)], check=True)
    return f"Scheduled daily fetch at {hour:02d}:00 (log: {DATA}/fetch.log). Remove with: launchctl unload {PLIST}"


SERVER_LABEL = "local.jobhunt.serve"
SERVER_PLIST = Path.home() / "Library/LaunchAgents" / f"{SERVER_LABEL}.plist"


def install_server(host: str, port: int) -> str:
    uv = shutil.which("uv") or "/opt/homebrew/bin/uv"
    log = _logs() / "serve.log"
    SERVER_PLIST.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{SERVER_LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{uv}</string><string>run</string><string>--project</string><string>{ROOT}</string>
    <string>jobhunt</string><string>serve</string><string>--host</string><string>{host}</string>
    <string>--port</string><string>{port}</string>
  </array>
  <key>WorkingDirectory</key><string>{ROOT}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
""")
    subprocess.run(["launchctl", "unload", str(SERVER_PLIST)], capture_output=True)
    subprocess.run(["launchctl", "load", str(SERVER_PLIST)], check=True)
    return (f"The dashboard now runs in the background on {host}:{port}, and starts again after a restart "
            f"(log: {log}). Stop it with: launchctl unload {SERVER_PLIST}")
