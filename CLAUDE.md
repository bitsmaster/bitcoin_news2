# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the bot

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in credentials
python main.py
```

For a quick test cycle, set `CHECK_INTERVAL_MINUTES=1` in `.env` before starting.

Default interval is **1440 minutes (24h)**.

## Architecture

The bot follows a linear pipeline on each scheduled tick:

```
scheduler.py → metrics/aggregator.py → scoring.py → notifier.py
```

**`bot/config.py`** — Single source of truth for all settings. Every module receives a `Settings` dataclass; nothing else calls `os.getenv`. `ConfigError` is raised at startup with a full list of validation failures if `.env` is misconfigured.

**`bot/metrics/`** — Three independent fetchers, each raising `MetricFetchError` on failure:
- `coingecko.py` — current price (USD + BRL) and 200-day daily history; MAs computed locally via `statistics.mean`
- `fear_greed.py` — Fear & Greed Index from alternative.me (no key required)
- `mvrv.py` — MVRV Ratio from CoinMetrics Community API (`CapMVRVCur` metric, no key required)

`aggregator.py` orchestrates all three. Price/history failures are **fatal** (re-raised, cycle skipped). MVRV and Fear & Greed failures are **non-fatal** (field set to `None`, 0 pts awarded for that dimension).

**`bot/scoring.py`** — Pure functions with no I/O. Takes `MetricSnapshot`, returns `ScoringResult`. Max score without MVRV is 60 pts (30 F&G + 30 MAs); with MVRV the max is 100 pts. Default thresholds: Forte ≥ 45, Moderado ≥ 30 (calibrated for no-MVRV baseline).

**`bot/notifier.py`** — Formats messages in Portuguese with HTML tags for Telegram (`parse_mode="HTML"`). Email receives the same text with tags stripped. `notify_startup()` fires once before the scheduler begins. `notify()` with `force=True` sends the weekly summary regardless of score.

**`bot/scheduler.py`** — `BlockingScheduler` (APScheduler, synchronous). Runs `run_check_cycle` on an interval and `run_weekly_status` every Sunday at 09:00 Brazil time. First cycle runs immediately on startup (`next_run_time=datetime.now()`).

## Scoring table

| Metric | Condition | Points |
|---|---|---|
| MVRV | < 1.0 | 40 |
| MVRV | 1.0–2.0 | 20 |
| MVRV | 2.0–3.5 | 5 |
| Fear & Greed | < 25 | 30 |
| Fear & Greed | 25–44 | 15 |
| Fear & Greed | 45–55 | 5 |
| Moving averages | price < MA200 | 30 |
| Moving averages | price < MA50 (above MA200) | 15 |

`score_moving_averages` checks MA200 first; only falls through to the MA50 branch if price is **above** MA200.

## 7-day drop alert (bot/drop_alert.py + bot/state.py)

Independent of the scoring pipeline. Runs every daily cycle alongside the normal check.

**Logic:**
- **Normal mode:** compare current price vs `price_7d_ago` (7th entry from the end of the CoinGecko historical array). If drop ≥ 10%: send alert, enter cooldown.
- **Cooldown (7 days):** skip all drop checks. `bot_state.json` stores `last_drop_signal_date` + `last_drop_signal_price`.
- **Post-cooldown check:** compare current price vs price at the signal date. If drop ≥ 10% again: new alert + new 7-day cooldown. If not: reset to normal mode (next cycle uses rolling 7-day window again).

State is persisted in `bot_state.json` (gitignored, lives on the server). Corrupted/missing file resets to normal mode safely.

## Key constraints

- `GLASSNODE_API_KEY` in `.env` is accepted but unused — MVRV now comes from CoinMetrics Community API (no key needed). The field is retained in `Settings` for future use.
- At least one notifier (`TELEGRAM_ENABLED` or `EMAIL_ENABLED`) must be `true` or startup fails.
- If adding a new metric source, raise `MetricFetchError` on any failure and handle it as non-fatal in `aggregator.collect()`.
