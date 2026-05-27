"""Quick data quality report."""
import sqlite3

conn = sqlite3.connect("tunisian_companies.db")
cur = conn.cursor()

cur.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN phone IS NOT NULL AND phone != '' THEN 1 ELSE 0 END) as has_phone,
        SUM(CASE WHEN email IS NOT NULL AND email != '' THEN 1 ELSE 0 END) as has_email,
        SUM(CASE WHEN website IS NOT NULL AND website != '' THEN 1 ELSE 0 END) as has_website,
        SUM(CASE WHEN address IS NOT NULL AND address != '' THEN 1 ELSE 0 END) as has_address,
        SUM(CASE WHEN sector IS NOT NULL AND sector != '' AND sector != 'Uncategorised' THEN 1 ELSE 0 END) as has_sector
    FROM companies
""")
r = cur.fetchone()
total = r[0]
print(f"=== Data Quality Report ===")
print(f"Total records:    {total}")
print(f"With Phone:       {r[1]} ({r[1]*100//total}%)")
print(f"With Email:       {r[2]} ({r[2]*100//total}%)")
print(f"With Website:     {r[3]} ({r[3]*100//total}%)")
print(f"With Address:     {r[4]} ({r[4]*100//total}%)")
print(f"With Sector:      {r[5]} ({r[5]*100//total}%)")

# Source breakdown
print(f"\n=== Source Breakdown ===")
cur.execute("SELECT source_data FROM companies WHERE source_data IS NOT NULL")
from collections import Counter
sources = Counter()
for row in cur.fetchall():
    import json
    try:
        sd = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        for key in sd:
            sources[key] += 1
    except:
        pass

for src, count in sources.most_common():
    print(f"  {src}: {count} records")

# Records with NO useful contact info at all
cur.execute("""
    SELECT COUNT(*) FROM companies 
    WHERE (phone IS NULL OR phone = '') 
    AND (email IS NULL OR email = '') 
    AND (website IS NULL OR website = '')
""")
no_contact = cur.fetchone()[0]
print(f"\nRecords with NO contact info: {no_contact} ({no_contact*100//total}%)")

conn.close()
