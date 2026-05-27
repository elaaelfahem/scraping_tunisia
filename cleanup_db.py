"""One-time script to clean placeholder/junk values from the database."""
import sqlite3

conn = sqlite3.connect("tunisian_companies.db")
cur = conn.cursor()

# Count dirty records
cur.execute("SELECT COUNT(*) FROM companies WHERE phone LIKE '%xxxxx%' OR phone LIKE '%*****%' OR phone = 'n/a'")
dirty_phones = cur.fetchone()[0]
print(f"Records with placeholder phones: {dirty_phones}")

cur.execute("SELECT COUNT(*) FROM companies WHERE phone IS NOT NULL AND phone != '' AND LENGTH(phone) > 0")
all_phones = cur.fetchone()[0]
print(f"Total records with any phone value: {all_phones}")

cur.execute("SELECT COUNT(*) FROM companies")
total = cur.fetchone()[0]
print(f"Total records: {total}")

# Clean placeholder phones
cur.execute(
    "UPDATE companies SET phone = NULL "
    "WHERE phone LIKE '%xxxxx%' OR phone LIKE '%*****%' "
    "OR phone = 'n/a' OR phone = 'none' OR phone = 'null' OR phone = 'N/A'"
)
cleaned_phones = cur.rowcount
print(f"Cleaned {cleaned_phones} placeholder phone values")

# Clean placeholder emails
cur.execute(
    "UPDATE companies SET email = NULL "
    "WHERE email LIKE '%xxxxx%' OR email = 'n/a' OR email = 'none'"
)
cleaned_emails = cur.rowcount
print(f"Cleaned {cleaned_emails} placeholder email values")

# Clean stub websites
cur.execute(
    "UPDATE companies SET website = NULL "
    "WHERE website IN ('www.', 'http://www.', 'https://www.', 'http://', 'https://', 'n/a', 'none')"
)
cleaned_websites = cur.rowcount
print(f"Cleaned {cleaned_websites} stub website values")

conn.commit()

# Show summary after cleanup
cur.execute("SELECT COUNT(*) FROM companies WHERE phone IS NOT NULL AND phone != ''")
remaining_phones = cur.fetchone()[0]
print(f"\nRecords with valid phones after cleanup: {remaining_phones}")

cur.execute("SELECT COUNT(*) FROM companies WHERE email IS NOT NULL AND email != ''")
remaining_emails = cur.fetchone()[0]
print(f"Records with emails: {remaining_emails}")

cur.execute("SELECT COUNT(*) FROM companies WHERE website IS NOT NULL AND website != ''")
remaining_websites = cur.fetchone()[0]
print(f"Records with websites: {remaining_websites}")

# Show a sample of what's left
print("\n--- Sample records after cleanup ---")
cur.execute("SELECT name, phone, email, website FROM companies WHERE phone IS NOT NULL AND phone != '' LIMIT 5")
for row in cur.fetchall():
    print(f"  {row[0]} | Phone: {row[1]} | Email: {row[2]} | Web: {row[3]}")

conn.close()
print("\nDone!")
