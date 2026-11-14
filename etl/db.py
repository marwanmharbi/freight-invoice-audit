"""
db.py
-----
One place that knows how to connect to SQL Server.
Every other script imports get_engine() from here.
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import URL

SERVER = "localhost"          # same server name you use in SSMS
DATABASE = "FreightAudit"
DRIVER = "ODBC Driver 18 for SQL Server"


def get_engine():
    url = URL.create(
        "mssql+pyodbc",
        host=SERVER,
        database=DATABASE,
        query={
            "driver": DRIVER,
            "trusted_connection": "yes",        # Windows login, no password
            "TrustServerCertificate": "yes",    # local server, self-signed cert
        },
    )
    return create_engine(url, fast_executemany=True)


if __name__ == "__main__":
    with get_engine().connect() as conn:
        row = conn.exec_driver_sql("SELECT DB_NAME(), @@SERVERNAME").fetchone()
        print(f"Connected to database {row[0]} on server {row[1]}")