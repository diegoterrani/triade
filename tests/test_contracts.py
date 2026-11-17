from __future__ import annotations

from datetime import date

from daytrade.b3.calendar import session_checker
from daytrade.b3.contracts import (
    active_contract,
    contract_code,
    wednesday_closest_to_15,
    wdo_expiration,
    wdo_last_trade,
)


def test_win_december_2024_is_the_18th():
    assert wednesday_closest_to_15(2024, 12) == date(2024, 12, 18)
    is_session = session_checker()
    assert contract_code("WIN", date(2024, 12, 18)) == "WINZ24"
    assert active_contract("WIN", date(2024, 12, 2), 2, is_session) == "WINZ24"
    assert active_contract("WIN", date(2024, 12, 17), 2, is_session) == "WING25"


def test_november_code_is_x_not_w():
    assert contract_code("WDO", date(2026, 11, 2)) == "WDOX26"


def test_wdo_march_2026_last_trade_is_the_previous_session():
    is_session = session_checker()
    assert wdo_expiration(2026, 3, is_session) == date(2026, 3, 2)
    assert wdo_last_trade(2026, 3, is_session) == date(2026, 2, 27)
    assert active_contract("WDO", date(2026, 2, 20), 2, is_session) == "WDOH26"


def test_b3_is_closed_on_christmas_and_weekends():
    is_session = session_checker()
    assert not is_session(date(2024, 12, 25))
    assert not is_session(date(2024, 8, 3))  # sábado
    assert is_session(date(2024, 8, 5))
