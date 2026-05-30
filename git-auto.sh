#!/usr/bin/env bash
# Auto-commit and push for the x-agent workspace (X For You algorithm sources).
#
# Env overrides:
#   AUTO_PUSH_BRANCH          branch to push (default: current)
#   AUTO_PUSH_DEBOUNCE        seconds after last change (default: 3)
#   AUTO_PUSH_COMMIT_PREFIX   commit message prefix (default: x-agent: sync)
#   AUTO_PUSH_WATCH_DIR       directory to watch (default: script dir)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCH_DIR="${AUTO_PUSH_WATCH_DIR:-$SCRIPT_DIR}"

if ! command -v inotifywait >/dev/null 2>&1; then
  echo "Missing dependency: inotifywait"
  echo "Install with: sudo apt-get install inotify-tools"
  exit 1
fi

if ! git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "No git repository found for x-agent."
  echo "Initialize from this directory, for example:"
  echo "  cd $SCRIPT_DIR && git init && git remote add origin <url>"
  exit 1
fi

GIT_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

if ! git -C "$GIT_ROOT" remote get-url origin >/dev/null 2>&1; then
  echo "Git remote 'origin' is not configured."
  exit 1
fi

BRANCH="${AUTO_PUSH_BRANCH:-$(git -C "$GIT_ROOT" branch --show-current)}"
DEBOUNCE_SECONDS="${AUTO_PUSH_DEBOUNCE:-3}"
COMMIT_PREFIX="${AUTO_PUSH_COMMIT_PREFIX:-x-agent: sync}"
LOCK_DIR="$GIT_ROOT/.git/.auto-push-lock"

# Paths that should not trigger commits (multi-GB LFS / build outputs).
PHOENIX_ARTIFACT_PATHS=(
  phoenix/artifacts
  x-algorithm-main/phoenix/artifacts
)

INOTIFY_EXCLUDE='(\.git/|node_modules/|\.venv/|\.uv/|dist/|build/|target/|\.next/|__pycache__/|\.pytest_cache/|\.mypy_cache/|\.ruff_cache/|\.coverage|htmlcov/|phoenix/artifacts/|oss-phoenix-artifacts/|\.DS_Store$|.*\.swp$|.*~$|\.ss$)'

if [[ -z "$BRANCH" ]]; then
  echo "Could not detect the current git branch."
  exit 1
fi

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "x-agent auto push watcher is already running."
  exit 1
fi

cleanup() {
  rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

unstage_phoenix_artifacts() {
  local rel
  for rel in "${PHOENIX_ARTIFACT_PATHS[@]}"; do
    if [[ -e "$GIT_ROOT/$rel" ]] || git -C "$GIT_ROOT" ls-files --error-unmatch "$rel" >/dev/null 2>&1; then
      git -C "$GIT_ROOT" reset HEAD -- "$rel" >/dev/null 2>&1 || true
    fi
  done
}

sync_changes() {
  git -C "$GIT_ROOT" add -A
  unstage_phoenix_artifacts

  if git -C "$GIT_ROOT" diff --cached --quiet; then
    return 0
  fi

  local commit_msg
  commit_msg="$COMMIT_PREFIX $(date '+%Y-%m-%d %H:%M:%S')"
  git -C "$GIT_ROOT" commit -m "$commit_msg"
  git -C "$GIT_ROOT" push origin "$BRANCH"
  echo "Pushed: $commit_msg"
}

echo "x-agent auto push watcher"
echo "  Git root:  $GIT_ROOT"
echo "  Watching:  $WATCH_DIR"
echo "  Branch:    $BRANCH"
echo "  Debounce:  ${DEBOUNCE_SECONDS}s"
echo "  Skipping:  phoenix/artifacts (LFS), target/, .venv/, build caches"
echo "Press Ctrl+C to stop."

sync_changes

while true; do
  inotifywait -qq -r \
    -e modify,create,delete,move \
    --exclude "$INOTIFY_EXCLUDE" \
    "$WATCH_DIR"

  sleep "$DEBOUNCE_SECONDS"
  sync_changes
done
