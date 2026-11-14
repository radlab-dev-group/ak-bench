#!/usr/bin/env bash
# Add one user to the AK-Bench UI user table, in the benchmark database.
#
# The password is typed at a prompt and handed to the hasher on stdin -- never
# as an argument, because argv is world-readable in `ps` and lands in the shell
# history of everyone who watched. What the database stores is a salted
# iterated digest (pbkdf2-sha256), never the password itself.
#
# Usage: ui-user-add.sh <name> [role]
#        role is one of: viewer (default), judge, admin
#
# The database comes from $AKBENCH_UI_DATABASE_URL when set
# (e.g. sqlite:///data/akbench.sqlite), the same connection the UI serves.
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: ui-user-add.sh <name> [role]

Adds one user to the AK-Bench UI user table in the benchmark database.
role is one of: viewer (default), judge, admin.

  viewer  sees the runs, the scores and the charts
  judge   additionally sees hidden tests and planted defects
  admin   manages the history: deletes runs, tasks, experiments, agents, runtimes

The password is typed at a prompt, never passed as an argument; the database
stores only its hash (pbkdf2-sha256, salted and iterated).

The connection is read the way the app reads it: the project's .env
(AKBENCH_PG_* / AKBENCH_DB_BACKEND -> PostgreSQL) is honored first, and
without one the user lands in data/akbench.sqlite. $AKBENCH_UI_DATABASE_URL
overrides both.
EOF
  exit 2
}

[ $# -ge 1 ] && [ $# -le 2 ] || usage

NAME="${1:-}"
ROLE="${2:-viewer}"

case "$ROLE" in
  viewer | judge | admin) ;;
  *)
    echo "error: role must be viewer, judge or admin, not '$ROLE'" >&2
    exit 2
    ;;
esac

if [ -z "$NAME" ]; then
  echo "error: name is empty" >&2
  exit 2
fi
case "$NAME" in
  *[!a-zA-Z0-9._-]*)
    echo "error: name may carry letters, digits, dot, dash and underscore only" >&2
    exit 2
    ;;
esac

printf 'password for %s: ' "$NAME" >&2
IFS= read -r -s PASSWORD
printf '\nrepeat password: ' >&2
IFS= read -r -s REPEAT
printf '\n' >&2

if [ -z "$PASSWORD" ]; then
  echo "error: the password is empty" >&2
  exit 2
fi
if [ "$PASSWORD" != "$REPEAT" ]; then
  echo "error: the passwords do not match" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# The secret travels on stdin: one line, straight into the hasher.
if ! printf '%s\n' "$PASSWORD" | (
  cd "$REPO_DIR" &&
  PYTHONPATH="${REPO_DIR}/src${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m bench_ui.userstore add "$NAME" "$ROLE"
); then
  exit 1
fi

echo
echo "serve the UI on the same database and sign in as '$NAME':"
echo "  ./run-ui.sh"
