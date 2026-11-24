"""测试夹具：每个测试用独立临时 SQLite 库。"""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_refunds.db"
    monkeypatch.setenv("REFUND_DB_PATH", str(db_path))

    from app import database

    importlib.reload(database)  # 让模块级 DB_PATH 指向临时库
    database.init_db()

    from app import services

    importlib.reload(services)
    from app import main

    importlib.reload(main)

    with TestClient(main.app) as c:
        yield c
