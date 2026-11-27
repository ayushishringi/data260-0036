from backend import models  # noqa: F401 - registers the ORM models on Base.metadata
from backend.database import Base, engine


Base.metadata.create_all(bind=engine)

print("All HW4 tables created successfully.")