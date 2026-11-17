# Estudo — nasdaq

Resultado histórico de um ponto de partida. Não é promessa de lucro.

- Barras: 3120
- Início: 2024-09-03T09:30:00-04:00
- Fim: 2024-10-28T15:55:00-04:00
- Fora da amostra a partir de: 2024-10-11
- Estratégia: `{'name': 'ny_open_range', 'range_start': '09:30', 'range_end': '10:00', 'orb_minutes': 30, 'ema_fast': 9, 'ema_slow': 21, 'atr_period': 14, 'atr_mult': 1.5, 'use_vwap_filter': True, 'use_trend_filter': True, 'one_trade_per_day': True}`
- Custos: USTEC: fee 0/lado + 0.0000% notional, slippage 10 ticks

### Amostra cheia

- Trades: 30 (ganhos 5, perdas 25)
- Taxa de acerto: 16.7%
- Fator de lucro: 0.81
- Drawdown máximo: 636.79 USD (6.1%)
- Sharpe (40 dias): -0.80
- Expectativa por trade: -7.38 USD
- PnL líquido: -221.47 USD
- Custos: 0.00 USD
- Equity final: 9778.53 USD

### Dentro da amostra

- Trades: 28 (ganhos 5, perdas 23)
- Taxa de acerto: 17.9%
- Fator de lucro: 0.89
- Drawdown máximo: 540.31 USD (5.2%)
- Sharpe (40 dias): -0.31
- Expectativa por trade: -4.46 USD
- PnL líquido: -124.99 USD
- Custos: 0.00 USD
- Equity final: 9875.01 USD

### Fora da amostra

- Trades: 12 (ganhos 2, perdas 10)
- Taxa de acerto: 16.7%
- Fator de lucro: 0.50
- Drawdown máximo: 501.49 USD (5.0%)
- Sharpe (40 dias): -2.56
- Expectativa por trade: -20.14 USD
- PnL líquido: -241.66 USD
- Custos: 0.00 USD
- Equity final: 9758.34 USD

O Sharpe usa o último equity de cada dia. Com poucos dias ele quase não diz nada.
