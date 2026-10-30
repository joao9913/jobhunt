"""Daily `jobhunt fetch` via a macOS LaunchAgent."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .core import DATA, ROOT

LABEL = "local.jobhunt.fetch"
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"


def install(hour: int) -> str:
    uv = shutil.which("uv") or "/opt/homebrew/bin/uv"
    DATA.mkdir(exist_ok=True)
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
