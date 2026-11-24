"""Pydantic 请求/响应模型。金额与票号一律严格整数（分），拒绝 bool 等隐式转换。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchCreate(StrictModel):
    batch_no: StrictStr = Field(min_length=1, description="批号")
    first_ticket: StrictInt = Field(description="连续整数票号首号")
    last_ticket: StrictInt = Field(description="连续整数票号尾号（含）")
    amount_received: StrictInt = Field(ge=0, description="整批实收金额，整数分")


class SegmentIn(StrictModel):
    first_ticket: StrictInt
    last_ticket: StrictInt


class RefundCreate(StrictModel):
    batch_no: StrictStr = Field(min_length=1)
    refund_no: StrictStr = Field(min_length=1, description="退单号，批号内唯一")
    segments: list[SegmentIn] = Field(min_length=1, description="一个或多个含首尾的号段")


class ReversalCreate(StrictModel):
    batch_no: StrictStr = Field(min_length=1)
    refund_no: StrictStr = Field(min_length=1)


class SegmentOut(BaseModel):
    first_ticket: int
    last_ticket: int
    amount: int = Field(description="该号段按原分摊规则计算的金额（分）")


class BatchOut(BaseModel):
    batch_no: str
    first_ticket: int
    last_ticket: int
    ticket_count: int
    amount_received: int
    base_share: int
    extra_shares: int
    created_at: str


class RefundOut(BaseModel):
    batch_no: str
    refund_no: str
    status: str
    amount: int
    segments: list[SegmentOut]
    idempotent: bool = Field(description="True 表示命中重送，未重复记账")
    created_at: str
    revoked_at: str | None = None


class ReversalOut(BaseModel):
    batch_no: str
    refund_no: str
    status: str
    released_amount: int
    idempotent: bool
    revoked_at: str


class LedgerEntryOut(BaseModel):
    id: int
    entry_type: str
    ref_no: str
    signed_amount: int
    balance_after: int
    detail: dict
    created_at: str


class BatchLedgerOut(BaseModel):
    batch_no: str
    posted_amount: int = Field(description="入账实收（分）")
    total_refund: int = Field(description="累计冲减（正数，分）")
    total_reversal: int = Field(description="累计冲回（正数，分）")
    balance: int = Field(description="当前批次账面余额（分）")
    entries: list[LedgerEntryOut]


class BatchRefundsOut(BaseModel):
    batch_no: str
    refunds: list[RefundOut]
