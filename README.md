# Três agentes de day trade

Três processos independentes, um por mercado. Cada um tem o próprio config, os próprios limites de risco, o próprio estudo, a própria análise e a própria execução. Nenhum agente importa o outro. Uma biblioteca pequena (`daytrade.common`) guarda o que é igual: risco, tamanho de posição, backtest, diário e kill switch.

O dono do sistema é o Diego, no fuso `America/Sao_Paulo`. O modo padrão é **paper**. Conta real exige duas travas ao mesmo tempo e não está ligada.

Isto é um ponto de partida configurável. Os números da amostra não são promessa de lucro.

## Estrutura

```
configs/                 YAML de cada agente (b3, crypto, nasdaq)
src/daytrade/common/     risco, execução, backtest, logs, MT5, Binance
src/daytrade/b3/         WIN e WDO, rolagem, calendário da B3
src/daytrade/crypto/     BTCUSDT e ETHUSDT, EMA, funding
src/daytrade/nasdaq/     USTEC, sessão de Nova York, calendário da NYSE
data/sample/             CSV de estudo (B3 e NASDAQ sintéticos; cripto real)
artifacts/backtests/     métricas da amostra
tests/                   risco, tamanho, sinais, trilhos de segurança
var/<agente>/            estado, log e diário (gitignored)
```

`python -m daytrade` só mostra a ajuda. Não sobe os três juntos.

## O que cada estratégia faz

As três implementam o mesmo protocolo (`reset`, `on_bar`, `describe`). Trocar o nome no YAML troca a estratégia sem mexer na execução.

**B3 — rompimento da abertura (`orb_vwap_trend`).** A faixa começa às 09:05, depois do leilão, e dura 30 minutos. Compra se o fechamento rompe a máxima, está acima da VWAP e a EMA rápida está acima da lenta. A venda é o espelho. O stop é 1,5 ATR. Uma entrada por ativo por dia. WIN zera às 18:10 (sem mão nova depois das 17:40). WDO zera às 18:15 (sem mão nova depois das 17:50) e não abre mão nova nas prévias da PTAX (10:00, 11:00, 12:00 e 13:00, dez minutos cada). Feriado zera e não abre.

**Cripto — tendência por EMA (`ema_trend_atr`).** EMA 20/50 no gráfico de 15 minutos, stop de 2,5 ATR. Fica de fora se o ATR percentual sai da banda 0,1%–2% ou se o funding passa de 0,05% a favor da mão (compra com funding alto, venda com funding muito negativo). Funding ausente não bloqueia. Janela de ±5 minutos em volta de 00:00, 08:00 e 16:00 UTC também não abre mão. Cruzamento contrário pede saída. No spot o config força `allow_short: false`.

**NASDAQ — dois modos no mesmo config.** O padrão é `ny_open_range`: faixa das 09:30 às 10:00 ET, com os mesmos filtros de VWAP, EMA e ATR da B3. A primeira entrada possível depois do blackout de notícia das 10:00 é a barra das 10:05. O outro modo, `vwap_mean_reversion`, vende quando o preço estica 1,5 ATR acima da VWAP (e compra o espelho), só com as EMAs próximas, e usa a VWAP como alvo. Os dois zeram às 15:45 ET, ou 15 minutos antes de um fechamento antecipado. Não abrem mão em feriado da NYSE nem nas janelas 08:25–08:40 e 09:55–10:05 ET.

O fill do estudo e do paper é na abertura da barra seguinte, piorado pelo slippage. Stop e alvo são olhados na mesma barra, depois do fill. Se stop e alvo caem juntos, vale o stop. Se o preço de entrada estimado já passou do stop, a entrada é descartada.

## Trilhos de segurança

- Modos: `backtest`, `paper`, `live`. O YAML nasce com `live_enabled: false` e `paper_venue: simulate`.
- Live só segue se `live_enabled: true` **e** `DAYTRADE_LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`. `true` ou `1` não servem. Live com `mt5.demo: true` é recusado.
- Toda entrada carrega stop. Sem stop a ordem nem chega na corretora. Se o stop ao vivo falha, a execução desfaz a entrada.
- Teto por trade, lote máximo, máximo de trades no dia, perda diária e drawdown máximo. A perda diária solta no pregão seguinte. O drawdown, com `sticky_drawdown_halt: true`, fica travado até `reset-halt`.
- O código recusa config absurdo: risco por trade acima de 5%, perda diária acima de 20%, drawdown acima de 50%.
- O lote é arredondado para baixo. Se o lote mínimo já estoura o risco, a quantidade é zero e a mão não abre.
- Kill switch por arquivo e por comando. O processo no ar cancela e zera. Apagar o arquivo não religa um processo que já saiu.
- Queda de conexão descarta o sinal pendente e não reentra no escuro. Na volta, a posição da corretora manda. Divergência bloqueia entrada nova e, se aparecer posição desconhecida, adota o tamanho com stop de emergência de 1%.
- Ctrl+C e SIGTERM zeram o paper/live antes de sair. `kill -9` não passa por esse caminho: use o comando de kill ou `flatten` antes.
- Segredos só em ambiente ou `.env` (gitignored). O exemplo está em `.env.example`.
- Log JSONL e diário por agente, em `var/<agente>/`. Telegram existe e nasce desligado; falha de envio não derruba o processo e o token não vai para o log.

O risco é da conta daquele agente. WIN e WDO dividem o limite diário do agente B3. Não há risco cruzado entre B3, cripto e NASDAQ.

## Instalação

Python 3.11 ou mais novo.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

O extra `mt5` (`pip install -e ".[mt5]"`) só existe para Windows. Nesta máquina Linux o backtest e o paper de replay rodam sem ele.

## Como rodar

Cada linha é um processo. Podem subir juntas; não compartilham estado.

```bash
python -m daytrade.b3 backtest
python -m daytrade.crypto backtest
python -m daytrade.nasdaq backtest

python -m daytrade.b3 paper --max-bars 250
python -m daytrade.crypto paper --max-bars 600
python -m daytrade.nasdaq paper --max-bars 120

python -m daytrade.b3 status
python -m daytrade.kill b3
python -m daytrade.kill --all
python -m daytrade.kill b3 --clear
python -m daytrade.b3 reset-halt
python -m daytrade.b3 flatten
```

`--config` vale antes ou depois do subcomando. O backtest também aceita `--data caminho.csv`.

Paper simulado lê o CSV do config e preenche ordens no `PaperBroker`. Não abre terminal e não assina ordem. Para cripto ao vivo de verdade, `paper_venue: testnet` usa `BINANCE_TESTNET_API_KEY` e `BINANCE_TESTNET_API_SECRET` e o host de testnet escolhido pelo código. Para B3 e NASDAQ, `paper_venue: demo` exige `mt5.demo: true` e o terminal de demonstração.

O modo de reversão do NASDAQ, sem editar o arquivo padrão:

```bash
# no YAML, strategy.name: vwap_mean_reversion
python -m daytrade.nasdaq backtest
```

`scripts/run_sample_backtests.py` regenera os quatro relatórios, inclusive os dois modos do NASDAQ.

Testes:

```bash
python -m pytest
```

## B3 e MetaTrader 5

O agente fala com o terminal da corretora brasileira pelo pacote `MetaTrader5`. O wheel oficial é Windows. O processo Python que importa esse pacote tem de ser o Python do Windows, na mesma máquina do terminal. Wine pode abrir o terminal; não substitui o Python de Windows para a API. Backtest e paper de replay não precisam do terminal e foram executados no Linux.

Desde 10/03/2025 a sessão contínua do WIN é 09:00–18:25, com leilão de fechamento por volta de 18:25–18:30. O WDO vai até 18:30 e não tem leilão de fechamento oficial. O leilão de abertura fica perto de 08:45–09:00. O config começa a faixa às 09:05 e zera antes do fim.

Contratos, no modo `specific`:

- WIN: meses pares. Vencimento na quarta-feira mais próxima do dia 15, ou no pregão seguinte se esse dia não tem sessão. Código `WIN` + letra do mês + ano (`WINZ24`). Rola quando restam até `roll_sessions_before` sessões (padrão 2).
- WDO: vence no primeiro pregão do mês. O último dia de negócio é a sessão anterior. Novembro é `X` (`WDOX26`), não `W`. O ponto de cotação vale R$ 10 por contrato; o tick é 0,5. O WIN vale R$ 0,20 por ponto de índice; o tick é 5 pontos.

Custos no YAML são teto de emolumento da página educativa da B3 (WIN cerca de R$ 0,25 por lado, WDO cerca de R$ 1,06 por lado), mais 1 tick de slippage. Corretagem da sua mesa não está aí. Troque pelos valores da nota antes de acreditar no estudo.

O calendário inclui feriados nacionais, 25 de janeiro, Carnaval (segunda e terça), Sexta-feira Santa, Corpus Christi e 24/31 de dezembro como dia sem pregão. Isso é aproximação. O calendário oficial do ano manda: use `calendar.extra_closed` e `extra_open`.

Dois agentes MT5 na mesma máquina Windows são dois processos, dois `terminal_path`, dois logins e dois magic (`26011701` na B3, `26011702` no NASDAQ). Não aponte os dois para o mesmo executável se as corretoras forem diferentes.

`time_offset_hours` fica 0 quando o terminal grava o horário local como se fosse UTC. Ajuste se as barras nascerem deslocadas.

## Cripto e Binance

Cliente REST próprio, sem ccxt. A URL não vem do YAML:

| Mercado | Live | Testnet |
| --- | --- | --- |
| USD-M | `https://fapi.binance.com` | `https://testnet.binancefuture.com` |
| Spot | `https://api.binance.com` | `https://testnet.binance.vision` |

O config nasce em USD-M, BTCUSDT e ETHUSDT, taker de 4 bps por lado, tick 0,10 e 0,01, passo de quantidade 0,001. No `connect`, o live e a testnet comparam isso com o `exchangeInfo` e recusam a ordem se o tick, o passo ou o lote mínimo divergirem.

Nesta rede o REST `fapi.binance.com` respondeu HTTP 451. O histórico público foi baixado de `data.binance.vision` (klines de 15 minutos e funding, 20/07/2026 a 16/11/2026). O tick observado nos preços bate com o YAML. O `LOT_SIZE` oficial não veio no arquivo; o modo live continua recusando ordem se o filtro da corretora for outro. Para repetir o download: `python scripts/download_binance.py`.

`feed.kind: binance_public` puxa o último candle fechado sem chave. Também depende do host de mercado. Se ele estiver bloqueado, use o CSV.

## NASDAQ na IC Markets

A IC Markets oferece MT5 e cTrader. A escolha foi MT5: a mesma API da B3, com outro terminal, outro login e outro magic. cTrader pediria outro protocolo sem mudar o desenho.

O símbolo usual no MT5 é `USTEC`. Confira o Market Watch da conta. O YAML assume tick 0,1, lote mínimo 0,1, passo 0,1 e US$ 1 por ponto cheio em 1,0 lote. Isso não foi lido da especificação da corretora. Antes de qualquer ordem demo ou live, o terminal é consultado e a ordem é recusada se o point value divergir mais de 5% do YAML. O slippage padrão é 1 ponto por lado, no lugar de comissão.

A sessão é 09:30–16:00 ET. O fuso de risco é `America/New_York`. O Brasil não tem horário de verão desde 2019; os Estados Unidos têm. A abertura de Nova York muda uma hora em relação a São Paulo. Feriados e o fechamento das 13:00 (sexta depois do Thanksgiving, 24 de dezembro, véspera aproximada de 4 de julho) estão no código. Confira o calendário do ano.

## Amostra que rodou aqui

Quarenta pregões sintéticos de WIN/WDO (5 minutos, semente fixa) e de USTEC. Cripto é kline público de verdade. Custos do YAML inclusos. Fora da amostra = últimos 30% dos dias, mesmos parâmetros, outro passe. Sharpe com o último equity de cada dia; com poucas dezenas de dias ele quase não informa.

| Agente | Trades | Acerto | Fator de lucro | PnL | Drawdown | Sharpe | Expectativa | Fora da amostra |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| B3 ORB | 80 | 22,5% | 1,21 | +804,20 BRL | 4,6% | 1,67 | +10,05 BRL | 24 trades, +875,56 BRL |
| Cripto EMA | 41 | 19,5% | 0,40 | −607,71 USDT | 8,3% | −2,22 | −14,82 USDT | 17 trades, −449,14 USDT |
| NASDAQ ORB | 30 | 16,7% | 0,81 | −221,47 USD | 6,1% | −0,80 | −7,38 USD | 12 trades, −241,66 USD |
| NASDAQ VWAP | 65 | 33,8% | 0,76 | −521,40 USD | 6,0% | −2,90 | −8,02 USD | 30 trades, −452,49 USD |

Na B3 a janela de dentro da amostra ficou levemente negativa (−71,36 BRL, fator 0,97). O positivo fora da amostra é uma série sintética curta, não uma confirmação.

Na cripto e nos dois modos do NASDAQ a amostra cheia furou o drawdown máximo e travou. O passe de fora da amostra é um processo novo, com equity nova: não é a continuação da conta que já estava travada. Os relatórios completos estão em `artifacts/backtests/`.

Os três paper de replay rodaram ao mesmo tempo, cada um com o próprio `var/<agente>/`, e cada um registrou trade no diário.

## Checklist para ir ao vivo

Faça um agente por vez. `live_enabled` continua `false` até o último item.

1. O estudo fora da amostra não é autorização. Rode paper por vários pregões reais e leia o diário.
2. Substitua emolumento, corretagem, slippage e point value pelos números da sua nota e do símbolo no terminal.
3. Confira o código do contrato corrente de WIN e WDO na semana do vencimento.
4. No NASDAQ, abra o símbolo no MT5 e confira tick, lote mínimo e valor do ponto. Se o terminal divergir mais de 5%, a ordem não sai — ajuste o YAML, não force.
5. Teste o kill switch na conta demo: `python -m daytrade.kill <agente>` tem de cancelar e zerar.
6. Derrube a rede de propósito. O agente não pode reentrar sozinho; na volta, o estado tem de bater com a corretora.
7. Confira feriados do ano (`extra_closed`) e, no NASDAQ, a diferença de horário de verão contra São Paulo.
8. Telegram é opcional. Se ligar, o token fica só no `.env`.
9. `DAYTRADE_LIVE_CONFIRM` só existe na máquina que opera, nunca no git.
10. Aí sim: `live_enabled: true`, `mt5.demo: false` (ou chaves live da Binance, não as de testnet), e o comando `live`.

## Limitações

- Não havia terminal MT5, conta de corretora nem chave da Binance. Ordem demo, testnet e live não foram enviadas. O que foi testado é backtest, paper de replay, risco, tamanho, sinais e as travas que não precisam de corretora.
- B3 e NASDAQ da amostra são aleatórios com semente `20261117`. Servem para o estudo rodar, não para descrever o pregão.
- O REST de futuros da Binance respondeu 451. O candle ao vivo (`binance_public`) não foi exercitado. O histórico veio do arquivo público da Binance Vision.
- `LOT_SIZE` de BTCUSDT/ETHUSDT não foi lido do `exchangeInfo`. O tick foi inferido dos preços (0,1 e 0,01).
- Calendário da B3 (24/31 de dezembro, Carnaval o dia inteiro) e o fechamento antecipado de julho nos EUA são aproximações.
- Fill parcial ao vivo não é modelado. A reconciliação é o freio.
- O id de ordem tem resolução de minuto. Comentário no MT5 cabe em 31 caracteres; os ids atuais ficam abaixo disso.
- Parar com `kill -9` não zera. Use o kill switch ou `flatten`.
