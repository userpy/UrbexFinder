"""One-time conservative merger for the existing bot/catalog snapshot pair.

Run with writers stopped and backups taken. Default is a read-only comparison;
--apply commits all changes atomically. Unknown conflicts abort without writes.
"""
import argparse
import os
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from .config import Settings

TABLES = ('roles','users','resources','places','place_ratings','place_reviews','place_photos','place_nonexistent_reports')
METADATA = {'category_id','created_at','updated_at'}
RATINGS = {'rating_avg','rating_count','rating_score'}


def merge(source_url, target_url, apply=False):
    source, target = create_engine(source_url), create_engine(target_url)
    summary = {}
    try:
        with source.connect().execution_options(isolation_level='REPEATABLE READ') as src, target.begin() as dst:
            src.execute(text('SET TRANSACTION READ ONLY'))
            dst.execute(text('SELECT pg_advisory_xact_lock(734836209)'))
            operations = []
            for name in TABLES:
                table = Table(name, MetaData(), autoload_with=dst)
                source_rows = {r['id']:dict(r) for r in src.execute(select(*(table.c[c['name']] for c in inspect(src).get_columns(name)))).mappings()}
                target_rows = {r['id']:dict(r) for r in dst.execute(select(table)).mappings()}
                # A bot-owned record missing at source may be a deletion or a
                # destination-only addition. Never silently pick either side.
                if name != 'places' and target_rows.keys() - source_rows.keys():
                    raise RuntimeError(f'{name}: destination-only records require reconciliation')
                added = updated = 0
                for id, row in source_rows.items():
                    previous = target_rows.get(id)
                    if previous is None:
                        if name == 'places':
                            raise RuntimeError('New bot places require category/ID reconciliation')
                        operations.append(table.insert().values(**row)); added += 1
                        continue
                    changed = {k for k in row if row[k] != previous[k]}
                    allowed = METADATA | RATINGS if name == 'places' else set()
                    if changed - allowed:
                        raise RuntimeError(f'{name}: conflicting record {id}, columns {sorted(changed-allowed)}')
                    values = {k:row[k] for k in changed & RATINGS} if name == 'places' else {}
                    if values:
                        operations.append(table.update().where(table.c.id==id).values(**values)); updated += 1
                summary[name] = {'source':len(source_rows),'target':len(target_rows),'insert':added,'update':updated}
            if apply:
                for operation in operations:dst.execute(operation)
                for name in TABLES:
                    dst.execute(text("SELECT setval(pg_get_serial_sequence(:name,'id'), GREATEST(COALESCE((SELECT max(id) FROM "+name+"),0),1), EXISTS(SELECT 1 FROM "+name+"))"), {'name':name})
            else:
                dst.rollback()
        return summary
    finally:
        source.dispose(); target.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    source_url = os.environ.get('MERGE_SOURCE_DATABASE_URL')
    if not source_url:raise SystemExit('Set MERGE_SOURCE_DATABASE_URL')
    print(merge(source_url, Settings().database_url, args.apply))
