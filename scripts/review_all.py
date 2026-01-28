#!/usr/bin/env python3
"""
Codex Review Script for Multiple Commits
Runs codex review on each commit not in master, appending to a file.
Designed to run in tmux to avoid timeout issues.

Usage:
    python review_all.py                    # Review all commits not in master
    python review_all.py abc123 def456      # Review specific commits
    python review_all.py -- abc123..def456  # Review commit range
"""

import subprocess
import sys
import os
import argparse
from datetime import datetime
import time

MASTER_BRANCH = "master"
WORKTREE_PATH = ".worktrees/review-branch"
OUTPUT_FILE = "review_results/codex_reviews.txt"


def run_command(cmd, cwd=None, capture_output=True):
    """Run a shell command and return output."""
    result = subprocess.run(
        cmd, shell=True, cwd=cwd, capture_output=capture_output, text=True
    )
    return result.stdout, result.stderr, result.returncode


def get_commits_not_in_master(base_branch, worktree_path):
    """Get list of commits not in master (oldest first)."""
    stdout, stderr, rc = run_command(
        f"git log {base_branch}..HEAD --reverse --format='%H'", cwd=worktree_path
    )
    if rc != 0:
        print(f"Error getting commits: {stderr}", file=sys.stderr)
        return []
    return [c for c in stdout.strip().split("\n") if c]


def get_commit_info(commit_hash, worktree_path):
    """Get commit message for a hash."""
    stdout, _, _ = run_command(
        f"git log -1 --format='%s' {commit_hash}", cwd=worktree_path
    )
    return stdout.strip()


def review_commit(commit_hash, commit_msg, count, total, output_file, worktree_path):
    """Review a single commit and append to output file."""
    print(f"[{count}/{total}] Reviewing commit: {commit_msg}")

    # Write header
    header = f"""
{"=" * 60}
COMMIT {count}/{total}
SHA: {commit_hash}
Message: {commit_msg}
Timestamp: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
{"=" * 60}

"""
    with open(output_file, "a") as f:
        f.write(header)

    # Run codex review
    result = subprocess.run(
        ["codex", "review", "--commit", commit_hash],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )

    with open(output_file, "a") as f:
        f.write(result.stdout)
        if result.stderr:
            f.write("\nSTDERR:\n")
            f.write(result.stderr)
        f.write(f"\n{'=' * 60}\n--- END OF REVIEW ---\n{'=' * 60}\n\n")

    print(f"[{count}/{total}] Completed: {commit_msg}")
    return True


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Review commits using codex CLI.",
        epilog="If no commits are specified, reviews all commits not in master.",
    )
    parser.add_argument(
        "commits",
        nargs="*",
        help="Specific commit hashes or ranges to review (e.g., abc123 or abc123..def456)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=OUTPUT_FILE,
        help=f"Output file for reviews (default: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "--worktree",
        default=WORKTREE_PATH,
        help=f"Path to git worktree (default: {WORKTREE_PATH})",
    )
    parser.add_argument(
        "--base-branch",
        default=MASTER_BRANCH,
        help=f"Base branch to compare against (default: {MASTER_BRANCH})",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # Update paths from args
    worktree_path = args.worktree
    output_file = args.output
    base_branch = args.base_branch

    # Create output directory
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Initialize output file
    with open(output_file, "w") as f:
        f.write(
            f"Codex Code Reviews - Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        f.write("=" * 60 + "\n\n")

    # Get commits
    if args.commits:
        # Use specified commits
        commits = args.commits
        print(f"Reviewing {len(commits)} specified commit(s)")
    else:
        # Get all commits not in master
        commits = get_commits_not_in_master(base_branch, worktree_path)
        if not commits:
            print("No commits to review!")
            return 0
        print(f"Found {len(commits)} commits to review (not in {base_branch})")

    total = len(commits)
    print(f"Reviews will be saved to: {output_file}")
    print()

    # Review each commit
    for i, commit in enumerate(commits, 1):
        msg = get_commit_info(commit, worktree_path)
        review_commit(commit, msg, i, total, output_file, worktree_path)
        time.sleep(1)  # Small delay between reviews

    # Write summary
    with open(output_file, "a") as f:
        f.write(f"\n{'=' * 60}\n")
        f.write(f"ALL REVIEWS COMPLETE\n")
        f.write(f"Total: {total}\n")
        f.write(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'=' * 60}\n")

    print()
    print("=" * 60)
    print(f"All reviews completed!")
    print(f"Total: {total}")
    print(f"Output saved to: {output_file}")
    print("=" * 60)


if __name__ == "__main__":
    main()
