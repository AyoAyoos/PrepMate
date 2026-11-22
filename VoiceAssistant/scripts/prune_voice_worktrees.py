"""Prune stale voice-agent worktrees. Dry-run by default; nothing is deleted
unless you pass ``--apply``.

Each voice session gets a git worktree, which is a full checkout of the repo,
so old sessions accumulate hundreds of megabytes. This tool removes only
worktrees that are both older than ``--max-age-days`` (default 7) and have no
tracked edits or untracked files. Any worktree holding files the agent created
is always preserved so you can inspect it.

Run:
    .\\.venv\\Scripts\\python.exe scripts\\prune_voice_worktrees.py
    .\\.venv\\Scripts\\python.exe scripts\\prune_voice_worktrees.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.opencode_client import OpenCodeClient  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually remove the worktrees listed as prune candidates.",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=7,
        help="Only worktrees older than this many days can be pruned (default: 7).",
    )
    args = parser.parse_args()

    client = OpenCodeClient()
    root = client.worktree_root.resolve()
    print(f"Worktree root: {root}")
    if not root.exists():
        print("Nothing to prune.")
        await client.close()
        return 0

    report = client.worktree_cleanup_report(max_age_days=args.max_age_days)
    if not report:
        print("No voice worktrees found.")
        await client.close()
        return 0

    prune = [item for item in report if item["action"] == "prune"]
    for item in report:
        marker = "PRUNE" if item["action"] == "prune" else "KEEP "
        print(f"  {marker}  {item['reason']:<20} {item['path']}")

    if not args.apply:
        print(f"\nDry run: {len(prune)} candidate(s). Re-run with --apply to remove them.")
        await client.close()
        return 0

    print(f"\nRemoving {len(prune)} worktree(s)...")
    stats = await client.prune_stale_worktrees(max_age_days=args.max_age_days)
    print(
        "Result: "
        f"pruned={stats['pruned']} "
        f"kept(agent files)={stats['preserved_files']} "
        f"kept(recent)={stats['preserved_recent']} "
        f"failed={stats['failed']}"
    )
    await client.close()
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
