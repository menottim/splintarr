#!/usr/bin/env python3
"""Test script to verify SQLCipher functionality."""

import os
import sys
from pathlib import Path

print("=" * 60)
print("SQLCipher Diagnostic Test")
print("=" * 60)

# Test 1: Check if secrets are readable
print("\n1. Checking secret files...")
for secret_name in ["db_key", "secret_key", "pepper"]:
    secret_path = f"/run/secrets/{secret_name}"
    if os.path.exists(secret_path):
        size = os.path.getsize(secret_path)
        content = Path(secret_path).read_text().strip()
        print(f"   ✓ {secret_name}: {size} bytes, stripped length: {len(content)}")
    else:
        print(f"   ✗ {secret_name}: NOT FOUND")

# Test 2: Check /data directory
print("\n2. Checking /data directory...")
if os.path.exists("/data"):
    print(f"   ✓ /data exists")
    if os.access("/data", os.W_OK):
        print(f"   ✓ /data is writable")
    else:
        print(f"   ✗ /data is NOT writable")
else:
    print(f"   ✗ /data does NOT exist")

# Test 3: Test SQLCipher import
print("\n3. Testing SQLCipher import...")
try:
    import sqlcipher3
    print(f"   ✓ sqlcipher3 imported successfully")
    print(f"     Version: {sqlcipher3.version}")
except ImportError as e:
    print(f"   ✗ Failed to import sqlcipher3: {e}")
    sys.exit(1)

# Test 4: Test basic SQLCipher database creation
print("\n4. Testing SQLCipher database creation...")
try:
    # Read the encryption key
    db_key = Path("/run/secrets/db_key").read_text().strip()
    print(f"   Key length: {len(db_key)} characters")

    # Try to create a test database
    test_db_path = "/data/test_sqlcipher.db"
    print(f"   Creating test database at: {test_db_path}")

    # Create connection with SQLCipher
    conn = sqlcipher3.connect(test_db_path)
    cursor = conn.cursor()

    # Set the encryption key IMMEDIATELY after connecting
    cursor.execute(f"PRAGMA key = '{db_key}'")

    # Set cipher configuration
    cursor.execute("PRAGMA cipher = 'aes-256-cfb'")
    cursor.execute("PRAGMA kdf_iter = 256000")

    # Try to create a table
    cursor.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, value TEXT)")
    cursor.execute("INSERT INTO test (value) VALUES ('Hello SQLCipher')")
    conn.commit()

    # Try to read it back
    cursor.execute("SELECT * FROM test")
    result = cursor.fetchone()
    print(f"   ✓ Successfully created and read from encrypted database")
    print(f"     Result: {result}")

    conn.close()

    # Clean up
    os.remove(test_db_path)
    print(f"   ✓ Test database cleaned up")

except Exception as e:
    print(f"   ✗ SQLCipher test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 5: Test SQLAlchemy connection string format
print("\n5. Testing SQLAlchemy connection format...")
try:
    from urllib.parse import urlencode

    db_key = Path("/run/secrets/db_key").read_text().strip()
    db_path = "/data/test_sqlalchemy.db"

    params = urlencode({
        "cipher": "aes-256-cfb",
        "kdf_iter": "256000",
    })

    database_url = f"sqlite+pysqlcipher://:{db_key}@/{db_path}?{params}"
    print(f"   URL format: sqlite+pysqlcipher://:{''*len(db_key)}@/{db_path}?{params}")

    from sqlalchemy import create_engine, text

    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    # Try to connect and execute a simple query
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY)"))
        conn.commit()

    print(f"   ✓ SQLAlchemy connection successful")

    # Clean up
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"   ✓ Test database cleaned up")

except Exception as e:
    print(f"   ✗ SQLAlchemy test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("All tests passed! ✓")
print("=" * 60)
