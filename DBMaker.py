import csv
import sqlite3

CSV_FILE = 'TestMohammad-Omid - Sheet1.csv'
DB_FILE = 'test_mohammad_omid2.db'
TABLE_NAME = 'data'

def infer_column_types(sample_row):
    types = []
    for value in sample_row:
        try:
            int(value)
            types.append('INTEGER')
        except ValueError:
            try:
                float(value)
                types.append('REAL')
            except ValueError:
                types.append('TEXT')
    return types

def main():
    with open(CSV_FILE, newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        headers = next(reader)
        sample_row = next(reader)
        csvfile.seek(0)
        next(reader)  # skip header again

        # Infer types from the sample row
        column_types = infer_column_types(sample_row)

        # Create table SQL
        columns = [f'"{name}" {col_type}' for name, col_type in zip(headers, column_types)]
        create_table_sql = f'CREATE TABLE IF NOT EXISTS {TABLE_NAME} ({", ".join(columns)});'

        # Connect to SQLite and create table
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(create_table_sql)

        # Insert data
        placeholders = ','.join(['?'] * len(headers))
        insert_sql = f'INSERT INTO {TABLE_NAME} VALUES ({placeholders})'

        # Insert the sample row first
        c.execute(insert_sql, sample_row)

        # Insert the rest of the rows
        for row in reader:
            c.execute(insert_sql, row)

        conn.commit()
        conn.close()
        print(f"Database '{DB_FILE}' created with table '{TABLE_NAME}'.")

if __name__ == '__main__':
    main()