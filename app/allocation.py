"""单票金额分摊与号段金额汇总（全程闭式公式，不展开票号）。

分摊规则
--------
一批共 ``n = first_ticket - last_ticket + 1`` 张票，实收 ``amount`` 分：

* ``base = amount // n``          每张基础金额
* ``extra = amount % n``          需要多分 1 分的票数
* 从首号起最小的 ``extra`` 个票号各得 ``base + 1`` 分，其余得 ``base`` 分

因此同批单票金额最多相差 1 分，且合计恒等于实收金额。
金额只取决于票号本身，与拆单方式、退票先后顺序无关——同一票号永远是同一金额。
"""

from __future__ import annotations


def ticket_count(first_no: int, last_no: int) -> int:
    """连续整数号段 [first_no, last_no] 的票数。"""
    return last_no - first_no + 1


def split_amount(amount: int, count: int) -> tuple[int, int]:
    """返回 (每张基础金额, 多分 1 分的票数)。"""
    if count <= 0:
        raise ValueError("ticket count must be positive")
    if amount < 0:
        raise ValueError("amount must be non-negative")
    return divmod(amount, count)


def ticket_price(
    ticket_no: int,
    batch_first: int,
    base: int,
    extra: int,
) -> int:
    """单个票号的分摊金额（固定规则，与退票拆单/顺序无关）。"""
    # 票号在批内的 0 基序号；序号 < extra 的票号多 1 分。
    return base + 1 if ticket_no - batch_first < extra else base


def segment_sum(
    seg_first: int,
    seg_last: int,
    batch_first: int,
    base: int,
    extra: int,
) -> int:
    """号段 [seg_first, seg_last] 的分摊金额合计（O(1)，不逐张计算）。

    批内序号小于 ``extra`` 的票号各多 1 分，故只需用整数夹取求出该号段
    与“加分区间 [batch_first, batch_first + extra - 1]”的交集大小。
    """
    count = ticket_count(seg_first, seg_last)
    lo = max(seg_first, batch_first)
    hi = min(seg_last, batch_first + extra - 1)
    extra_in_segment = hi - lo + 1 if hi >= lo else 0
    return base * count + extra_in_segment
