"""Attach each Log Analytics workspace's daily cap to its row in an `az resource list` export.

`az resource list` carries no properties, so cost_guard's C6 cap check would always fail; the
deploy workflow exports workspaces separately and merges them here before running the guard.
"""

import json
import sys


def main(inventory_path: str, workspaces_path: str) -> None:
    with open(inventory_path) as f:
        inventory = json.load(f)
    with open(workspaces_path) as f:
        caps = {w["name"]: w.get("workspaceCapping") for w in json.load(f)}
    for item in inventory:
        if item.get("type", "").lower() == "microsoft.operationalinsights/workspaces":
            item["workspaceCapping"] = caps.get(item.get("name"))
    with open(inventory_path, "w") as f:
        json.dump(inventory, f)


if __name__ == "__main__":
    main(*sys.argv[1:3])
