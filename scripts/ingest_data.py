"""
Panama Papers Data Ingestion Script
Loads ICIJ Offshore Leaks CSV data into Oracle Database

Requirements:
    pip install oracledb pandas numpy python-dotenv
"""

import argparse
import oracledb
import pandas as pd
import numpy as np
from datetime import datetime
import os
from pathlib import Path

# Will be set from command-line args or environment
DB_CONFIG = {}
CSV_DIR = './data'
BATCH_SIZE = 5000


def get_connection():
    """Establish database connection using thin mode (no Oracle Client needed)."""
    return oracledb.connect(**DB_CONFIG)


def safe_date_parse(date_str):
    """
    Parse date strings from CSV, handling various formats and null values.
    Returns None for unparseable values rather than raising exceptions.
    """
    if pd.isna(date_str) or date_str == '' or date_str == 'null':
        return None

    # Try common date formats found in the ICIJ data
    formats = ['%Y-%m-%d', '%d-%b-%Y', '%Y/%m/%d', '%d/%m/%Y']
    for fmt in formats:
        try:
            return datetime.strptime(str(date_str).strip(), fmt)
        except ValueError:
            continue
    return None


def truncate_string(value, max_length):
    """Safely truncate strings to fit database column limits."""
    if pd.isna(value) or value is None:
        return None
    str_value = str(value)
    return str_value[:max_length] if len(str_value) > max_length else str_value


def load_entities(connection, csv_path):
    """
    Load entities (offshore companies, trusts, foundations) from CSV.
    These represent the core offshore structures in the investigation.
    """
    print(f"Loading entities from {csv_path}...")

    df = pd.read_csv(csv_path, dtype=str, low_memory=False)
    df.columns = df.columns.str.lower().str.strip()

    cursor = connection.cursor()

    insert_sql = """
        INSERT INTO entities (
            node_id, name, jurisdiction, jurisdiction_desc,
            country_codes, countries, incorporation_date,
            inactivation_date, struck_off_date, status,
            service_provider, source_id, address, internal_id
        ) VALUES (
            :1, :2, :3, :4, :5, :6, :7, :8, :9, :10, :11, :12, :13, :14
        )
    """

    records = []
    total_loaded = 0
    errors = []

    for idx, row in df.iterrows():
        record = (
            truncate_string(row.get('node_id'), 50),
            truncate_string(row.get('name'), 500),
            truncate_string(row.get('jurisdiction'), 200),
            truncate_string(row.get('jurisdiction_description'), 500),
            truncate_string(row.get('country_codes'), 200),
            truncate_string(row.get('countries'), 500),
            safe_date_parse(row.get('incorporation_date')),
            safe_date_parse(row.get('inactivation_date')),
            safe_date_parse(row.get('struck_off_date')),
            truncate_string(row.get('status'), 100),
            truncate_string(row.get('service_provider'), 200),
            truncate_string(row.get('sourceid', row.get('source_id')), 100),
            truncate_string(row.get('address'), 1000),
            truncate_string(row.get('internal_id'), 100)
        )
        records.append(record)

        if len(records) >= BATCH_SIZE:
            try:
                cursor.executemany(insert_sql, records)
                connection.commit()
                total_loaded += len(records)
                print(f"  Loaded {total_loaded:,} entities...")
            except oracledb.Error as e:
                errors.append(f"Batch error at record {total_loaded}: {e}")
                connection.rollback()
            records = []

    if records:
        try:
            cursor.executemany(insert_sql, records)
            connection.commit()
            total_loaded += len(records)
        except oracledb.Error as e:
            errors.append(f"Final batch error: {e}")
            connection.rollback()

    cursor.close()
    print(f"  Completed: {total_loaded:,} entities loaded")
    if errors:
        print(f"  Warnings: {len(errors)} batch errors encountered")

    return total_loaded


def load_officers(connection, csv_path):
    """Load officers (directors, shareholders, beneficiaries) from CSV."""
    print(f"Loading officers from {csv_path}...")

    df = pd.read_csv(csv_path, dtype=str, low_memory=False)
    df.columns = df.columns.str.lower().str.strip()

    cursor = connection.cursor()

    insert_sql = """
        INSERT INTO officers (
            node_id, name, country_codes, countries,
            source_id, valid_until
        ) VALUES (:1, :2, :3, :4, :5, :6)
    """

    records = []
    total_loaded = 0

    for idx, row in df.iterrows():
        record = (
            truncate_string(row.get('node_id'), 50),
            truncate_string(row.get('name'), 500),
            truncate_string(row.get('country_codes'), 200),
            truncate_string(row.get('countries'), 500),
            truncate_string(row.get('sourceid', row.get('source_id')), 100),
            truncate_string(row.get('valid_until'), 100)
        )
        records.append(record)

        if len(records) >= BATCH_SIZE:
            cursor.executemany(insert_sql, records)
            connection.commit()
            total_loaded += len(records)
            print(f"  Loaded {total_loaded:,} officers...")
            records = []

    if records:
        cursor.executemany(insert_sql, records)
        connection.commit()
        total_loaded += len(records)

    cursor.close()
    print(f"  Completed: {total_loaded:,} officers loaded")
    return total_loaded


def load_intermediaries(connection, csv_path):
    """Load intermediaries (law firms, banks, corporate agents) from CSV."""
    print(f"Loading intermediaries from {csv_path}...")

    df = pd.read_csv(csv_path, dtype=str, low_memory=False)
    df.columns = df.columns.str.lower().str.strip()

    cursor = connection.cursor()

    insert_sql = """
        INSERT INTO intermediaries (
            node_id, name, country_codes, countries,
            source_id, status, internal_id, address
        ) VALUES (:1, :2, :3, :4, :5, :6, :7, :8)
    """

    records = []
    total_loaded = 0

    for idx, row in df.iterrows():
        record = (
            truncate_string(row.get('node_id'), 50),
            truncate_string(row.get('name'), 500),
            truncate_string(row.get('country_codes'), 200),
            truncate_string(row.get('countries'), 500),
            truncate_string(row.get('sourceid', row.get('source_id')), 100),
            truncate_string(row.get('status'), 100),
            truncate_string(row.get('internal_id'), 100),
            truncate_string(row.get('address'), 1000)
        )
        records.append(record)

        if len(records) >= BATCH_SIZE:
            cursor.executemany(insert_sql, records)
            connection.commit()
            total_loaded += len(records)
            print(f"  Loaded {total_loaded:,} intermediaries...")
            records = []

    if records:
        cursor.executemany(insert_sql, records)
        connection.commit()
        total_loaded += len(records)

    cursor.close()
    print(f"  Completed: {total_loaded:,} intermediaries loaded")
    return total_loaded


def load_addresses(connection, csv_path):
    """Load addresses from CSV."""
    print(f"Loading addresses from {csv_path}...")

    df = pd.read_csv(csv_path, dtype=str, low_memory=False)
    df.columns = df.columns.str.lower().str.strip()

    cursor = connection.cursor()

    insert_sql = """
        INSERT INTO addresses (
            node_id, address, country_codes, countries, source_id
        ) VALUES (:1, :2, :3, :4, :5)
    """

    records = []
    total_loaded = 0

    for idx, row in df.iterrows():
        record = (
            truncate_string(row.get('node_id'), 50),
            truncate_string(row.get('address', row.get('name')), 2000),
            truncate_string(row.get('country_codes'), 200),
            truncate_string(row.get('countries'), 500),
            truncate_string(row.get('sourceid', row.get('source_id')), 100)
        )
        records.append(record)

        if len(records) >= BATCH_SIZE:
            cursor.executemany(insert_sql, records)
            connection.commit()
            total_loaded += len(records)
            print(f"  Loaded {total_loaded:,} addresses...")
            records = []

    if records:
        cursor.executemany(insert_sql, records)
        connection.commit()
        total_loaded += len(records)

    cursor.close()
    print(f"  Completed: {total_loaded:,} addresses loaded")
    return total_loaded


def load_relationships(connection, csv_path):
    """Load relationships (edges) connecting nodes."""
    print(f"Loading relationships from {csv_path}...")

    df = pd.read_csv(csv_path, dtype=str, low_memory=False)
    df.columns = df.columns.str.lower().str.strip()

    cursor = connection.cursor()

    insert_sql = """
        INSERT INTO relationships (
            node_id_start, node_id_end, rel_type, source_id,
            start_date, end_date
        ) VALUES (:1, :2, :3, :4, :5, :6)
    """

    records = []
    total_loaded = 0

    for idx, row in df.iterrows():
        record = (
            truncate_string(row.get('node_id_start', row.get('start')), 50),
            truncate_string(row.get('node_id_end', row.get('end')), 50),
            truncate_string(row.get('rel_type', row.get('type')), 100),
            truncate_string(row.get('sourceid', row.get('source_id')), 100),
            safe_date_parse(row.get('start_date')),
            safe_date_parse(row.get('end_date'))
        )
        records.append(record)

        if len(records) >= BATCH_SIZE:
            cursor.executemany(insert_sql, records)
            connection.commit()
            total_loaded += len(records)
            print(f"  Loaded {total_loaded:,} relationships...")
            records = []

    if records:
        cursor.executemany(insert_sql, records)
        connection.commit()
        total_loaded += len(records)

    cursor.close()
    print(f"  Completed: {total_loaded:,} relationships loaded")
    return total_loaded


def main():
    """Main ingestion workflow."""
    global DB_CONFIG, CSV_DIR

    parser = argparse.ArgumentParser(description='Ingest Panama Papers data into Oracle')
    parser.add_argument('--data-dir', required=True, help='Directory containing CSV files')
    parser.add_argument('--wallet-dir', required=True, help='Directory containing Oracle wallet')
    parser.add_argument('--service', required=True, help='Database service name (e.g., panamapoc_low)')
    parser.add_argument('--user', default='PANAMA_PAPERS', help='Database user')
    parser.add_argument('--password', help='Database password')
    args = parser.parse_args()

    CSV_DIR = args.data_dir

    # Get password - default for PANAMA_PAPERS user created by Liquibase
    password = args.password
    if not password:
        if args.user.upper() == 'PANAMA_PAPERS':
            password = 'PanamaPapers2024!'
        else:
            # Try environment or .env file for ADMIN
            password = os.environ.get('ADB_ADMIN_PASSWORD')
            if not password:
                env_file = Path(__file__).parent.parent / '.env'
                if env_file.exists():
                    for line in env_file.read_text().splitlines():
                        if line.startswith('ADB_ADMIN_PASSWORD='):
                            password = line.split('=', 1)[1].strip().strip('"\'')
                            break

    if not password:
        print("Error: No password provided. Use --password")
        return

    # Read wallet password
    wallet_password_file = Path(args.wallet_dir) / 'wallet_password.txt'
    if wallet_password_file.exists():
        wallet_password = wallet_password_file.read_text().strip()
    else:
        print(f"Error: Wallet password file not found: {wallet_password_file}")
        return

    # Configure connection for ADB with wallet
    DB_CONFIG = {
        'user': args.user,
        'password': password,
        'dsn': args.service,
        'config_dir': args.wallet_dir,
        'wallet_location': args.wallet_dir,
        'wallet_password': wallet_password
    }

    print("=" * 60)
    print("Panama Papers Data Ingestion")
    print("=" * 60)

    print("\nConnecting to database...")
    connection = get_connection()
    print(f"Connected to: {connection.dsn}")

    stats = {}

    def table_count(table):
        cursor = connection.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        cursor.close()
        return count

    try:
        # Skip tables that already have data (allows resume)
        if table_count('entities') > 0:
            stats['entities'] = table_count('entities')
            print(f"Skipping entities (already has {stats['entities']:,} records)")
        else:
            stats['entities'] = load_entities(
                connection, os.path.join(CSV_DIR, 'nodes-entities.csv'))

        if table_count('officers') > 0:
            stats['officers'] = table_count('officers')
            print(f"Skipping officers (already has {stats['officers']:,} records)")
        else:
            stats['officers'] = load_officers(
                connection, os.path.join(CSV_DIR, 'nodes-officers.csv'))

        if table_count('intermediaries') > 0:
            stats['intermediaries'] = table_count('intermediaries')
            print(f"Skipping intermediaries (already has {stats['intermediaries']:,} records)")
        else:
            stats['intermediaries'] = load_intermediaries(
                connection, os.path.join(CSV_DIR, 'nodes-intermediaries.csv'))

        if table_count('addresses') > 0:
            stats['addresses'] = table_count('addresses')
            print(f"Skipping addresses (already has {stats['addresses']:,} records)")
        else:
            stats['addresses'] = load_addresses(
                connection, os.path.join(CSV_DIR, 'nodes-addresses.csv'))

        if table_count('relationships') > 0:
            stats['relationships'] = table_count('relationships')
            print(f"Skipping relationships (already has {stats['relationships']:,} records)")
        else:
            stats['relationships'] = load_relationships(
                connection, os.path.join(CSV_DIR, 'relationships.csv'))

        print("\n" + "=" * 60)
        print("Ingestion Complete")
        print("=" * 60)
        for table, count in stats.items():
            print(f"  {table}: {count:,} records")
        print(f"  Total: {sum(stats.values()):,} records")

    finally:
        connection.close()
        print("\nConnection closed.")


if __name__ == '__main__':
    main()
