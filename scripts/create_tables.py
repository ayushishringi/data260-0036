from backend import models
from backend.database import Base, engine


Base.metadata.create_all(bind=engine)

print("All HW4 tables created successfully.")