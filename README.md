# TRIADE

Três processos independentes, um por mercado, mais um analista externo que pede mãos mais longas pelo mesmo risco. Cada agente tem o próprio config, os próprios limites, o próprio estudo, a própria análise e a própria execução. Nenhum agente importa o outro. A biblioteca `daytrade` guarda o que é igual: risco, tamanho de posição, backtest, diário e kill switch. O pacote instalável se chama `triade`; o módulo continua `daytrade`.

O dono do sistema é o Diego, no fuso `America/Sao_Paulo`. O modo padrão de estudo é **paper**, no perfil de pesquisa. A conta real começa no perfil `micro_live`, com capital pequeno, e exige as duas travas ao mesmo tempo. O dono dispensou a conta demo porque o preenchimento de lá não batia com o da conta real. Demo continua no código para quem quiser; não é o caminho documentado de partida.

Isto é um ponto de partida configurável. Os números da amostra não são promessa de lucro.

## Estrutura

```
configs/                 YAML de cada agente, com seções llm e micro_live
src/daytrade/common/     risco, execução, backtest, logs, MT5, Binance, analista
src/daytrade/llm/        CLI estreita do analista
src/daytrade/b3/         WIN e WDO, rolagem, calendário da B3
src/daytrade/crypto/     BTCUSDT e ETHUSDT, EMA, funding
src/daytrade/nasdaq/     USTEC, sessão de Nova York, calendário da NYSE
scripts/linux/           Wine, Xvfb, ponte e unidades systemd
scripts/windows/         caminho alternativo, se o VPS for Windows
examples/                pedido de exemplo do analista
data/sample/             CSV de estudo (B3 e NASDAQ sintéticos; cripto real)
artifacts/backtests/     métricas da amostra
tests/                   risco, tamanho, sinais, analista, perfil micro
var/<agente>/            estado, log, diário, fila e eventos (gitignored)
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

## Modelo híbrido

O scalp e o rompimento continuam 100% em Python, no fechamento de cada barra. A segunda fonte é um analista externo (um assistente que você roda a cada 15–30 minutos, ou quando um evento aparece). Ele pede mãos de 30 minutos a algumas horas e pode ligar, desligar e ajustar parâmetros dentro do que o YAML permite.

O analista não fala com a corretora. O comando só valida e deixa um arquivo na fila. O processo do agente, no bar seguinte, passa esse pedido pelo mesmo motor das estratégias: stop obrigatório, risco por trade, perda diária, drawdown, kill switch e horário. Se o agente estiver desligado, o arquivo espera.

O desligamento (`disable`) bloqueia entrada nova das duas fontes. Stop, alvo e tempo máximo da mão que já está aberta continuam. Zerar a conta continua sendo o kill switch ou o `flatten`.

Conflito de fonte, padrão: **uma mão aberta por símbolo**. Quem chegou primeiro fica. A outra fonte é recusada, com o motivo no diário. Não há netting. Se as duas pedirem o mesmo símbolo na mesma barra, o Python entra na fila primeiro e o analista só preenche numa barra seguinte se o símbolo estiver livre. Posição adotada da corretora (`source=broker`) bloqueia as duas.

Cada trade no diário leva `source=python` ou `source=llm`, com a justificativa. O arquivo `var/<agente>/journal/llm.jsonl` guarda a decisão mesmo que o agente esteja fora do ar. Dá para medir as duas fontes em separado. O teto de trades e a perda diária também existem por fonte; estourar a fonte trava só ela. A perda diária e o drawdown da conta travam todo mundo.

Parâmetros que o analista pode mudar ficam em `llm.parameters` de cada YAML. O padrão é estreito (`atr_mult` e os filtros já existentes). Período de EMA não entra: trocar o período no meio do pregão exigiria reconstruir o indicador. Fora da faixa, o comando recusa.

Quando algo relevante acontece fora do backtest, o Python escreve `var/<agente>/events/queue.jsonl` e substitui `events/latest.json`. Os gatilhos atuais são pico de volume (barra acima de `llm.volume_spike_multiple`, padrão 2, contra a média das anteriores), sinal de rompimento do Python e halt. O backtest não escreve esses arquivos, para a amostra continuar reproduzível.

### CLI do analista

Um agente por invocação.

```bash
python -m daytrade.llm b3 context
python -m daytrade.llm b3 status
python -m daytrade.llm b3 submit --file examples/llm-order-win.json
python -m daytrade.llm b3 set-param atr_mult 1.8
python -m daytrade.llm b3 disable
python -m daytrade.llm b3 enable
```

`context` imprime um JSON curto: últimas barras (base, 15m e 60m), VWAP, ATR, volume relativo e perfil, posições com a fonte, PnL do dia por fonte, orçamento de risco que ainda resta, eventos da sessão (leilões da B3, prévias da PTAX, abertura dos EUA, funding) e os halts. Se o agente já rodou em paper ou live, usa `var/<agente>/recent-bars.json`. Sem isso, usa o CSV do config.

O pedido é um objeto JSON, sem campo extra. `idempotency_key` tem de 8 a 36 caracteres `[A-Za-z0-9_-]` e vira o id da ordem na corretora, então um reenvio não duplica. Reenviar a mesma chave devolve o resultado gravado e não entra de novo na fila.

```json
{
  "idempotency_key": "llm-win-20261117-001",
  "symbol": "WIN",
  "side": "buy",
  "qty": 1,
  "entry_type": "market",
  "stop": 127000,
  "take_profit": 129500,
  "max_holding_minutes": 120,
  "rationale": "preço segurou acima da VWAP depois da abertura; mão de duas horas, stop abaixo da faixa"
}
```

`stop` é obrigatório. `take_profit` e `limit_price` são opcionais; `limit_price` só existe quando `entry_type` é `limit`. Sem `max_holding_minutes`, vale o máximo do YAML (240). A quantidade pedida é um teto: o risco pode reduzir, nunca aumentar. Se o lote mínimo da corretora já passa do risco ou da quantidade pedida, a ordem é recusada. Erro de validação sai com código 2 e a linha `erro: ...`.

## Perfil micro_live

O comando `live` sempre aplica `micro_live` e recusa se a seção não existir. Backtest e paper continuam no bloco `risk` de pesquisa, que é o perfil da amostra. As duas travas não mudam: `live_enabled: true` e `DAYTRADE_LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`, exatamente assim.

| Agente | Ponto de partida documentado |
| --- | --- |
| B3 | Equity de referência R$ 5.000, risco 1% por trade, perda diária 2%, drawdown 4%, no máximo 4 trades no dia e 2 por fonte, perda de 0,5% por fonte. No máximo 1 WIN e 1 WDO. |
| Cripto | 1.000 USDT, risco 2%, perda diária 3%, drawdown 6%, USD-M com alavancagem 2x e margem isolada. O tamanho é o menor lote que cobre o notional mínimo (100 USDT no YAML, substituído pelo `exchangeInfo` no `connect`). BTC até 0,01, ETH até 0,1. |
| NASDAQ | 2.000 USD, risco 0,5%, perda diária 1%, drawdown 3%. O lote máximo vira o lote mínimo lido no terminal. |

Um stop largo faz 1 contrato, ou o notional mínimo, estourar o risco. A mão não abre. Isso é o comportamento esperado, não um erro para contornar. No cripto, `micro_live.market: spot` ignora a alavancagem e desliga a venda. Alavancagem acima de 2x é recusada antes de falar com a Binance.

No live da B3 e do NASDAQ o terminal é a fonte do lote, do passo, do tick e do point value. Se `volume_min`, `volume_step`, tick ou valor do tick não puderem ser lidos, o agente não opera. Paper e demo continuam com a tolerância de 5% contra o YAML.

## Instalação

Python 3.11 ou mais novo.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

O extra `mt5` (`pip install -e ".[mt5]"`) é o Python do Windows. No VPS Linux o agente não instala esse pacote: ele fala com um Python de Windows que roda dentro do Wine. Backtest e paper de replay não precisam do terminal.

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

A corretora da B3 entra pelo MetaTrader 5. A primeira opção é o MT5 da XP. Se a XP não oferecer MT5 nessa conta, Clear ou Rico servem: são do mesmo grupo, com outro login, outro servidor e outro `terminal_path`. O nome do servidor não está fixo neste repositório; copie o que o terminal mostrar em Arquivo → Login. O pacote `MetaTrader5` só existe para Windows. No VPS Linux ele roda dentro do Wine, junto do terminal, e o agente fala com ele pela ponte (`mt5.transport: bridge`). No Windows nativo, `mt5.transport: direct`. Backtest e paper de replay não precisam do terminal.

Desde 10/03/2025 a sessão contínua do WIN é 09:00–18:25, com leilão de fechamento por volta de 18:25–18:30. O WDO vai até 18:30 e não tem leilão de fechamento oficial. O leilão de abertura fica perto de 08:45–09:00. O config começa a faixa às 09:05 e zera antes do fim.

Contratos, no modo `specific`:

- WIN: meses pares. Vencimento na quarta-feira mais próxima do dia 15, ou no pregão seguinte se esse dia não tem sessão. Código `WIN` + letra do mês + ano (`WINZ24`). Rola quando restam até `roll_sessions_before` sessões (padrão 2).
- WDO: vence no primeiro pregão do mês. O último dia de negócio é a sessão anterior. Novembro é `X` (`WDOX26`), não `W`. O ponto de cotação vale R$ 10 por contrato; o tick é 0,5. O WIN vale R$ 0,20 por ponto de índice; o tick é 5 pontos.

Custos no YAML são teto de emolumento da página educativa da B3 (WIN cerca de R$ 0,25 por lado, WDO cerca de R$ 1,06 por lado), mais 1 tick de slippage. Corretagem da sua mesa não está aí. Troque pelos valores da nota antes de acreditar no estudo.

O calendário inclui feriados nacionais, 25 de janeiro, Carnaval (segunda e terça), Sexta-feira Santa, Corpus Christi e 24/31 de dezembro como dia sem pregão. Isso é aproximação. O calendário oficial do ano manda: use `calendar.extra_closed` e `extra_open`.

B3 e NASDAQ são dois terminais, dois prefixos Wine, duas portas (`18861` e `18862`), dois logins e dois magic (`26011701` e `26011702`). Não aponte os dois para o mesmo `terminal64.exe`. O cripto não usa nada disso: é Python do Linux e a API da Binance.

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

O símbolo usual no MT5 é `USTEC`. Confira o Market Watch da conta. O YAML de pesquisa assume tick 0,1, lote mínimo 0,1, passo 0,1 e US$ 1 por ponto cheio em 1,0 lote. Isso não foi lido da especificação da corretora. No paper e na demo a ordem é recusada se o point value divergir mais de 5% do YAML. No `live`, o perfil micro adota lote, passo e point value do terminal e recusa a sessão se esses campos não puderem ser lidos. O slippage padrão do estudo é 1 ponto por lado, no lugar de comissão.

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

## VPS Linux perto de São Paulo

O alvo é um Ubuntu ou Debian perto de São Paulo. O fuso da máquina pode ficar em `America/Sao_Paulo`. O agente do NASDAQ continua em `America/New_York` no YAML: o Brasil não tem horário de verão desde 2019 e os Estados Unidos têm.

O cripto é um processo Python do Linux. B3 e NASDAQ não importam `MetaTrader5` nesse processo. Cada um tem o próprio prefixo Wine, o próprio Xvfb, o próprio terminal e uma ponte que só escuta em `127.0.0.1`. Dentro do prefixo roda o Python de Windows com o pacote `MetaTrader5`. O agente manda um JSON por conexão local, com prazo em toda chamada. A ponte não é um atalho de risco: ordem, stop, perda diária, drawdown, kill e horário continuam no agente.

`mt5.transport: bridge` é o padrão destes YAMLs. `direct` é o Python do Windows falando com o terminal sem ponte, no caminho alternativo mais abaixo.

A ponte é frágil. Wine, o terminal e o Python de dentro do prefixo são três processos que podem travar sem derrubar o agente. Um prazo estourado ou um socket fechado vira desconexão: o sinal pendente é descartado, entrada nova fica bloqueada, e a volta passa por reconciliação antes de liberar o livro. A ordem que estava na fila não é reenviada. Se a chamada estourou depois do `order_send`, a ordem pode ter ido; a reconciliação é quem diz o que ficou aberto.

Como ver se a ponte está viva, com o agente parado para não disputar a única conexão:

```bash
systemctl --user start triade-xvfb-b3 triade-bridge-b3
.venv/bin/python -m daytrade.mt5bridge check --config configs/b3.yaml
```

A resposta `{"ok": true, "pong": true, ...}` significa que o processo da ponte aceita conexão. Não significa que o terminal está logado. Com o agente parado, `--init` pede o login e lê a equity. Dois processos inicializando o mesmo terminal brigam; não use `--init` com o agente no ar.

Se o check falhar:

1. `systemctl --user status triade-xvfb-b3 triade-bridge-b3` e o arquivo `var/b3/logs/bridge.log`.
2. Confira se o display existe: `ls /tmp/.X11-unix/X71` (B3) e `X72` (NASDAQ).
3. Confira a porta: `ss -ltnp | grep 18861`. Tem de ser `127.0.0.1`, nunca `0.0.0.0`.
4. Reinicie só a ponte: `systemctl --user restart triade-bridge-b3`. Se o terminal pediu senha de novo, abra o prefixo e faça o login. O agente, quando a ponte volta, reconcilia e escreve isso no diário.
5. Não aponte a B3 e o NASDAQ para o mesmo prefixo nem para a mesma porta. Não faça forward dessa porta para fora da máquina.

### Comandos

Na raiz do projeto, num Ubuntu/Debian:

```bash
sudo apt-get install -y wine wine64 winetricks xvfb cabextract unzip wget ca-certificates python3 python3-venv python3-pip
bash scripts/linux/setup-triade.sh
```

O script cria o venv do Linux (sem o extra `mt5`), copia `.env.example` se ainda não houver `.env`, cria os prefixos `~/.local/share/triade/wine-b3` e `wine-nasdaq`, instala o Python 3.12 de Windows e o `MetaTrader5` dentro de cada um, e grava unidades de usuário do systemd. Elas nascem **desabilitadas**. Os agentes nascem em **paper**. O script não mexe em `live_enabled` e não define `DAYTRADE_LIVE_CONFIRM`.

Instale o terminal em cada prefixo e entre na conta. XP primeiro; Clear ou Rico se a XP não oferecer MT5. IC Markets no outro prefixo:

```bash
WINEPREFIX=$HOME/.local/share/triade/wine-b3 xvfb-run -a wine ~/Downloads/xp-mt5setup.exe
WINEPREFIX=$HOME/.local/share/triade/wine-nasdaq xvfb-run -a wine ~/Downloads/icmarkets-mt5setup.exe
```

Aponte `mt5.terminal_path` para o `terminal64.exe` daquele prefixo (`C:\Program Files\MetaTrader 5\terminal64.exe` é o caminho de dentro do Wine, não o caminho Linux). Preencha o `.env`. Deixe o símbolo no Market Watch.

Subir à mão, ainda em paper:

```bash
systemctl --user start triade-xvfb-b3 triade-bridge-b3
bash scripts/linux/run-agent.sh b3 paper
bash scripts/linux/run-agent.sh crypto paper
```

Log do agente: `var/<agente>/logs/paper.jsonl` (ou `live.jsonl`). Log da ponte: `var/<agente>/logs/bridge.log`. O watcher de `scripts/linux/run-agent.sh` olha `var/KILL_ALL` e `var/<agente>/KILL`. Enquanto um desses arquivos existir, ele espera e não religa o Python. A unidade da ponte reinicia se o Wine cair; ela não manda ordem sozinha. Apagar o kill não zera posição.

Para o boot, depois do checklist: `sudo loginctl enable-linger $USER`, habilite as unidades e só então edite `triade-agent-b3.service` para trocar `paper` por `live`.

```bash
systemctl --user enable --now triade-xvfb-b3 triade-bridge-b3 triade-agent-b3 triade-agent-crypto
```

## VPS Windows, caminho alternativo

Se a máquina for Windows, use `mt5.transport: direct` nos YAMLs da B3 e do NASDAQ. O processo é o Python de Windows, no mesmo computador do terminal, sem Wine e sem ponte. O fuso pode ficar em `America/Sao_Paulo`. O NASDAQ continua em `America/New_York` no YAML.

1. Instale o Python 3.12 de 64 bits (python.org). O wheel do MetaTrader 5 é `win_amd64`.
2. Instale dois terminais, cada um no próprio diretório: o MT5 da XP (ou Clear/Rico, se a XP não tiver MT5) e o MT5 da IC Markets. Anote cada `terminal64.exe`. Não use o mesmo executável para as duas corretoras.
3. Na raiz do projeto, no PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\setup-triade.ps1
```

O script cria `.venv`, instala o projeto com o extra `mt5`, copia `.env.example` para `.env` se ainda não existir e registra três tarefas (`TRIADE-b3`, `TRIADE-crypto`, `TRIADE-nasdaq`). Elas nascem **desabilitadas** e chamam o watcher em modo **paper**. O script não muda `live_enabled` e não define `DAYTRADE_LIVE_CONFIRM`.

4. Preencha `.env` com login, senha e servidor de cada terminal, e as chaves da Binance se for usar o cripto. Aponte `mt5.terminal_path` de `configs/b3.yaml` e `configs/nasdaq.yaml` para o executável certo. Magics: `26011701` na B3 e `26011702` no NASDAQ.
5. Faça login manual em cada terminal e deixe o símbolo no Market Watch (WIN/WDO ou o código contínuo que você escolheu; USTEC na IC Markets).
6. Para subir um agente na mão, ainda em paper:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\run-agent.ps1 -Agent b3 -Mode paper
```

O log do processo fica em `var\<agente>\logs\paper.jsonl` (ou `live.jsonl`). A fila do analista fica em `var\<agente>\llm\`. Os eventos ficam em `var\<agente>\events\`.

7. O watcher olha `var\KILL_ALL` e `var\<agente>\KILL` antes de chamar o Python. Enquanto um desses arquivos existir, ele espera e não reinicia o agente. Apagar o arquivo não zera posição; o kill switch é que cancela e zera.
8. Só depois do checklist abaixo: habilite a tarefa no Agendador, e apenas então troque o argumento para `-Mode live`.

## Checklist para conta real com capital pequeno

Um agente por vez. `live_enabled` continua `false` até o último item. A unidade systemd, ou a tarefa do Windows, continua desabilitada até lá.

1. Leia a amostra de novo. Ela não autoriza a conta. O positivo da B3 é série sintética curta; cripto e NASDAQ furaram o drawdown.
2. Confirme que o comando `live` está no perfil `micro_live`: 1 WIN, 1 WDO, alavancagem no máximo 2x isolada, lote mínimo do USTEC lido no terminal.
3. Substitua emolumento, corretagem e slippage pelos números da nota. Um stop largo em 1 contrato tem de ser recusado quando estoura o risco, e isso precisa aparecer no diário.
4. Confira o código do contrato corrente de WIN e WDO na semana do vencimento.
5. Abra o USTEC no terminal da IC Markets. Se o agente não conseguir ler lote mínimo, passo e valor do tick, ele não opera. Não chute esses números no YAML para furar a recusa.
6. Na Binance, confira margem isolada e alavancagem 2x depois do `connect`. Acima de 2x o processo nem tenta.
7. Mande um pedido do analista com quantidade acima do teto e outro sem stop. Os dois têm de sair com `erro:` e código 2, sem chegar na corretora.
8. Com uma mão Python aberta, o pedido do analista no mesmo símbolo tem de ser recusado. Com a mão do analista aberta, o Python não pode fechá-la.
9. `disable` não zera. O kill switch zera. Teste os dois antes de deixar o processo sozinho.
10. Pare a ponte (`systemctl --user stop triade-bridge-b3`) no meio do paper com terminal. O diário tem de registrar desconexão e nenhuma entrada nova. Suba a ponte e confira a reconciliação. O mesmo vale para uma queda de rede no cripto.
11. Confira feriados do ano (`extra_closed`) e a diferença de horário de verão de Nova York contra São Paulo.
12. `DAYTRADE_LIVE_CONFIRM` só existe na máquina que opera, nunca no git.
13. Aí sim, ainda com capital do `micro_live`: `live_enabled: true`, `mt5.demo: false` (ou chaves live da Binance, não as de testnet), e o comando `live`. O analista continua passando pelo mesmo risco. Ele não aumenta o teto de perda nem o lote máximo.

## Limitações

- Não havia terminal MT5, conta de corretora nem chave da Binance. Ordem demo, testnet e live não foram enviadas. A ponte foi exercitada com um servidor falso (prazo e queda), não com Wine nem com um terminal logado. O lote mínimo do USTEC não foi lido de um terminal nesta máquina.
- Este repositório não chama uma API de modelo. O analista é um processo seu, que usa a CLI. Sem chave de LLM.
- B3 e NASDAQ da amostra são aleatórios com semente `20261117`. Servem para o estudo rodar, não para descrever o pregão.
- O REST de futuros da Binance respondeu 451. O candle ao vivo (`binance_public`) não foi exercitado. O histórico veio do arquivo público da Binance Vision.
- `LOT_SIZE` de BTCUSDT/ETHUSDT não foi lido do `exchangeInfo`. O tick foi inferido dos preços (0,1 e 0,01).
- Calendário da B3 (24/31 de dezembro, Carnaval o dia inteiro) e o fechamento antecipado de julho nos EUA são aproximações.
- Fill parcial ao vivo não é modelado. A reconciliação é o freio.
- O id de ordem tem resolução de minuto. Comentário no MT5 cabe em 31 caracteres; os ids atuais ficam abaixo disso.
- Parar com `kill -9` não zera. Use o kill switch ou `flatten`.
