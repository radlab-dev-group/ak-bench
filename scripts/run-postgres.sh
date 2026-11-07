#!/usr/bin/env bash
set -euo pipefail

# Starts AK-Bench PostgreSQL in Docker.
# Database data is persisted in a Docker named volume.
#
# Configuration comes from the project .env (the same names AK-Bench reads for
# database.postgres.*); a variable that is already exported wins over the file.
#   AKBENCH_PG_IMAGE=postgres:18
#   AKBENCH_PG_HOST=127.0.0.1        what AK-Bench connects to
#   AKBENCH_PG_BIND=127.0.0.1        what address Docker publishes on
#   AKBENCH_PG_PORT=5959
#   AKBENCH_PG_USER=akbench          the bootstrap (superuser) role
#   AKBENCH_PG_PASSWORD=             required, no default; see below
#   AKBENCH_PG_DB=akbench
#   AKBENCH_PG_APP_USER=             optional least-privilege role to provision
#   AKBENCH_PG_APP_PASSWORD=         required with APP_USER
#   AKBENCH_PG_CONTAINER=akbench-postgres
#   AKBENCH_PG_VOLUME=akbench-postgres-data
#
# AKBENCH_PG_BIND is separate from AKBENCH_PG_HOST on purpose: publishing a
# port on 0.0.0.0 while naming 127.0.0.1 as the host is exactly how a database
# ends up reachable from a network its operator thought they had excluded.
# AKBENCH_PG_PASSWORD has no default, and a well-known value is refused unless
# AKBENCH_PG_ALLOW_WEAK_PASSWORD=1 says you mean a throwaway instance.
#
# Commands:
#   start      - create/start PostgreSQL (and provision APP_USER if configured)
#   provision  - (re)apply the least-privilege role and its grants
#   stop       - stop container
#   status     - show container status
#   down       - remove container (volume survives)
#   env        - print the connection variables for the shell (password masked)
#   psql       - open PostgreSQL shell

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

ENV_FILE="${AKBENCH_ENV_FILE:-${REPO_ROOT}/.env}"

# Load KEY=VALUE lines from .env without overriding what is already exported.
load_env_file() {
  local file="$1" line key value
  [ -f "${file}" ] || return 0
  while IFS= read -r line || [ -n "${line}" ]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line#export }"
    case "${line}" in
      ""|"#"*) continue ;;
    esac
    [[ "${line}" == *"="* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    [[ "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    value="${value%%#*}"
    value="${value%"${value##*[![:space:]]}"}"
    if [ "${#value}" -ge 2 ]; then
      case "${value}" in
        \"*\"|\'*\'*) value="${value:1:${#value}-2}" ;;
      esac
    fi
    [ -n "${!key:-}" ] && continue
    export "${key}=${value}"
  done < "${file}"
}

load_env_file "${ENV_FILE}"

IMAGE="${AKBENCH_PG_IMAGE:-postgres:18}"
HOST_ADDR="${AKBENCH_PG_HOST:-127.0.0.1}"
PORT="${AKBENCH_PG_PORT:-5959}"
USER_NAME="${AKBENCH_PG_USER:-akbench}"
PASSWORD="${AKBENCH_PG_PASSWORD:-}"
DB_NAME="${AKBENCH_PG_DB:-akbench}"
CONTAINER="${AKBENCH_PG_CONTAINER:-akbench-postgres}"
VOLUME="${AKBENCH_PG_VOLUME:-akbench-postgres-data}"

# What the container publishes on, as opposed to what clients connect to. These
# used to be the same variable, and that was the bug: "-p 5959:5432" with no
# address binds every interface on the machine, so an operator who set
# AKBENCH_PG_HOST=127.0.0.1 -- reading it, rightly, as "this box only" -- had
# put the database on the network anyway.
BIND_ADDR="${AKBENCH_PG_BIND:-127.0.0.1}"

#: Optional least-privilege role. When set and different from the bootstrap
#: superuser, `start` creates it and grants only what AK-Bench does.
APP_USER="${AKBENCH_PG_APP_USER:-}"
APP_PASSWORD="${AKBENCH_PG_APP_PASSWORD:-}"

COMMAND="${1:-start}"

# --- refuse a database that would be unsafe to publish --------------------
require_password() {
  if [ -z "${PASSWORD}" ]; then
    cat >&2 <<EOF
ERROR: AKBENCH_PG_PASSWORD is not set.

There is no default password: a credential that ships with the repository is a
credential every installation shares. Generate one and put it in .env:

  python -c "import secrets; print(secrets.token_urlsafe(24))"
EOF
    exit 1
  fi

  case "${PASSWORD}" in
    akbench_local|postgres|password|admin|root|changeme|test|dev|akbench)
      weak=1 ;;
    *)
      weak=0 ;;
  esac
  if [ "${weak}" = "1" ] && [ -z "${AKBENCH_PG_ALLOW_WEAK_PASSWORD:-}" ]; then
    cat >&2 <<EOF
ERROR: AKBENCH_PG_PASSWORD is a well-known value.

Anyone who has read this repository would have the database. Generate one:

  python -c "import secrets; print(secrets.token_urlsafe(24))"

Set AKBENCH_PG_ALLOW_WEAK_PASSWORD=1 to override, for a throwaway instance.
EOF
    exit 1
  fi

  if [ "${#PASSWORD}" -lt 12 ] && [ -z "${AKBENCH_PG_ALLOW_WEAK_PASSWORD:-}" ]; then
    echo "ERROR: AKBENCH_PG_PASSWORD is shorter than 12 characters." >&2
    exit 1
  fi
}

url() {
  printf 'postgresql+psycopg://%s:***@%s:%s/%s' \
    "${USER_NAME}" "${HOST_ADDR}" "${PORT}" "${DB_NAME}"
}

print_env() {
  echo "  AKBENCH_PG_HOST=${HOST_ADDR}"
  echo "  AKBENCH_PG_PORT=${PORT}"
  echo "  AKBENCH_PG_BIND=${BIND_ADDR}"
  echo "  AKBENCH_PG_USER=${USER_NAME}"
  # The password is what this file is protecting, and this function is reached
  # by `env` as well as by `start`: a terminal scrollback and a CI log are both
  # places where a secret outlives the command that printed it.
  if [ -n "${PASSWORD}" ]; then
    echo "  AKBENCH_PG_PASSWORD=*** (${#PASSWORD} characters)"
  else
    echo "  AKBENCH_PG_PASSWORD=*** (not set)"
  fi
  echo "  AKBENCH_PG_DB=${DB_NAME}"
}

ensure_running() {
  # Check whether the container is already running.
  if [ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER}" 2>/dev/null || true)" = "true" ]; then
    echo "Container ${CONTAINER} is already running."
    return 0
  fi

  # Start an existing stopped container.
  if [ -n "$(docker inspect -f '{{.Id}}' "${CONTAINER}" 2>/dev/null || true)" ]; then
    echo "Starting existing container ${CONTAINER}..."
    docker start "${CONTAINER}" >/dev/null
  else
    # Create persistent Docker volume if it doesn't exist.
    docker volume create "${VOLUME}" >/dev/null

    # Only a new container needs a password to be chosen; a stopped one already
    # has one, and `stop`/`status` must keep working without it.
    require_password

    echo "Creating PostgreSQL container ${CONTAINER}..."

    docker run -d \
      --name "${CONTAINER}" \
      --restart unless-stopped \
      -p "${BIND_ADDR}:${PORT}:5432" \
      -v "${VOLUME}:/var/lib/postgresql" \
      -e POSTGRES_USER="${USER_NAME}" \
      -e POSTGRES_PASSWORD="${PASSWORD}" \
      -e POSTGRES_DB="${DB_NAME}" \
      "${IMAGE}" >/dev/null
  fi

  # Wait for PostgreSQL to become ready.
  echo "Waiting for PostgreSQL to accept connections..."

  for i in $(seq 1 60); do
    if docker exec "${CONTAINER}" \
      pg_isready -U "${USER_NAME}" -d "${DB_NAME}" >/dev/null 2>&1; then
      echo "PostgreSQL is ready."
      return 0
    fi

    if [ "${i}" -eq 60 ]; then
      echo "ERROR: PostgreSQL did not become ready." >&2
      docker logs --tail 50 "${CONTAINER}" >&2
      exit 1
    fi

    sleep 1
  done
}

# --- a role with only the privileges AK-Bench uses -------------------------
# The bootstrap user of the image is a cluster superuser, and AK-Bench connected
# as it: SQL access was then host access, through COPY ... PROGRAM or
# lo_export. AK-Bench needs to read and write its own tables, and to create them
# when it migrates, and nothing else.
provision_app_role() {
  [ -n "${APP_USER}" ] || return 0
  if [ "${APP_USER}" = "${USER_NAME}" ]; then
    echo "AKBENCH_PG_APP_USER equals AKBENCH_PG_USER; that is the superuser, so nothing to provision." >&2
    return 0
  fi
  if ! [[ "${APP_USER}" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
    echo "ERROR: AKBENCH_PG_APP_USER must be a lower-case identifier." >&2
    return 1
  fi
  if [ -z "${APP_PASSWORD}" ]; then
    echo "ERROR: AKBENCH_PG_APP_PASSWORD is required when AKBENCH_PG_APP_USER is set." >&2
    return 1
  fi

  echo "Provisioning the least-privilege role ${APP_USER}..."
  docker exec -i "${CONTAINER}" psql -U "${USER_NAME}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 \
    -c "DO \$\$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${APP_USER}') THEN
            CREATE ROLE ${APP_USER} LOGIN PASSWORD '${APP_PASSWORD}';
          ELSE
            ALTER ROLE ${APP_USER} LOGIN PASSWORD '${APP_PASSWORD}';
          END IF;
        END \$\$;" \
    -c "REVOKE CREATE ON SCHEMA public FROM PUBLIC" \
    -c "GRANT CONNECT ON DATABASE ${DB_NAME} TO ${APP_USER}" \
    -c "GRANT USAGE, CREATE ON SCHEMA public TO ${APP_USER}" \
    -c "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ${APP_USER}" \
    -c "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO ${APP_USER}" \
    -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${APP_USER}" \
    -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO ${APP_USER}"
  echo "  ${APP_USER} is not a superuser. Point AK-Bench at it with AKBENCH_PG_USER=${APP_USER}"
  echo "  (the bootstrap user ${USER_NAME} stays for administration)."
}

case "${COMMAND}" in

  start)
    ensure_running
    provision_app_role

    echo
    echo "PostgreSQL is up:"
    echo "  Image:     ${IMAGE}"
    echo "  Container: ${CONTAINER}"
    echo "  Volume:    ${VOLUME}"
    echo "  Published: ${BIND_ADDR}:${PORT} -> 5432"
    echo "  Database:  ${DB_NAME}"
    echo "  User:      ${USER_NAME}"

    case "${BIND_ADDR}" in
      127.0.0.1|localhost|::1) ;;
      *)
        echo
        echo "  WARNING: published on ${BIND_ADDR}, not loopback. Anyone who can"
        echo "  reach this port can attempt to authenticate against the database."
        ;;
    esac

    echo
    echo "Connection parameters (from ${ENV_FILE} unless exported):"
    print_env
    echo
    echo "AK-Bench reads these as database.postgres.* and builds the URL itself."
    echo "To check what it resolved to: akbench config show"
    ;;

  stop)
    if [ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER}" 2>/dev/null || true)" = "true" ]; then
      docker stop "${CONTAINER}" >/dev/null
      echo "Container ${CONTAINER} stopped."
    else
      echo "Container ${CONTAINER} is not running."
    fi
    ;;

  provision)
    ensure_running
    provision_app_role
    ;;

  env)
    print_env
    ;;

  status)
    docker ps -a \
      --filter "name=^${CONTAINER}$" \
      --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

    echo
    echo "Docker volume:"
    docker volume inspect "${VOLUME}" --format '{{.Name}}' 2>/dev/null || echo "Volume does not exist."
    ;;

  down)
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
    echo "Container ${CONTAINER} removed."
    echo "Database data preserved in Docker volume: ${VOLUME}"
    ;;

  psql)
    ensure_running
    shift
    docker exec -it "${CONTAINER}" \
      psql -U "${USER_NAME}" -d "${DB_NAME}" "$@"
    ;;

  *)
    echo "Usage: $0 [start|provision|stop|status|down|env|psql]" >&2
    exit 2
    ;;

esac
