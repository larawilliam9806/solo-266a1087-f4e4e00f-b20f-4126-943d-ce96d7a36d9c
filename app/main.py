"""退票供数 API（FastAPI）。

路由
----
POST /api/batches                登记一批团购票（批号/首尾票号/实收分），入账后固定
POST /api/refunds                提交退单（多号段；越界/重叠整单退回）
POST /api/refunds/reverse        凭退单号撤销，释放原号段并按原金额冲回
GET  /api/batches                批次清单
GET  /api/batches/{batch_no}     批次详情（含分摊参数）
GET  /api/batches/{batch_no}/refunds  该批逐单退单（含撤销态）
GET  /api/batches/{batch_no}/ledger  该批逐单冲减/冲回账目明细
GET  /healthz                    存活探针
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import services
from .database import init_db
from .schemas import (
    BatchCreate,
    BatchLedgerOut,
    BatchOut,
    BatchRefundsOut,
    RefundCreate,
    RefundOut,
    ReversalCreate,
    ReversalOut,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="展会团购退票供数 API",
    version="1.0.0",
    description="按号段冲减收入：不逐张展开票号，号段状态与账目原子生效。",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "请求参数校验失败", "detail": exc.errors()},
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/batches", response_model=BatchOut, status_code=201)
def post_batch(payload: BatchCreate) -> BatchOut:
    return services.register_batch(payload)


@app.get("/api/batches", response_model=list[BatchOut])
def get_batches() -> list[BatchOut]:
    return services.list_batches()


@app.get("/api/batches/{batch_no}", response_model=BatchOut)
def get_batch(batch_no: str) -> BatchOut:
    return services.get_batch(batch_no)


@app.post("/api/refunds", response_model=RefundOut, status_code=201)
def post_refund(payload: RefundCreate) -> RefundOut:
    return services.create_refund(payload)


@app.post("/api/refunds/reverse", response_model=ReversalOut)
def post_reversal(payload: ReversalCreate) -> ReversalOut:
    return services.reverse_refund(payload)


@app.get("/api/batches/{batch_no}/refunds", response_model=BatchRefundsOut)
def get_refunds(batch_no: str) -> BatchRefundsOut:
    return services.list_refunds(batch_no)


@app.get("/api/batches/{batch_no}/ledger", response_model=BatchLedgerOut)
def get_ledger(batch_no: str) -> BatchLedgerOut:
    return services.batch_ledger(batch_no)
