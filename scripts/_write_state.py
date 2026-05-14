#!/usr/bin/env python3
# Atomic state.json writer shared by upgrade.sh and watch_health.sh.
# Args: <phase> <message> <new_version> <old_version> <state_file>
import json
import os
import sys
from datetime import datetime, timezone

phase, message, new_v, old_v, path = sys.argv[1:]
os.makedirs(os.path.dirname(path), exist_ok=True)
data = {
    "phase": phase,
    "current_version": old_v or None,
    "target_version": new_v or None,
    "channel": None,
    "pct": 0,
    "message": message or None,
    "started_at": None,
    "finished_at": (
        datetime.now(timezone.utc).isoformat()
        if phase in ("success", "failed", "rolled_back")
        else None
    ),
}
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f)
os.replace(tmp, path)
