#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
state_file="$repo_root/data/state.json"
if [[ ! -f "$state_file" ]]; then
  echo "state file missing: $state_file" >&2
  exit 1
fi

git fetch origin data:refs/remotes/origin/data 2>/dev/null || true
persist_root="$(mktemp -d)"
persist_worktree="$persist_root/data-worktree"
cleanup() {
  git -C "$repo_root" worktree remove --force "$persist_worktree" >/dev/null 2>&1 || true
  git -C "$repo_root" worktree prune >/dev/null 2>&1 || true
}
trap cleanup EXIT

if git show-ref --verify --quiet refs/remotes/origin/data; then
  git worktree add --detach "$persist_worktree" refs/remotes/origin/data
  git -C "$persist_worktree" switch -C data
else
  git worktree add --detach "$persist_worktree" HEAD
  git -C "$persist_worktree" switch --orphan data
  git -C "$persist_worktree" read-tree --empty
fi

mkdir -p "$persist_worktree/exports"
cp "$state_file" "$persist_worktree/state.json"
if [[ -d "$repo_root/public/data" ]]; then
  cp "$repo_root/public/data/inventory.json" "$persist_worktree/exports/inventory.json"
  cp "$repo_root/public/data/inventory.csv" "$persist_worktree/exports/inventory.csv"
  cp "$repo_root/public/data/status.json" "$persist_worktree/exports/status.json"
  cp "$repo_root/public/data/events.json" "$persist_worktree/exports/events.json"
fi

git -C "$persist_worktree" config user.name "freitag-watch[bot]"
git -C "$persist_worktree" config user.email "freitag-watch[bot]@users.noreply.github.com"
git -C "$persist_worktree" add state.json exports 2>/dev/null || git -C "$persist_worktree" add state.json
if git -C "$persist_worktree" diff --cached --quiet; then
  echo "data branch unchanged"
  exit 0
fi
git -C "$persist_worktree" commit -m "data: update inventory state"
git -C "$persist_worktree" push origin HEAD:data

