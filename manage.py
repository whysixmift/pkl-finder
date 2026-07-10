import sys
from app.database.schema_audit import run_schema_audit

def main():
    if len(sys.argv) < 2:
        print("Usage: python manage.py [command]")
        print("Available commands:")
        print("  schema-audit   Compares ORM metadata to the actual SQLite database.")
        sys.exit(1)

    command = sys.argv[1]
    if command == "schema-audit":
        success = run_schema_audit()
        sys.exit(0 if success else 1)
    else:
        print(f"Unknown command: '{command}'")
        sys.exit(1)

if __name__ == "__main__":
    main()
