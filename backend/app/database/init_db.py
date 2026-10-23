from sqlalchemy.exc import SQLAlchemyError

from app.database.connection import engine
from app.models import Base


def initialize_tables() -> None:
    try:
        Base.metadata.create_all(bind=engine)
    except SQLAlchemyError:
        raise SystemExit(
            "Database initialization failed. Verify the local database "
            "connection and configuration."
        ) from None


def main() -> None:
    initialize_tables()
    print("Initial database tables are present.")


if __name__ == "__main__":
    main()
