#!/usr/bin/env bash
set -euo pipefail

# Usage: bash scripts/export_places.sh [output.csv]
# Relative output paths are resolved from the project root.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if [[ $# -gt 1 ]]; then
  echo "Использование: bash scripts/export_places.sh [output.csv]" >&2
  exit 1
fi

OUTPUT_FILE="${1:-places.csv}"
if [[ "${OUTPUT_FILE}" != /* ]]; then
  OUTPUT_FILE="${PROJECT_DIR}/${OUTPUT_FILE}"
fi

cd "${PROJECT_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker не найден в PATH" >&2
  exit 1
fi

# Keep an existing export intact if the database connection or COPY fails.
TMP_FILE="$(mktemp "${OUTPUT_FILE}.tmp.XXXXXX")"
trap 'rm -f -- "${TMP_FILE}"' EXIT

# Use the database credentials configured inside the db container.
docker compose exec -T db sh -c '
  exec psql -X -q -v ON_ERROR_STOP=1 \
    -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-mydatabase}" \
    -c "COPY (SELECT * FROM public.places ORDER BY id) TO STDOUT WITH (FORMAT CSV, HEADER TRUE, ENCODING '\''UTF8'\'');"
' > "${TMP_FILE}"

mv -- "${TMP_FILE}" "${OUTPUT_FILE}"
echo "Готово: ${OUTPUT_FILE}"
