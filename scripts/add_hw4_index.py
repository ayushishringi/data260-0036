from sqlalchemy import text

from backend.database import engine


INDEX_NAME = "idx_vulnerability_reports_package_name"


def main() -> None:
    with engine.begin() as connection:
        existing_index = connection.execute(
            text(
                """
                SHOW INDEX
                FROM vulnerability_reports
                WHERE Key_name = :index_name
                """
            ),
            {"index_name": INDEX_NAME},
        ).first()

        if existing_index:
            print(f"Index already exists: {INDEX_NAME}")
            return

        connection.execute(
            text(
                f"""
                CREATE INDEX {INDEX_NAME}
                ON vulnerability_reports(package_name)
                """
            )
        )

        print(f"Created index: {INDEX_NAME}")


if __name__ == "__main__":
    main()