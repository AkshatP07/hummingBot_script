Handwritten Code Explaination (Sorry for bad handwriting) https://drive.google.com/drive/folders/10MV-PyUtNhXlWcQHjkEMeNwj0Q-h2YPC

# 🧠 Custom Market Making Strategy — Hummingbot

This is a **custom script-based market making strategy** for [Hummingbot](https://hummingbot.org/), enhanced with smart trading signals like **trend detection**, **mean reversion (RSI & Bollinger Bands)**, **volatility-based spread adjustment**, and **inventory-aware order placement**.

## 🚀 Strategy Overview

The strategy places buy and sell orders around a reference price and adjusts dynamically based on:

- **Market Trend**: Uses simple moving averages to detect uptrends and downtrends.
- **Mean Reversion**: Counterbalances trend logic with RSI and Bollinger Bands to avoid chasing momentum blindly.
- **Volatility Buffer**: Adapts spread based on recent price fluctuations.
- **Inventory Skew**: Dynamically widens or tightens spreads to rebalance your holdings.
- **Profit Threshold**: Orders are placed only if the expected profit meets a minimum threshold.

## 📦 Features

✅ Mid/Last price selection  
✅ Smart trend + RSI logic  
✅ Dynamic Bollinger Bands  
✅ Inventory-based spread skewing  
✅ Minimum profit spread threshold  
✅ Configurable refresh intervals and lookback windows

---

## 🛠️ Installation

1. Clone or download this repository.
2. Copy `custom_pmm_strategy.py` to your Hummingbot `scripts/` directory:
   ```bash
   cp custom_pmm_strategy.py ~/hummingbot/scripts/

