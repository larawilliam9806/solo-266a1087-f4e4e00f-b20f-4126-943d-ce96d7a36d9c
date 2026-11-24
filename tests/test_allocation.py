"""纯函数测试：分摊恒等式、号段求和与逐张枚举一致、拆单不变性。"""

import pytest

from app.allocation import segment_sum, split_amount, ticket_count, ticket_price


def enumerate_segment_sum(first, last, batch_first, base, extra):
    """对照实现：逐张求和（仅测试用，产品代码不展开票号）。"""
    return sum(ticket_price(n, batch_first, base, extra) for n in range(first, last + 1))


@pytest.mark.parametrize(
    "amount,count", [(1000, 10), (9999, 7), (1, 3), (0, 5), (100, 1), (123456, 97)]
)
def test_split_invariants(amount, count):
    base, extra = split_amount(amount, count)
    # 合计等于实收，单票最多相差 1 分
    assert base * count + extra == amount
    assert 0 <= extra < count


def test_segment_sum_matches_enumeration():
    batch_first, amount, count = 101, 1000, 10  # base=100, extra=0
    base, extra = split_amount(amount, count)
    for first in range(101, 111):
        for last in range(first, 111):
            assert segment_sum(first, last, batch_first, base, extra) == \
                enumerate_segment_sum(first, last, batch_first, base, extra)


def test_segment_sum_with_extra_matches_enumeration():
    batch_first, amount, count = 1000, 1003, 10  # base=100, extra=3
    base, extra = split_amount(amount, count)
    assert extra == 3
    for first in range(1000, 1010):
        for last in range(first, 1010):
            assert segment_sum(first, last, batch_first, base, extra) == \
                enumerate_segment_sum(first, last, batch_first, base, extra)


def test_split_does_not_change_ticket_amount():
    # 同一张票无论和谁组单，金额固定（拆单/顺序无关）
    base, extra = split_amount(1003, 10)  # 1000..1009，前 3 张 101，其余 100
    assert [ticket_price(n, 1000, base, extra) for n in range(1000, 1010)] == \
        [101, 101, 101, 100, 100, 100, 100, 100, 100, 100]
    # 把 1000..1009 拆成任意号段组合，各号段金额之和等于整批实收
    parts = [(1000, 1000), (1001, 1004), (1005, 1009)]
    total = sum(segment_sum(a, b, 1000, base, extra) for a, b in parts)
    assert total == 1003
    assert ticket_count(1000, 1009) == 10


def test_bad_inputs():
    with pytest.raises(ValueError):
        split_amount(10, 0)
    with pytest.raises(ValueError):
        split_amount(-1, 3)
