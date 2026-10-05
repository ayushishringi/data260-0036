"""Create HW5 tables and add nullable relationship columns to existing installs."""
from backend import models  # noqa: F401
from backend.database import Base, engine


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        dialect = connection.dialect.name
        if dialect == "mysql":
            for statement in (
                "ALTER TABLE vulnerability_reports ADD COLUMN advisory_id INT NULL",
                "ALTER TABLE vulnerability_reports ADD COLUMN available_count INT NOT NULL DEFAULT 1",
                "ALTER TABLE vulnerability_reports ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
                "ALTER TABLE vulnerability_reports ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
                "ALTER TABLE vulnerability_reports ADD COLUMN report_code VARCHAR(80) NULL",
                "UPDATE vulnerability_reports SET report_code = CONCAT('VULN-0036-', LPAD(id, 4, '0')) WHERE report_code IS NULL",
                "ALTER TABLE vulnerability_reports MODIFY COLUMN report_code VARCHAR(80) NOT NULL",
                "ALTER TABLE vulnerability_reports ADD CONSTRAINT uq_vulnerability_reports_report_code UNIQUE (report_code)",
                "ALTER TABLE vulnerability_reports ADD CONSTRAINT fk_reports_advisory "
                "FOREIGN KEY (advisory_id) REFERENCES advisories(id) ON DELETE RESTRICT",
            ):
                try:
                    connection.exec_driver_sql(statement)
                except Exception as exc:
                    message = str(exc)
                    if (
                        "Duplicate column" not in message
                        and "Duplicate key name" not in message
                        and "Duplicate foreign key constraint name" not in message
                        and "Duplicate entry" not in message
                    ):
                        raise
    print("HW5 schema is ready.")


if __name__ == "__main__":
    main()
