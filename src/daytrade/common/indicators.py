"""Indicadores sem olhar para o futuro. Cada update consome só o preço corrente."""

from __future__ import annotations

from daytrade.common.models import Bar


class EMA:
    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("período da EMA tem de ser >= 1")
        self.period = period
        self.k = 2 / (period + 1)
        self.value: float | None = None
        self._seed: list[float] = []

    def update(self, price: float) -> float | None:
        if self.value is None:
            self._seed.append(price)
            if len(self._seed) < self.period:
                return None
            self.value = sum(self._seed) / self.period
            return self.value
        self.value = price * self.k + self.value * (1 - self.k)
        return self.value

    def reset(self) -> None:
        self.value = None
        self._seed.clear()


class ATR:
    """ATR de Wilder."""

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("período do ATR tem de ser >= 1")
        self.period = period
        self.value: float | None = None
        self._prev_close: float | None = None
        self._seed: list[float] = []

    def update(self, high: float, low: float, close: float) -> float | None:
        if self._prev_close is None:
            true_range = high - low
        else:
            true_range = max(
                high - low,
                abs(high - self._prev_close),
                abs(low - self._prev_close),
            )
        self._prev_close = close
        if self.value is None:
            self._seed.append(true_range)
            if len(self._seed) < self.period:
                return None
            self.value = sum(self._seed) / self.period
            return self.value
        self.value = (self.value * (self.period - 1) + true_range) / self.period
        return self.value

    def reset(self) -> None:
        self.value = None
        self._prev_close = None
        self._seed.clear()


def ema_series(values: list[float], period: int) -> list[float | None]:
    calc = EMA(period)
    return [calc.update(v) for v in values]


def atr_series(bars: list[Bar], period: int) -> list[float | None]:
    calc = ATR(period)
    return [calc.update(b.high, b.low, b.close) for b in bars]


def crosses_up(prev_fast: float, prev_slow: float, fast: float, slow: float) -> bool:
    return prev_fast <= prev_slow and fast > slow


def crosses_down(prev_fast: float, prev_slow: float, fast: float, slow: float) -> bool:
    return prev_fast >= prev_slow and fast < slow
