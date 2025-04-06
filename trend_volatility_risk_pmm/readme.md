trend_volatility_risk_pmm.py

A custom pure market-making strategy for centralized crypto exchanges (CEX) built on the Hummingbot framework.

This script intelligently adapts spread levels using **volatility indicators**, **trend detection**, and **inventory skew-based risk management**, making it a competition-ready, production-capable bot.

---

Key Features

### 📈 Volatility-Aware Spread
- Calculates short-term price volatility using rolling returns.
- Dynamically adjusts the spread multiplier based on observed volatility.
- Wider spreads in high-volatility periods to reduce overtrading and slippage risk.

Trend Detection Logic
- Uses a short-term vs long-term simple moving average (SMA).
- Biases order spreads during uptrends and downtrends to capture momentum.
  - Tighter sell spreads during uptrend.
  - Tighter buy spreads during downtrend.

Inventory Skew Risk Management
- Analyzes current base and quote balance.
- Skews bid/ask spreads to restore balance:
  - If holding too much base: increases sell aggression.
  - If low on base: increases buy aggression.
- Protects from overexposure to either asset.

---

## ⚙️ Configuration Parameters

```python
exchange = "binance_paper_trade"
trading_pair = "BTC-USDT"
order_amount = 0.005
base_spread = 0.0003
max_spread = 0.005
order_refresh_time = 30
price_type = "mid"  # or "last"
volatility_lookback = 20
inventory_skew_enabled = True
