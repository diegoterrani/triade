from __future__ import annotations

import pytest

from daytrade.common.prices import floor_step
from daytrade.common.sizing import size_by_risk
from tests.conftest import sample_instrument


def test_floor_step_does_not_round_up():
    assert floor_step(2.9, 1) == 2
    assert floor_step(0.0019, 0.001) == pytest.approx(0.001)
    assert floor_step(0.0004, 0.001) == 0


def test_size_respects_risk_and_lot():
    inst = sample_instrument()
    qty = size_by_risk(10_000, 0.01, entry=101, stop=90, instrument=inst)
    assert qty == 9
    assert qty * abs(101 - 90) * inst.point_value <= 10_000 * 0.01 + 1e-6


def test_size_caps_at_max_qty():
    inst = sample_instrument(max_qty=3)
    assert size_by_risk(10_000, 0.01, 101, 90, inst) == 3


def test_min_lot_that_breaks_the_risk_cap_is_rejected():
    inst = sample_instrument(min_qty=1, point_value=0.2, tick_size=5)
    qty = size_by_risk(1_000, 0.001, entry=128000, stop=127000, instrument=inst)
    assert qty == 0


def test_stop_closer_than_a_tick_is_rejected():
    inst = sample_instrument(tick_size=5)
    assert size_by_risk(10_000, 0.01, entry=100, stop=103, instrument=inst) == 0
