"""SQLite 账存：连接管理与建表。

账表
----
batches          批登记（入账后固定，不提供修改/删除）
refund_orders    退单主表（active / revoked 两态）
refund_segments  退单号段（只存首尾，不逐张展开；撤销后行保留，active 标记随单）
ledger_entries   账目明细：入账(+实收)、退票冲减(-)、撤销冲回(+)，带逐单余额

并发
----
写事务一律 ``BEGIN IMMEDIATE``：同一时刻只允许一个写者，重叠校验与账目写入在
同一事务内原子提交，失败整体回滚保留原账。配合 WAL 与 busy_timeout 支持并发读。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from collections.abc import Iterator

import sqlite3

# 测试可通过环境变量指定临时库；默认挂载到 compose 的 data 卷。
DB_PATH = os.environ.get("REFUND_DB_PATH", "/data/refunds.db")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS batches (
    batch_no        TEXT PRIMARY KEY,
    first_ticket    INTEGER NOT NULL,
    last_ticket     INTEGER NOT NULL,
    ticket_count    INTEGER NOT NULL,
    amount_received INTEGER NOT NULL,           -- 实收金额，整数分
    base_share      INTEGER NOT NULL,           -- 单票基础金额
    extra_shares    INTEGER NOT NULL,           -- 多分 1 分的票数
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS refund_orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_no    TEXT NOT NULL REFERENCES batches(batch_no),
    refund_no   TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    amount      INTEGER NOT NULL,               -- 按原分摊金额计算的冲减额（分）
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    revoked_at  TEXT,
    UNIQUE(batch_no, refund_no)
);

CREATE TABLE IF NOT EXISTS refund_segments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_no    TEXT NOT NULL,                   -- 冗余批次号，重叠校验免 JOIN
    order_id    INTEGER NOT NULL REFERENCES refund_orders(id),
    first_ticket INTEGER NOT NULL,              -- 只存首尾，绝不逐张展开
    last_ticket  INTEGER NOT NULL
);

-- 区间重叠校验的两个索引方向（见 services._find_active_overlap）
CREATE INDEX IF NOT EXISTS idx_seg_batch_start
    ON refund_segments(batch_no, first_ticket, last_ticket);
CREATE INDEX IF NOT EXISTS idx_seg_batch_end
    ON refund_segments(batch_no, last_ticket);

CREATE INDEX IF NOT EXISTS idx_orders_batch ON refund_orders(batch_no);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_no     TEXT NOT NULL REFERENCES batches(batch_no),
    entry_type   TEXT NOT NULL CHECK (entry_type IN ('batch_posting', 'refund', 'reversal')),
    ref_no       TEXT NOT NULL,                 -- 批号 / 退单号
    signed_amount INTEGER NOT NULL,             -- 入账为正，冲减为负，冲回为正
    balance_after INTEGER NOT NULL,             -- 该批逐单余额（分）
    detail_json  TEXT NOT NULL,                 -- 号段等明细，供下游逐单核对
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_ledger_batch
    ON ledger_entries(batch_no, id);
"""


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(
        db_path or DB_PATH,
        timeout=30.0,
        isolation_level=None,  # 手工事务
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={30_000}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | None = None) -> None:
    """幂等建库建表（可重复调用）。"""
    path = db_path or DB_PATH
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """请求级连接（短连接），退出即关闭。"""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def write_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """立即型写事务：提交或整体回滚，失败保留原账。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
