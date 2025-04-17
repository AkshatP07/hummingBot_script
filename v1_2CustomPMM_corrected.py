import logging
import os
from decimal import Decimal
from typing import Dict, List , Tuple

from pydantic import Field

from hummingbot.client.config.config_data_types import BaseClientModel, ClientFieldData
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase

class CustomPMMConfig(BaseClientModel):
    script_file_name: str = Field(default_factory=lambda: os.path.basename(__file__))
    exchange: str = Field("binance_paper_trade", client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Exchange"))
    trading_pair: str = Field("BTC-USDT", client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Trading pair"))
    order_amount: Decimal = Field(Decimal("0.005"), client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Order amount (base asset)"))
    base_spread: Decimal = Field(Decimal("0.0003"), client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Base spread"))
    max_spread: Decimal = Field(Decimal("0.005"), client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Max spread on high volatility"))
    risk_aversion: Decimal = Field(Decimal("0.15"), client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Risk aversion (0 to 1)"))
    order_refresh_time: int = Field(30, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Order refresh time (s)"))
    price_type: str = Field("mid", client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Price type (mid or last)"))
    volatility_lookback: int = Field(20, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Volatility window (trades)"))
    inventory_skew_enabled: bool = Field(True, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Enable inventory skew logic"))


class CustomPMM(ScriptStrategyBase):
    create_timestamp = 0
    price_source = PriceType.MidPrice

    @classmethod
    def init_markets(cls, config: CustomPMMConfig):
        cls.markets = {config.exchange: {config.trading_pair}}
        cls.price_source = PriceType.LastTrade if config.price_type == "last" else PriceType.MidPrice

    def __init__(self, connectors: Dict[str, ConnectorBase], config: CustomPMMConfig):
        super().__init__(connectors)
        self.config = config
        self.volatility_buffer: List[Decimal] = []

    def on_tick(self):
        try:
            if self.create_timestamp <= self.current_timestamp:
                self.cancel_all_orders()
                proposal = self.create_proposal()
                proposal_adjusted = self.adjust_proposal_to_budget(proposal)
                self.place_orders(proposal_adjusted)
                self.create_timestamp = self.current_timestamp + self.config.order_refresh_time
        except Exception as e:
            self.logger().error(f"Error in on_tick: {e}")


    def create_proposal(self) -> List[OrderCandidate]:
        connector = self.connectors[self.config.exchange]
        ref_price = Decimal(connector.get_price_by_type(self.config.trading_pair, self.price_source))
        
        if ref_price is None or ref_price <= 0:
            self.logger().warning("Ref price is None or invalid, skipping proposal.")
            return []


        # Track price history for volatility and trend
        self.volatility_buffer.append(ref_price)
        if len(self.volatility_buffer) > self.config.volatility_lookback:
            self.volatility_buffer.pop(0)

        spread_multiplier = self.dynamic_spread_multiplier() * (Decimal("1") + self.config.risk_aversion)
        bid_spread = self.config.base_spread * spread_multiplier
        ask_spread = self.config.base_spread * spread_multiplier
        self.logger().info(f"Spread Multiplier: {spread_multiplier} | Bid Spread: {bid_spread} | Ask Spread: {ask_spread}")

        # Trend adjustment
        trend = self.detect_trend()
        if trend == "uptrend":
            bid_spread *= Decimal("1.2")
            ask_spread *= Decimal("0.8")
        elif trend == "downtrend":
            bid_spread *= Decimal("0.8")
            ask_spread *= Decimal("1.2")

        # Inventory skew
        if self.config.inventory_skew_enabled:
            base_bal = Decimal(connector.get_balance(self.config.trading_pair.split("-")[0]) or 0)
            quote_bal = Decimal(connector.get_balance(self.config.trading_pair.split("-")[1]) or 0)
            self.logger().info(f"Balances: base={base_bal}, quote={quote_bal}")
            denom = base_bal * ref_price + quote_bal 
            if denom == 0:
                inventory_ratio = Decimal("0.5")
            else:
                inventory_ratio = (base_bal * ref_price) / denom
            if inventory_ratio > Decimal("0.6"):
                bid_spread *= Decimal("1.5")
                ask_spread *= Decimal("0.8")
            elif inventory_ratio < Decimal("0.4"):
                bid_spread *= Decimal("0.8")
                ask_spread *= Decimal("1.5")

        # RSI-based spread adjustment
        rsi = self.calculate_rsi()
        self.logger().info(f"RSI: {rsi}")
        if rsi > Decimal("70"):  # Overbought
            bid_spread *= Decimal("1.2")  # more eager to sell -> ask spread should be less so it is multiplied by 0.8
            ask_spread *= Decimal("0.8")
        elif rsi < Decimal("30"):  # Oversold
            bid_spread *= Decimal("0.8")  # more eager to buy
            ask_spread *= Decimal("1.2")
        else:
        # Neutral RSI (more aggressive spreads)
            bid_spread *= Decimal("0.95")
            ask_spread *= Decimal("0.95")
            
        lower, mid, upper = self.calculate_bollinger_bands()
        if ref_price >= upper:
            # Overbought zone
            bid_spread *= Decimal("1.2")
            ask_spread *= Decimal("0.8")
        elif ref_price <= lower:
            # Oversold zone
            bid_spread *= Decimal("0.8")
            ask_spread *= Decimal("1.2")
        else:
            # Normal zone
            bid_spread *= Decimal("0.95")
            ask_spread *= Decimal("0.95")
        self.logger().info(f"Bollinger: Lower={lower}, Mid={mid}, Upper={upper}")
        
        buy_price = ref_price * (Decimal("1") - bid_spread)
        sell_price = ref_price * (Decimal("1") + ask_spread)
        min_profit_threshold = Decimal("0.0001")  # 0.01%
        spread = (sell_price - buy_price) / ref_price
        if spread < min_profit_threshold:
            self.logger().info("Spread too tight, skipping orders.")
            return []

        buy_order = OrderCandidate(self.config.trading_pair, True, OrderType.LIMIT, TradeType.BUY, self.config.order_amount, buy_price)
        sell_order = OrderCandidate(self.config.trading_pair, True, OrderType.LIMIT, TradeType.SELL, self.config.order_amount, sell_price)
        self.logger().info(f"Ref: {ref_price} | Buy @ {buy_price} | Sell @ {sell_price}")

        return [buy_order, sell_order]

    def dynamic_spread_multiplier(self) -> Decimal:
        if len(self.volatility_buffer) < 2:
            return Decimal("1")
        returns = [abs((Decimal(self.volatility_buffer[i]) - Decimal(self.volatility_buffer[i - 1])) / Decimal(self.volatility_buffer[i - 1]))
                for i in range(1, len(self.volatility_buffer))]
        vol = sum(returns) / Decimal(len(returns))
        spread_factor = min(Decimal("1") +  vol * Decimal("10") , self.config.max_spread / self.config.base_spread)
        return spread_factor

    def detect_trend(self) -> str:
        if len(self.volatility_buffer) < 5:
            return "neutral"
        short_window = self.volatility_buffer[-3:]
        long_window = self.volatility_buffer
        sma_short = sum(short_window) / Decimal(len(short_window))
        sma_long = sum(long_window) / Decimal(len(long_window))
        if sma_short > sma_long *  Decimal("1.001"):
            return "uptrend"
        elif sma_short < sma_long * Decimal("0.999"):
            return "downtrend"
        else:
            return "neutral"
        
    def calculate_rsi(self, period: int = 14) -> Decimal:
        if len(self.volatility_buffer) < period + 1:
            return Decimal("50")  # Neutral if not enough data
        gains = []
        losses = []
        for i in range(1, period + 1):
            change = self.volatility_buffer[-i] - self.volatility_buffer[-i - 1]
            if change > 0:
                gains.append(change)
            else:
                losses.append(abs(change))
        avg_gain = sum(gains) / Decimal(period)
        avg_loss = sum(losses) / Decimal(period)
        if avg_loss == 0:
            return Decimal("100")
        rs = avg_gain / avg_loss
        return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))
    
    
    def calculate_bollinger_bands(self, period: int = 20) -> Tuple[Decimal, Decimal, Decimal]:
        if len(self.volatility_buffer) < period:
            return Decimal("0"), Decimal("0"), Decimal("0")
        prices = self.volatility_buffer[-period:]
        sma = sum(prices) / Decimal(period)
        variance = sum([(p - sma) ** 2 for p in prices]) / Decimal(period)
        std_dev = variance.sqrt()
        upper_band = sma + std_dev * 2
        lower_band = sma - std_dev * 2
        return lower_band, sma, upper_band

    def adjust_proposal_to_budget(self, proposal: List[OrderCandidate]) -> List[OrderCandidate]:
        # Makes sure the account has enough balance.
        self.logger().info(f"Orders after budget adjustment: {[str(o) for o in proposal]}")
        # all_or_none=True means: either place both buy and sell orders, or none at all (avoid being one-sided).
        return self.connectors[self.config.exchange].budget_checker.adjust_candidates(proposal, all_or_none=True)

    def place_orders(self, proposal: List[OrderCandidate]):
        for order in proposal:
            self.logger().info(f"Placing order: {order}")
            self.place_order(self.config.exchange, order)

    def place_order(self, connector_name: str, order: OrderCandidate):
        if order.order_side == TradeType.BUY:
            self.buy(connector_name, order.trading_pair, order.amount, order.order_type, order.price)
        else:
            self.sell(connector_name, order.trading_pair, order.amount, order.order_type, order.price)

    def cancel_all_orders(self):
        for order in self.get_active_orders(self.config.exchange):
            self.cancel(self.config.exchange, order.trading_pair, order.client_order_id)

    def did_fill_order(self, event: OrderFilledEvent):
        msg = f"{event.trade_type.name} {round(event.amount, 4)} {event.trading_pair} @ {round(event.price, 2)} on {self.config.exchange}"
        self.log_with_clock(logging.INFO, msg)
        self.notify_hb_app_with_timestamp(msg)
        
    def order_filled_hook(self, event: OrderFilledEvent):
        self.logger().info(f" ORDER FILLED: {event.trade_type.name} {event.amount} {event.trading_pair} @ {event.price}")

        # Show updated balances
        base_asset, quote_asset = event.trading_pair.split("-")
        base_bal = self.connectors[self.config.exchange].get_balance(base_asset)
        quote_bal = self.connectors[self.config.exchange].get_balance(quote_asset)
        self.logger().info(f"Updated Balances — {base_asset}: {base_bal}, {quote_asset}: {quote_bal}")

        # Show total P&L if available
        if hasattr(self, "performance_tracker") and self.performance_tracker:
            realized_pnl = self.performance_tracker.realized_pnl
            self.logger().info(f"Realized P&L so far: {realized_pnl}")

