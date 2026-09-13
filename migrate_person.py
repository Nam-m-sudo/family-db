"""
Run this ONCE against your deployed family_collect.db to add the new
masa / paksha / thithi columns used for death details.

The old dod_nakshatra column is left in place (untouched, just unused) —
SQLite can't drop columns on older versions without rebuilding the table,
and there's no benefit to forcing that here.
"""
import sqlite3

conn = sqlite3.connect("family_collect.db")
cur = conn.cursor()

cur.execute("PRAGMA table_info(person)")
existing_cols = [row[1] for row in cur.fetchall()]

for col in ("dod_masa", "dod_paksha", "dod_thithi"):
    if col not in existing_cols:
        cur.execute(f"ALTER TABLE person ADD COLUMN {col} VARCHAR(30)")
        print(f"Added {col} column")
    else:
        print(f"{col} column already exists, nothing to do.")

conn.commit()
conn.close()
print("Migration done. Now restart/redeploy app.py.")