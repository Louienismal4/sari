import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Set the isolated test database before pytest imports any application module.
# The application loads the project-level .env during import, so doing this in
# conftest keeps collection order from ever selecting the Supabase connection.
os.environ["DATABASE_URL"] = "sqlite:///./test_sari.db"
os.environ["OCR_PROVIDER"] = "mock"
