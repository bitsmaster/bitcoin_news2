# Bitcoin Bot

Bot de monitoramento de Bitcoin que analisa métricas on-chain e de mercado para identificar oportunidades de compra, enviando alertas via Telegram e/ou e-mail.

## Como funciona

A cada ciclo (padrão: 24h), o bot coleta três métricas, atribui uma pontuação e envia notificação caso o score ultrapasse os limiares configurados:

| Métrica | Fonte | Pontos máximos |
|---|---|---|
| MVRV Ratio | CoinMetrics Community API (sem chave) | 40 |
| Fear & Greed Index | alternative.me (sem chave) | 30 |
| Médias móveis (MA50 / MA200) | CoinGecko (sem chave) | 30 |

**Score máximo sem MVRV:** 60 pts &nbsp;|&nbsp; **Com MVRV:** 100 pts

### Tabela de pontuação

| Métrica | Condição | Pontos |
|---|---|---|
| MVRV | < 1.0 | 40 |
| MVRV | 1.0 – 2.0 | 20 |
| MVRV | 2.0 – 3.5 | 5 |
| Fear & Greed | < 25 | 30 |
| Fear & Greed | 25 – 44 | 15 |
| Fear & Greed | 45 – 55 | 5 |
| Médias móveis | preço < MA200 | 30 |
| Médias móveis | preço < MA50 (acima da MA200) | 15 |

### Alertas

- **Sinal de compra forte:** score ≥ 45 (padrão)
- **Sinal de compra moderado:** score ≥ 30 (padrão)
- **Resumo semanal:** todo domingo às 09h (horário de Brasília), independente do score
- **Alerta de queda:** queda ≥ 10% em 7 dias — com cooldown de 7 dias após disparo

## Instalação

**Requisitos:** Python 3.11+

```bash
pip install -r requirements.txt
cp .env.example .env   # preencha as credenciais
python main.py
```

## Configuração

Copie `.env.example` para `.env` e edite as variáveis:

### Notificadores

Pelo menos um deve estar ativo.

**Telegram**
```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<token do @BotFather>
TELEGRAM_CHAT_ID=<seu chat_id>
```

**E-mail (Gmail)**
```env
EMAIL_ENABLED=true
GMAIL_SENDER=seu_email@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx   # Senha de App do Google
EMAIL_RECIPIENTS=destinatario@email.com
```

### Agendamento

```env
CHECK_INTERVAL_MINUTES=1440   # padrão: 24h; use 1 para testes
WEEKLY_STATUS_ENABLED=true
```

### Limiares de pontuação

```env
SCORE_STRONG_BUY=45    # ajuste para 70 se estiver usando MVRV
SCORE_MODERATE_BUY=30  # ajuste para 50 se estiver usando MVRV
```

### Logging

```env
LOG_LEVEL=INFO
LOG_FILE=bitcoin_bot.log
```

## Estrutura do projeto

```
bitcoin-news/
├── main.py                  # Entrypoint
├── bot/
│   ├── config.py            # Carregamento e validação de configurações
│   ├── scheduler.py         # Agendador de ciclos (APScheduler)
│   ├── scoring.py           # Cálculo de pontuação (sem I/O)
│   ├── notifier.py          # Envio de mensagens (Telegram + e-mail)
│   ├── drop_alert.py        # Alerta de queda de 7 dias
│   ├── state.py             # Persistência de estado (bot_state.json)
│   ├── logger.py            # Configuração de logs
│   └── metrics/
│       ├── aggregator.py    # Orquestra as três fontes de dados
│       ├── coingecko.py     # Preço atual + histórico (MA50/MA200)
│       ├── fear_greed.py    # Fear & Greed Index
│       └── mvrv.py          # MVRV Ratio (CoinMetrics)
├── .env.example
├── requirements.txt
├── Procfile                 # Deploy (ex: Heroku/Railway)
└── runtime.txt
```

## Deploy

O projeto inclui `Procfile` para plataformas como Heroku ou Railway:

```
worker: python main.py
```

## Dependências

- [APScheduler](https://apscheduler.readthedocs.io/) — agendamento de tarefas
- [requests](https://docs.python-requests.org/) — requisições HTTP
- [python-dotenv](https://pypi.org/project/python-dotenv/) — leitura do `.env`
- [pytz](https://pypi.org/project/pytz/) — fusos horários
