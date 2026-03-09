#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

OUTPUT_FILE="${1:-lat_lon_full_address.csv}"
if [[ "${OUTPUT_FILE}" != /* ]]; then
  OUTPUT_FILE="${PROJECT_DIR}/${OUTPUT_FILE}"
fi

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-mydatabase}"
TMP_FILE="${OUTPUT_FILE}.tmp"

cd "${PROJECT_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker не найден в PATH" >&2
  exit 1
fi

if ! docker compose ps db >/dev/null 2>&1; then
  echo "Сервис db недоступен. Проверьте, что стек запущен: docker compose up -d" >&2
  exit 1
fi

docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "\copy (
SELECT
  latitude::text AS lat,
  longitude::text AS lon,
  COALESCE(full_address, '') AS full_address
FROM places
WHERE latitude IS NOT NULL
  AND longitude IS NOT NULL
ORDER BY id
) TO STDOUT WITH CSV HEADER" > "${TMP_FILE}"

mv "${TMP_FILE}" "${OUTPUT_FILE}"
echo "Готово: ${OUTPUT_FILE}"
