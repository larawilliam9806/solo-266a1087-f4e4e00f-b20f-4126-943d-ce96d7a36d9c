"""端到端 API 测试。

约定示例批：B1 票号 1000..1009 共 10 张，实收 1003 分
=> base=100, extra=3，票 1000/1001/1002 各 101，其余各 100。
"""

import sqlite3
import threading

BATCH = {
    "batch_no": "B1",
    "first_ticket": 1000,
    "last_ticket": 1009,
    "amount_received": 1003,
}


def _register(client, batch=BATCH):
    r = client.post("/api/batches", json=batch)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------ 批登记

def test_register_batch_and_immutable(client):
    body = _register(client)
    assert body["ticket_count"] == 10
    assert body["base_share"] == 100
    assert body["extra_shares"] == 3
    # 重复批号冲突
    r = client.post("/api/batches", json=BATCH)
    assert r.status_code == 409
    # 首尾倒置
    r = client.post(
        "/api/batches",
        json={**BATCH, "batch_no": "B2", "first_ticket": 9, "last_ticket": 1},
    )
    assert r.status_code == 422
    # 布尔值不得冒充整数
    r = client.post(
        "/api/batches",
        json={**BATCH, "batch_no": "B3", "amount_received": True},
    )
    assert r.status_code == 422


def test_zero_amount_batch(client):
    body = _register(
        client, {**BATCH, "batch_no": "BZ", "amount_received": 0}
    )
    assert body["base_share"] == 0 and body["extra_shares"] == 0
    r = client.post(
        "/api/refunds",
        json={"batch_no": "BZ", "refund_no": "R1", "segments": [{"first_ticket": 1000, "last_ticket": 1009}]},
    )
    assert r.status_code == 201 and r.json()["amount"] == 0


# ------------------------------------------------------------ 正常退票 + 金额

def test_refund_amount_segment_formula(client):
    _register(client)
    r = client.post(
        "/api/refunds",
        json={
            "batch_no": "B1",
            "refund_no": "R1",
            "segments": [
                {"first_ticket": 1000, "last_ticket": 1002},  # 101*3 = 303
                {"first_ticket": 1005, "last_ticket": 1006},  # 100*2 = 200
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["amount"] == 503
    assert [s["amount"] for s in body["segments"]] == [303, 200]
    assert body["status"] == "active"
    assert body["idempotent"] is False


def test_split_orders_same_ticket_amounts(client):
    """拆单或改变退票顺序不改变单票金额：不同拆法总额一致。"""
    _register(client)
    # 拆法一：整段一单
    r = client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R1",
              "segments": [{"first_ticket": 1000, "last_ticket": 1009}]},
    )
    assert r.json()["amount"] == 1003
    client.post("/api/refunds/reverse", json={"batch_no": "B1", "refund_no": "R1"})

    # 拆法二：逆序提交三个号段（响应按首号排序），总额不变
    r = client.post(
        "/api/refunds",
        json={
            "batch_no": "B1",
            "refund_no": "R2",
            "segments": [
                {"first_ticket": 1005, "last_ticket": 1009},
                {"first_ticket": 1003, "last_ticket": 1004},
                {"first_ticket": 1000, "last_ticket": 1002},
            ],
        },
    )
    assert r.status_code == 201
    assert r.json()["amount"] == 1003
    assert [s["first_ticket"] for s in r.json()["segments"]] == [1000, 1003, 1005]


# ------------------------------------------------------------ 整单退回场景

def test_out_of_range_whole_order_rejected(client):
    _register(client)
    # 越界：整单退回，无任何残留
    r = client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R1",
              "segments": [{"first_ticket": 999, "last_ticket": 1001}]},
    )
    assert r.status_code == 400
    r = client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R2",
              "segments": [{"first_ticket": 1008, "last_ticket": 1010}]},
    )
    assert r.status_code == 400
    ledger = client.get("/api/batches/B1/ledger").json()
    assert ledger["total_refund"] == 0
    assert client.get("/api/batches/B1/refunds").json()["refunds"] == []


def test_intra_order_overlap_rejected(client):
    _register(client)
    r = client.post(
        "/api/refunds",
        json={
            "batch_no": "B1",
            "refund_no": "R1",
            "segments": [
                {"first_ticket": 1001, "last_ticket": 1004},
                {"first_ticket": 1003, "last_ticket": 1006},  # 与上段重叠
            ],
        },
    )
    assert r.status_code == 400
    # 相邻不重叠应通过
    r = client.post(
        "/api/refunds",
        json={
            "batch_no": "B1",
            "refund_no": "R2",
            "segments": [
                {"first_ticket": 1001, "last_ticket": 1004},
                {"first_ticket": 1005, "last_ticket": 1006},
            ],
        },
    )
    assert r.status_code == 201


def test_overlap_with_active_order_rejected(client):
    _register(client)
    client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R1",
              "segments": [{"first_ticket": 1003, "last_ticket": 1006}]},
    )
    # 边界相接（1007 起）不重叠
    ok = client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R2",
              "segments": [{"first_ticket": 1007, "last_ticket": 1007}]},
    )
    assert ok.status_code == 201
    # 部分重叠、完全包含、跨段覆盖均整单退回
    for seg in [
        {"first_ticket": 1006, "last_ticket": 1006},
        {"first_ticket": 1004, "last_ticket": 1005},
        {"first_ticket": 1000, "last_ticket": 1009},
    ]:
        r = client.post(
            "/api/refunds",
            json={"batch_no": "B1", "refund_no": "RX", "segments": [seg]},
        )
        assert r.status_code == 409
    # 失败单不产生账目
    ledger = client.get("/api/batches/B1/ledger").json()
    assert ledger["total_refund"] == 400 + 100  # R1(100*4) + R2(100)


# ------------------------------------------------------------ 撤销 / 冲回 / 幂等

def test_reversal_releases_segments_and_reverses_at_original_amount(client):
    _register(client)
    client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R1",
              "segments": [{"first_ticket": 1000, "last_ticket": 1002}]},  # 303
    )
    r = client.post(
        "/api/refunds/reverse", json={"batch_no": "B1", "refund_no": "R1"}
    )
    assert r.status_code == 200
    assert r.json()["released_amount"] == 303
    assert r.json()["idempotent"] is False

    # 原号段已释放：同号段新退单成功
    r = client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R2",
              "segments": [{"first_ticket": 1000, "last_ticket": 1002}]},
    )
    assert r.status_code == 201 and r.json()["amount"] == 303

    # 已撤销退单号不得复用
    r = client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R1",
              "segments": [{"first_ticket": 1008, "last_ticket": 1009}]},
    )
    assert r.status_code == 409

    # 撤销不存在的单
    r = client.post(
        "/api/refunds/reverse", json={"batch_no": "B1", "refund_no": "NOPE"}
    )
    assert r.status_code == 404


def test_idempotent_resend_does_not_double_book(client):
    _register(client)
    payload = {
        "batch_no": "B1",
        "refund_no": "R1",
        "segments": [{"first_ticket": 1000, "last_ticket": 1002}],
    }
    first = client.post("/api/refunds", json=payload).json()
    again = client.post("/api/refunds", json=payload).json()
    assert again["idempotent"] is True
    assert again["amount"] == first["amount"] == 303

    # 撤销重送同样幂等
    rev1 = client.post("/api/refunds/reverse", json={"batch_no": "B1", "refund_no": "R1"}).json()
    rev2 = client.post("/api/refunds/reverse", json={"batch_no": "B1", "refund_no": "R1"}).json()
    assert rev1["idempotent"] is False and rev2["idempotent"] is True
    assert rev1["revoked_at"] == rev2["revoked_at"]

    ledger = client.get("/api/batches/B1/ledger").json()
    types = [(e["entry_type"], e["signed_amount"]) for e in ledger["entries"]]
    assert types == [
        ("batch_posting", 1003),
        ("refund", -303),
        ("reversal", 303),
    ]
    assert ledger["balance"] == 1003
    assert ledger["total_refund"] == 303
    assert ledger["total_reversal"] == 303


def test_same_refund_no_different_segments_conflicts(client):
    _register(client)
    client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R1",
              "segments": [{"first_ticket": 1000, "last_ticket": 1001}]},
    )
    r = client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R1",
              "segments": [{"first_ticket": 1008, "last_ticket": 1009}]},
    )
    assert r.status_code == 409


# ------------------------------------------------------------ 账目明细

def test_ledger_running_balance_and_detail(client):
    _register(client)
    client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R1",
              "segments": [{"first_ticket": 1000, "last_ticket": 1002}]},  # -303
    )
    client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R2",
              "segments": [{"first_ticket": 1005, "last_ticket": 1009}]},  # -500
    )
    client.post("/api/refunds/reverse", json={"batch_no": "B1", "refund_no": "R1"})  # +303

    ledger = client.get("/api/batches/B1/ledger").json()
    balances = [e["balance_after"] for e in ledger["entries"]]
    assert balances == [1003, 700, 200, 503]
    assert ledger["balance"] == 503
    refund_entry = next(e for e in ledger["entries"] if e["ref_no"] == "R2")
    assert refund_entry["detail"]["segments"] == [[1005, 1009]]
    assert refund_entry["detail"]["segment_amounts"] == [500]

    refunds = client.get("/api/batches/B1/refunds").json()["refunds"]
    assert [r["status"] for r in refunds] == ["revoked", "active"]


def test_refund_unknown_batch_404(client):
    assert client.post(
        "/api/refunds",
        json={"batch_no": "X", "refund_no": "R1",
              "segments": [{"first_ticket": 1, "last_ticket": 2}]},
    ).status_code == 404
    assert client.get("/api/batches/X/ledger").status_code == 404


# ------------------------------------------------------------ 并发原子性

def test_concurrent_overlapping_refunds_only_one_wins(client):
    _register(client)

    results: list[int] = []
    barrier = threading.Barrier(5)

    def worker(i: int):
        barrier.wait()
        r = client.post(
            "/api/refunds",
            json={
                "batch_no": "B1",
                "refund_no": f"C{i}",
                "segments": [{"first_ticket": 1000, "last_ticket": 1009}],
            },
        )
        results.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results).count(201) == 1
    assert sorted(results).count(409) == 4
    ledger = client.get("/api/batches/B1/ledger").json()
    assert ledger["total_refund"] == 1003  # 只记一次账
    assert ledger["balance"] == 0


def test_concurrent_reversals_only_books_once(client):
    _register(client)
    client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R1",
              "segments": [{"first_ticket": 1000, "last_ticket": 1009}]},
    )
    outcomes: list[int] = []
    barrier = threading.Barrier(5)

    def worker():
        barrier.wait()
        r = client.post(
            "/api/refunds/reverse", json={"batch_no": "B1", "refund_no": "R1"}
        )
        outcomes.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert outcomes.count(200) == 5
    ledger = client.get("/api/batches/B1/ledger").json()
    # 冲回只入账一次：余额恢复为整批实收
    assert ledger["total_reversal"] == 1003
    assert ledger["balance"] == 1003
    reversals = [e for e in ledger["entries"] if e["entry_type"] == "reversal"]
    assert len(reversals) == 1


# ------------------------------------------------------------ 不逐张展开

def test_no_ticket_level_rows(client):
    """号段只存首尾：10 张票的退单在库里只有 1 行号段、0 行逐票数据。"""
    from app import database

    _register(client)
    client.post(
        "/api/refunds",
        json={"batch_no": "B1", "refund_no": "R1",
              "segments": [{"first_ticket": 1000, "last_ticket": 1009}]},
    )
    conn = sqlite3.connect(database.DB_PATH)
    try:
        (seg_rows,) = conn.execute(
            "SELECT COUNT(*) FROM refund_segments"
        ).fetchone()
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()
    assert seg_rows == 1
    assert not any("ticket" in t and t != "refund_segments" for t in tables)
