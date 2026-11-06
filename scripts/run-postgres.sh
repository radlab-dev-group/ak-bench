#!/usr/bin/env bash
set -euo pipefail

# Starts AK-Bench PostgreSQL in Docker.
# Database data is persisted in a Docker named volume.
#
# Configuration comes from the project .env (the same names AK-Bench reads for
# database.postgres.*); a variable that is already exported wins over the file.
#   AKBENCH_PG_IMAGE=postgres:18
#   AKBENCH_PG_HOST=127.0.0.1
#   AKBENCH_PG_PORT=5959
#   AKBENCH_PG_USER=akbench
#   AKBENCH_PG_PASSWORD=akbench_local
#   AKBENCH_PG_DB=akbench
#   AKBENCH_PG_CONTAINER=akbench-postgres
#   AKBENCH_PG_VOLUME=akbench-postgres-data
#
# Commands:
#   start  - create/start PostgreSQL
#   stop   - stop container
#   status - show container status
#   down   - remove container (volume survives)
#   env    - print the connection variables for the shell
#   psql   - open PostgreSQL shell

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
PASSWORD="${AKBENCH_PG_PASSWORD:-akbench_local}"
DB_NAME="${AKBENCH_PG_DB:-akbench}"
CONTAINER="${AKBENCH_PG_CONTAINER:-akbench-postgres}"
VOLUME="${AKBENCH_PG_VOLUME:-akbench-postgres-data}"

COMMAND="${1:-start}"

url() {
  printf 'postgresql+psycopg://%s:***@%s:%s/%s' \
    "${USER_NAME}" "${HOST_ADDR}" "${PORT}" "${DB_NAME}"
}

print_env() {
  echo "  AKBENCH_PG_HOST=${HOST_ADDR}"
  echo "  AKBENCH_PG_PORT=${PORT}"
  echo "  AKBENCH_PG_USER=${USER_NAME}"
  echo "  AKBENCH_PG_PASSWORD=${PASSWORD}"
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

    echo "Creating PostgreSQL container ${CONTAINER}..."

    docker run -d \
      --name "${CONTAINER}" \
      --restart unless-stopped \
      -p "${PORT}:5432" \
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

case "${COMMAND}" in

  start)
    ensure_running

    echo
    echo "PostgreSQL is up:"
    echo "  Image:     ${IMAGE}"
    echo "  Container: ${CONTAINER}"
    echo "  Volume:    ${VOLUME}"
    echo "  Port:      ${PORT}"
    echo "  Database:  ${DB_NAME}"
    echo "  User:      ${USER_NAME}"

    echo
    echo "Connection parameters (from ${ENV_FILE} unless exported):"
    print_env
    echo
    echo "AK-Bench reads these as database.postgres.*; to pin the URL instead:"
    echo "  export AKBENCH__DATABASE__URL=\'$(url)\'"
    ;;

  stop)
    if [ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER}" 2>/dev/null || true)" = "true" ]; then
      docker stop "${CONTAINER}" >/dev/null
      echo "Container ${CONTAINER} stopped."
    else
      echo "Container ${CONTAINER} is not running."
    fi
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
    echo "Usage: $0 [start|stop|status|down|env|psql]" >&2
    exit 2
    ;;

esac
