import os
import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
)

cursor = conn.cursor()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")

tables = [
    "customers",
    "products",
    "orders",
    "order_items",
    "support_tickets"
]

for table in tables:
    file_path = os.path.join(RAW_DIR, f"{table}.csv")

    df = pd.read_csv(file_path)

    for _, row in df.iterrows():
        cols = ",".join(df.columns)
        placeholders = ",".join(["%s"] * len(df.columns))

        sql = f"""
        INSERT INTO {table}
        ({cols})
        VALUES ({placeholders})
        """

        cursor.execute(sql, tuple(row))

    conn.commit()
    print(f"Loaded {table}")

cursor.close()
conn.close()

print("All data loaded.")