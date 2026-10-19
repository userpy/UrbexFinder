#!/usr/bin/env python3
"""Выбрать CSV и добавить новые места в PostgreSQL через Docker Compose."""

import argparse
import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT_DIR = Path(__file__).resolve().parent.parent
FIELDS = ("name", "description", "type", "latitude", "longitude", "category", "full_address")
SQL_START = """BEGIN;
SET LOCAL lock_timeout = '15s';
CREATE TEMP TABLE import_places (
    seq bigint GENERATED ALWAYS AS IDENTITY,
    name text NOT NULL, description text, type text,
    latitude numeric(10,6), longitude numeric(10,6), category text, full_address text
) ON COMMIT DROP;
COPY import_places (name, description, type, latitude, longitude, category, full_address) FROM STDIN;
"""
SQL_END = r"""\.
LOCK TABLE public.places IN SHARE ROW EXCLUSIVE MODE;
WITH unique_places AS (
    SELECT DISTINCT ON (latitude, longitude) *
    FROM import_places ORDER BY latitude, longitude, seq
), inserted AS (
    INSERT INTO public.places (name, description, type, latitude, longitude, category, full_address)
    SELECT i.name, i.description, i.type, i.latitude, i.longitude, i.category, i.full_address
    FROM unique_places i
    WHERE NOT EXISTS (
        SELECT 1 FROM public.places p
        WHERE p.latitude = i.latitude AND p.longitude = i.longitude
    )
    RETURNING id
)
SELECT (SELECT count(*) FROM import_places) AS csv_rows,
       count(*) AS inserted,
       (SELECT count(*) FROM import_places) - count(*) AS skipped
FROM inserted;
COMMIT;
"""


def choose_file():
    paths = sorted(set(PROJECT_DIR.glob("*.csv")) | set((PROJECT_DIR / "bot/geo_data").glob("*.csv")))
    print("Выберите CSV-файл:")
    for index, path in enumerate(paths, 1):
        print(f"  {index}. {path.relative_to(PROJECT_DIR)}")
    answer = input("Номер файла или путь к другому CSV: ").strip()
    if answer.isdigit() and 1 <= int(answer) <= len(paths):
        return paths[int(answer) - 1]
    if not answer:
        raise ValueError("файл не выбран")
    return Path(answer).expanduser()


def coordinate(raw, limit, row_number, field):
    try:
        number = Decimal(raw.strip())
        if not number.is_finite() or abs(number) > limit:
            raise ValueError()
        return format(number.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise ValueError(f"Строка {row_number}: неверное значение {field}") from exc


def copy_text(value):
    # COPY text format: escape newlines and backslashes, including a literal \.
    # CSV values never become SQL or psql commands.
    if value is None or value == "":
        return "\\N"
    if "\0" in value:
        raise ValueError("CSV содержит недопустимый нулевой символ")
    return value.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def prepare_import(path, stream):
    csv.field_size_limit(16 * 1024 * 1024)
    stream.write(SQL_START)
    count = 0
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        headers = reader.fieldnames or []
        required = {"name", "latitude", "longitude"}
        if len(headers) != len(set(headers)) or not required.issubset(headers):
            raise ValueError("Нужны уникальные заголовки CSV и поля name,latitude,longitude (разделитель — запятая)")
        for row_number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Строка {row_number}: число значений не совпадает с заголовком")
            if not row["name"].strip():
                raise ValueError(f"Строка {row_number}: пустое название")
            row["latitude"] = coordinate(row["latitude"], 90, row_number, "latitude")
            row["longitude"] = coordinate(row["longitude"], 180, row_number, "longitude")
            stream.write("\t".join(copy_text(row.get(field)) for field in FIELDS) + "\n")
            count += 1
    if not count:
        raise ValueError("CSV не содержит мест")
    stream.write(SQL_END)
    stream.flush()
    stream.seek(0)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", type=Path, help="CSV; без аргумента — выбор файла")
    parser.add_argument("--check", action="store_true", help="только проверить CSV, без записи в БД")
    args = parser.parse_args()
    try:
        path = args.file.expanduser() if args.file is not None else choose_file()
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="") as stream:
            count = prepare_import(path, stream)
            print(f"Файл: {path.resolve()}\nПроверено строк: {count}", flush=True)
            if args.check:
                return 0
            subprocess.run(
                ["docker", "compose", "exec", "-T", "-e", "PGCLIENTENCODING=UTF8", "db", "sh", "-c",
                 'exec psql -X -q -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" '
                 '-d "${POSTGRES_DB:-mydatabase}"'],
                cwd=PROJECT_DIR, stdin=stream, check=True,
            )
        print("Готово. inserted — добавлено, skipped — пропущено совпадений по координатам.")
        return 0
    except (OSError, ValueError, csv.Error, UnicodeError, EOFError, subprocess.CalledProcessError) as exc:
        print(f"Ошибка импорта: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Импорт прерван.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
