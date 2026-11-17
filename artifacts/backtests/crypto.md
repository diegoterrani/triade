# Estudo — crypto

Resultado histórico de um ponto de partida. Não é promessa de lucro.

- Barras: 22920
- Início: 2026-07-20T15:00:00+00:00
- Fim: 2026-11-16T23:45:00+00:00
- Fora da amostra a partir de: 2026-10-12
- Estratégia: `{'name': 'ema_trend_atr', 'ema_fast': 20, 'ema_slow': 50, 'atr_period': 14, 'atr_mult': 2.5, 'min_atr_pct': 0.001, 'max_atr_pct': 0.02, 'use_funding_filter': True, 'max_funding_long': 0.0005, 'min_funding_short': -0.0005, 'allow_short': True}`
- Custos: BTCUSDT: fee 0/lado + 0.0400% notional, slippage 1 ticks, ETHUSDT: fee 0/lado + 0.0400% notional, slippage 1 ticks

### Amostra cheia

- Trades: 41 (ganhos 8, perdas 33)
- Taxa de acerto: 19.5%
- Fator de lucro: 0.40
- Drawdown máximo: 845.06 USDT (8.3%)
- Sharpe (120 dias): -2.22
- Expectativa por trade: -14.82 USDT
- PnL líquido: -607.71 USDT
- Custos: 192.63 USDT
- Equity final: 9392.29 USDT

### Dentro da amostra

- Trades: 41 (ganhos 8, perdas 33)
- Taxa de acerto: 19.5%
- Fator de lucro: 0.40
- Drawdown máximo: 845.06 USDT (8.3%)
- Sharpe (120 dias): -2.22
- Expectativa por trade: -14.82 USDT
- PnL líquido: -607.71 USDT
- Custos: 192.63 USDT
- Equity final: 9392.29 USDT

### Fora da amostra

- Trades: 17 (ganhos 2, perdas 15)
- Taxa de acerto: 11.8%
- Fator de lucro: 0.06
- Drawdown máximo: 867.43 USDT (8.3%)
- Sharpe (120 dias): -2.32
- Expectativa por trade: -26.42 USDT
- PnL líquido: -449.14 USDT
- Custos: 86.77 USDT
- Equity final: 9550.86 USDT

O Sharpe usa o último equity de cada dia. Com poucos dias ele quase não diz nada.
