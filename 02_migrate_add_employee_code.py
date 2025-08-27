import sqlite3, os

DB = "safety.db"  # change to your current DB filename if different
if not os.path.exists(DB):
    print("safety.db not found in this folder.")
    raise SystemExit(1)

conn = sqlite3.connect(DB)
cur = conn.cursor()

# Check existing columns
cur.execute("PRAGMA table_info(employee)")
cols = [r[1] for r in cur.fetchall()]

# Add column if missing
if "employee_code" not in cols:
    print("Adding column employee_code ...")
    cur.execute("ALTER TABLE employee ADD COLUMN employee_code TEXT")

# Populate codes where empty
print("Populating employee_code values ...")
for (emp_id,) in cur.execute("SELECT id FROM employee WHERE employee_code IS NULL OR employee_code = ''"):
    code = f"E{emp_id:04d}"
    cur.execute("UPDATE employee SET employee_code=? WHERE id=?", (code, emp_id))

conn.commit()
conn.close()
print("Migration complete.")
