"""
Copies all data from local SQLite into Railway PostgreSQL.
Usage: python migrate_to_railway.py <RAILWAY_DATABASE_URL>
"""
import sys
import os
from sqlalchemy import create_engine, text

LOCAL_DB = 'sqlite:///instance/crm.db'


def migrate(railway_url):
    if railway_url.startswith('postgres://'):
        railway_url = railway_url.replace('postgres://', 'postgresql://', 1)

    print('Connecting to local SQLite...')
    local = create_engine(LOCAL_DB)

    print('Connecting to Railway PostgreSQL...')
    remote = create_engine(railway_url)

    # Create all tables on Railway using the app with Railway URL
    print('Creating tables on Railway...')
    os.environ['DATABASE_URL'] = railway_url
    from app import app
    from models import db
    with app.app_context():
        db.create_all()
    print('Tables created.')

    # SQLite stores booleans as 0/1 — PostgreSQL needs True/False
    BOOLEAN_COLS = {
        'schools':          ['won', 'digital_flyer_sent', 'physical_flyer_sent'],
        'activities':       ['follow_up_complete'],
        'parent_activities':['follow_up_complete'],
        'users':            [],
        'parents':          [],
        'email_templates':  [],
        'email_logs':       [],
        'attachments':      [],
    }

    tables_in_order = [
        'users',
        'schools',
        'parents',
        'activities',
        'parent_activities',
        'email_templates',
        'email_logs',
        'attachments',
    ]

    with local.connect() as src:
        with remote.connect() as dst:
            for table in tables_in_order:
                # Fetch rows from SQLite
                try:
                    result = src.execute(text(f'SELECT * FROM {table}'))
                    rows = result.fetchall()
                    col_names = list(result.keys())
                except Exception as e:
                    print(f'  {table}: skipped ({e})')
                    continue

                if not rows:
                    print(f'  {table}: empty')
                    continue

                # Clear remote table
                try:
                    dst.execute(text(f'TRUNCATE TABLE {table} RESTART IDENTITY CASCADE'))
                    dst.commit()
                except Exception as e:
                    print(f'  {table}: could not truncate ({e})')

                # Insert rows, skipping any SQLite-only stale columns
                # Get actual columns on the remote table to skip stale SQLite-only columns
                remote_cols_result = dst.execute(text(
                    f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}'"
                ))
                remote_col_set = {r[0] for r in remote_cols_result}
                valid_cols = [c for c in col_names if c in remote_col_set]

                col_str = ', '.join(f'"{c}"' for c in valid_cols)
                placeholders = ', '.join([f':{c}' for c in valid_cols])
                insert_sql = text(f'INSERT INTO {table} ({col_str}) VALUES ({placeholders})')

                bool_cols = BOOLEAN_COLS.get(table, [])
                batch = []
                for row in rows:
                    d = dict(zip(col_names, row))
                    for col in bool_cols:
                        if col in d and d[col] is not None:
                            d[col] = bool(d[col])
                    batch.append({k: v for k, v in d.items() if k in remote_col_set})
                dst.execute(insert_sql, batch)
                dst.commit()
                print(f'  {table}: {len(rows)} rows migrated')

            # Fix PostgreSQL auto-increment sequences
            print('Fixing sequences...')
            for table in tables_in_order:
                try:
                    dst.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
                    ))
                    dst.commit()
                except Exception:
                    pass

    print('\nAll done — data is live on Railway.')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python migrate_to_railway.py <RAILWAY_DATABASE_URL>')
        sys.exit(1)
    migrate(sys.argv[1])
