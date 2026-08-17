import os
import tempfile
import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from app.config import settings
from app.database import Database
from app.rules import RuleEngine
from app.worker import BackgroundWorkerManager

TEST_API_KEY = "c3JpdmFsbGkudGVzdEBleGFtcGxlLmNvbQ.f6f5e6ef44eb17184a65"


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    yield db
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


@pytest.fixture
def client(temp_db):
    settings.API_KEY = TEST_API_KEY
    settings.VERIFY_WEBHOOK_SIGNATURE = False

    main_mod.db = temp_db
    main_mod.rule_engine = RuleEngine(temp_db)
    main_mod.worker_manager = BackgroundWorkerManager(temp_db)

    with TestClient(main_mod.app) as test_client:
        yield test_client
