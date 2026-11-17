from __future__ import annotations

import ast
from pathlib import Path

from daytrade.common.livegate import CONFIRM_VALUE, assert_live_allowed
from daytrade.common.specs import assert_point_value
from daytrade.crypto.binance_api import base_url, is_duplicate_client_order, sign_query
from daytrade.common.errors import LiveGateError, SafetyError
from daytrade.common.mt5_broker import build_order_request
import pytest


def test_live_gate_needs_flag_and_exact_env():
    with pytest.raises(LiveGateError):
        assert_live_allowed("b3", False, {})
    with pytest.raises(LiveGateError):
        assert_live_allowed("b3", True, {})
    with pytest.raises(LiveGateError):
        assert_live_allowed("b3", True, {"DAYTRADE_LIVE_CONFIRM": "true"})
    assert_live_allowed("b3", True, {"DAYTRADE_LIVE_CONFIRM": CONFIRM_VALUE})


def test_binance_signature_and_hosts():
    signed = sign_query("secret", [("symbol", "BTCUSDT"), ("timestamp", "1")])
    assert signed.startswith("symbol=BTCUSDT&timestamp=1&signature=")
    assert signed.endswith("ef9d3d77a34d9a13a21a4c2d7f3e8cb091888a74ca62b5b62f430e78eded95ba")
    assert base_url("usdm", True) == "https://testnet.binancefuture.com"
    assert base_url("usdm", False) == "https://fapi.binance.com"
    assert base_url("spot", True) == "https://testnet.binance.vision"
    assert "testnet" not in base_url("spot", False)
    assert is_duplicate_client_order({"code": -4116, "msg": "duplicate"})


def test_mt5_request_carries_a_stop():
    request = build_order_request(
        venue_symbol="WINZ24",
        side="buy",
        qty=1,
        price=128000,
        stop=127000,
        magic=7,
        client_order_id="b3WINZ24",
        deviation=20,
        reduce_only=False,
    )
    assert request["sl"] == 127000
    with pytest.raises(SafetyError):
        build_order_request(
            venue_symbol="WINZ24",
            side="buy",
            qty=1,
            price=128000,
            stop=None,
            magic=7,
            client_order_id="x",
            deviation=20,
            reduce_only=False,
        )


def test_point_value_mismatch_refuses_the_order():
    with pytest.raises(SafetyError):
        assert_point_value(
            symbol="USTEC",
            config_point_value=1,
            broker_tick_value=10,
            broker_tick_size=1,
        )
    assert assert_point_value(symbol="USTEC", config_point_value=1, broker_tick_value=0.1, broker_tick_size=0.1) == 1


def test_agents_do_not_import_each_other():
    root = Path(__file__).resolve().parents[1] / "src" / "daytrade"
    for agent in ("b3", "crypto", "nasdaq"):
        others = {"b3", "crypto", "nasdaq"} - {agent}
        for path in (root / agent).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for other in others:
                        assert not node.module.startswith(f"daytrade.{other}"), path
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for other in others:
                            assert not alias.name.startswith(f"daytrade.{other}"), path
