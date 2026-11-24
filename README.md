# 展会团购退票供数 API

展会团购票按整批实收金额登记，财务数仓按退回票号冲减收入的供数服务。
FastAPI + SQLite（账存）+ Docker Compose 启动。

## 核心规则与设计约束

| 约束 | 实现方式 |
| --- | --- |
| 每批登记批号、连续整数票号首尾、实收金额（整数分），入账后固定 | `batches` 表只增不改，无更新/删除接口；批号主键冲突返回 409 |
| 同批单票分摊最多相差 1 分，合计等于实收 | 闭式分摊：`base = amount // n`，`extra = amount % n`；首号起最小的 `extra` 个票号各得 `base+1`，其余得 `base`。恒等式 `base*n + extra = amount` |
| 拆单或改变退票顺序不改变单票金额 | 金额只由票号与批次分摊参数决定（`app/allocation.py`），与退单结构、提交顺序无关；号段入参排序后存储 |
| 退单注明批号、退单号、一个或多个含首尾号段 | `POST /api/refunds`，号段只存首尾 |
| 号段越界、单内重叠、与未撤销退单重叠 → 整单退回 | 校验全部在写事务内；任一失败抛错回滚，不留任何号段/账目残留 |
| 撤销凭退单号释放原号段、按原金额冲回 | 退单 `active → revoked`；重叠查询只认 `active`，号段即释放；冲回金额取建单时固化值 |
| 号段状态与账目明细一起生效，失败保留原账 | 同一 `BEGIN IMMEDIATE` 事务内写号段与 `ledger_entries`，异常整体回滚 |
| 退单/撤销重送不重复记账 | 同批号+退单号+同号段重放原单（`idempotent=true`）；撤销重放原撤销结果，均不产生新账目行 |
| 下游按批查询逐单冲减/冲回明细 | `GET /api/batches/{batch_no}/ledger`，含逐单流水、逐段金额、逐单余额 |
| **全程不逐张展开票号** | 号段表只有首尾两列；号段金额用 O(1) 区间公式（加分区间交集大小），无逐票行、无逐票循环 |
| **核对重叠不遍历该批历史退单** | 区间重叠 SQL `first_ticket <= ? AND last_ticket >= ?` 走复合索引（`EXPLAIN QUERY PLAN` 为 `SEARCH ... USING INDEX`），按批索引定位候选，应用层不加载历史退单 |

并发写者在 `BEGIN IMMEDIATE` 处串行（WAL + `busy_timeout=30s`），
消除“先查后写”的时序窗口：并发重叠退票只有一单成功，并发撤销只入账一次。

## 目录结构

```
app/
  allocation.py   # 分摊与号段金额的 O(1) 纯函数（不展开票号）
  database.py     # SQLite 连接、建表、写事务上下文
  schemas.py      # Pydantic 模型（严格整数，拒绝 bool 伪装）
  services.py     # 业务逻辑：登记/退票/撤销/查询，事务与幂等
  main.py         # FastAPI 路由
tests/            # pytest：纯函数 + 端到端 API + 并发原子性
Dockerfile
docker-compose.yml
requirements.txt
```

## Docker Compose 启动

```bash
docker compose up -d --build
# 服务监听 http://localhost:8000 ，SQLite 数据在命名卷 refund-data（/data/refunds.db）
docker compose logs -f
docker compose down            # 停止；加 -v 同时清除数据卷
```

健康检查：`GET http://localhost:8000/healthz`
交互式文档：`http://localhost:8000/docs`

## API 一览

| 方法/路径 | 说明 |
| --- | --- |
| `POST /api/batches` | 批登记 `{batch_no, first_ticket, last_ticket, amount_received}` |
| `GET /api/batches` / `GET /api/batches/{batch_no}` | 批次清单/详情（含 base/extra 分摊参数） |
| `POST /api/refunds` | 退单 `{batch_no, refund_no, segments:[{first_ticket,last_ticket}...]}` |
| `POST /api/refunds/reverse` | 撤销 `{batch_no, refund_no}` |
| `GET /api/batches/{batch_no}/refunds` | 该批全部退单（含撤销态、逐段金额） |
| `GET /api/batches/{batch_no}/ledger` | 逐单冲减/冲回流水与批次余额 |

### 状态码约定

- `201` 登记/退票成功；`200` 撤销/查询成功
- `400` 号段越界、首尾倒置、单内重叠（整单退回）
- `409` 与未撤销退单重叠、批号/退单号冲突（整单退回）
- `404` 批号或退单不存在；`422` 请求体校验失败（含非严格整数）
- 重送成功仍为 `201/200`，响应体 `idempotent=true` 表示未重复记账

### 金额符号约定（整数分）

`batch_posting` 为正、`refund`（冲减）为负、`reversal`（冲回）为正；
每条流水带 `balance_after`（该批逐单余额），`balance = 实收 - 累计冲减 + 累计冲回`。

## 本地测试（无需 Docker）

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt httpx pytest
pytest -q
```

覆盖：分摊恒等式、号段公式与逐张枚举对照、拆单/顺序不变性、三类整单退回、
幂等重放、撤销释放与冲回、并发退票/并发撤销原子性、无逐票行存储、索引查询计划。
