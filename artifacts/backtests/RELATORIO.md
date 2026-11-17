# Amostra de backtest

Números de um ponto de partida. Não são promessa de lucro e não foram otimizados contra esta amostra.

### b3 — `orb_vwap_trend`

- Fonte: série sintética para o estudo rodar sem corretora; não é pregão da B3
- Período: 2024-08-01T09:00:00-03:00 → 2024-09-25T18:20:00-03:00 (9040 barras)
- Fora da amostra desde: 2024-09-10
- Amostra cheia: 80 trades, acerto 22.5%, fator de lucro 1.21, PnL 804.20 BRL, drawdown 4.6%, Sharpe 1.67
- Fora da amostra: 24 trades, PnL 875.56 BRL, Sharpe 2.42

### crypto — `ema_trend_atr`

- Fonte: klines públicos USD-M e funding de data.binance.vision (o REST fapi devolveu HTTP 451 nesta rede)
- Período: 2026-07-20T15:00:00+00:00 → 2026-11-16T23:45:00+00:00 (22920 barras)
- Fora da amostra desde: 2026-10-12
- Amostra cheia: 41 trades, acerto 19.5%, fator de lucro 0.40, PnL -607.71 USDT, drawdown 8.3%, Sharpe -2.22
- Fora da amostra: 17 trades, PnL -449.14 USDT, Sharpe -2.32
- Amostra cheia travou: drawdown máximo. O passe fora da amostra é outro processo, com equity nova.

### nasdaq — `ny_open_range`

- Fonte: série sintética da sessão de Nova York; não é o book da IC Markets
- Período: 2024-09-03T09:30:00-04:00 → 2024-10-28T15:55:00-04:00 (3120 barras)
- Fora da amostra desde: 2024-10-11
- Amostra cheia: 30 trades, acerto 16.7%, fator de lucro 0.81, PnL -221.47 USD, drawdown 6.1%, Sharpe -0.80
- Fora da amostra: 12 trades, PnL -241.66 USD, Sharpe -2.56
- Amostra cheia travou: drawdown máximo. O passe fora da amostra é outro processo, com equity nova.

### nasdaq — `vwap_mean_reversion`

- Fonte: série sintética da sessão de Nova York; não é o book da IC Markets
- Período: 2024-09-03T09:30:00-04:00 → 2024-10-28T15:55:00-04:00 (3120 barras)
- Fora da amostra desde: 2024-10-11
- Amostra cheia: 65 trades, acerto 33.8%, fator de lucro 0.76, PnL -521.40 USD, drawdown 6.0%, Sharpe -2.90
- Fora da amostra: 30 trades, PnL -452.49 USD, Sharpe -4.28
- Amostra cheia travou: drawdown máximo. O passe fora da amostra é outro processo, com equity nova.

B3 e NASDAQ usam série sintética. Cripto usa klines públicos da Binance.
