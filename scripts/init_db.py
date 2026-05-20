"""Initialize the SQLite database for query logs."""
from src.observability.database import DEFAULT_DB_PATH, init_db

if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DEFAULT_DB_PATH}")
