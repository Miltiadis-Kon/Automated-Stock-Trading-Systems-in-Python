"""
Objective: Short stocks in order to hedge when the markets move down.
When long positions start to lose money, this system should offset those losses.
This is the perfect add-on to an LTTF system, to capture those downward moves.
 
From the book : Automated STOCK Trading Systems by Lawrence Bensdorp
"""

import webbrowser
import pandas_ta as ta
import pandas as pd
from datetime import datetime, timedelta
from lumibot.backtesting import YahooDataBacktesting
from lumibot.strategies import Strategy
from lumibot.brokers import Alpaca
from lumibot.strategies.strategy import Strategy
from lumibot.entities import Asset, Order
from lumibot.traders import Trader
import os
from dotenv import load_dotenv
import plotly.graph_objects as go




load_dotenv()

apikey = os.getenv("APCA_API_KEY_PAPER")
apisecret = os.getenv("APCA_API_SECRET_KEY_PAPER")

ALPACA_CONFIG = {
    "API_KEY":apikey,
    "API_SECRET": apisecret,
    "PAPER": True,  # Set to True for paper trading, False for live trading
}

class ShortRSIThrust(Strategy):
    
    parameters = {
        "AvgDailyVolume": 25000000,
        "SmaLength":50,
        "Ticker": Asset(symbol="AAPL", asset_type=Asset.AssetType.STOCK),
        "TrailStopLoss" : False, # True if you want to use a trail stop with no tp,
                              #False if you want to use a 2:1 tp:sl ratio
        "RiskRewardRatio" : 2, # Risk Reward Ratio for the trade
        "RiskPercent": 0.02, # 2 percent risk
        "MaxSizePercent" : 0.1, # 10 percent size
        "MaxPositions" : 10,
        "ATRPeriod" : 10,
        
    }
    
    def check_if_tradeable(self):
        """
        Average daily dollar volume greater than $50 million over the last twenty days.
        Minimum price $5.00.
        """
        bars = self.ticker_bars.iloc[-20:]
        if bars is None:
            print("No data found! Please consider changing the ticker symbol.")
            return False
        if bars["volume"].mean() < self.parameters["AvgDailyVolume"]: # Average daily dollar volume greater than $50 million
            return False
        if bars["close"].min() < 5: # Minimum price $5.00.
            return False
      #  print(f"{self.parameters["Ticker"]} meets the minimum requirements to be traded using the Long Trend High Momentum strategy.")
        
        # Average true range percentage over the last ten days is 3 percent or more of the closing price of the stock.
        atr_percentage = (ta.atr(self.ticker_bars["high"],self.ticker_bars["low"],self.ticker_bars["close"],length=10)/self.ticker_bars["close"]).mean()
        if atr_percentage < 0.03:
            return False
        
        return True
    
    def setup(self):
        '''
        Three-day RSI is above ninety. 
        The last two days the close was higher than the previous day. 
        '''
        rsi = ta.rsi(self.ticker_bars["close"],length=3)
        if rsi.iloc[-1] < 90:
            return False
        if self.ticker_bars["close"].iloc[-1] < self.ticker_bars["close"].iloc[-2]:
            return False
        if self.ticker_bars["close"].iloc[-2] < self.ticker_bars["close"].iloc[-3]:
            return False
        return True
    
    def before_market_opens(self):
        self.ticker_bars = self.get_historical_prices(self.parameters["Ticker"],self.parameters["ATRPeriod"]+1,"day").df
        self.is_tradeable = self.check_if_tradeable()
        self.is_setup_met = self.setup()
        # Check positions
            # Place stop loss 
        
        return super().before_market_opens()
   
    def initialize(self):
        # Strategy parameters
        self.sleeptime = "1D" # Execute strategy every day once
        self.risk_percent = self.parameters["RiskPercent"] # 2 percent risk
        self.max_size_percent = self.parameters["MaxSizePercent"] # 10 percent size
        self.max_positions = self.parameters["MaxPositions"]
        
        # Trading parameters
        self.entry_percent = 0.04  # 4% above previous close
        self.profit_target = 0.04  # 4% profit target
        self.atr_period = self.parameters["ATRPeriod"]  # Period for ATR calculation
        self.atr_multiplier = 3  # Multiplier for stop loss
        
        # Track open positions
        self.positions_data = {}  # Dictionary to track position entry dates and prices
        
        #TODO: fix this
    def position_sizing(self): 
        """Calculate position size based on risk parameters"""
        if len(self.positions_data) >= self.max_positions:
            return 0     
        return int((self.cash / self.ticker_bars["close"].iloc[-1]) * self.risk_percent)

    def get_atr(self):
        """Calculate ATR for the last 10 days"""
        bars = self.ticker_bars
        return ta.atr(bars['high'], bars['low'], bars['close'], length=self.atr_period).iloc[-1]


    def plot(self,order,price,date):
        """Plot the strategy"""
        expiration = date + timedelta(days=2)
        fig = go.Figure(data=[go.Candlestick(x=self.ticker_bars.index,
                open=self.ticker_bars['open'],
                high=self.ticker_bars['high'],
                low=self.ticker_bars['low'],
                close=self.ticker_bars['close'])])
        
        fig.add_trace(go.Scatter(x=[date,expiration],
                                 y=[price,price],
                                 mode="lines",
                                 marker=dict(size=[10],color="blue"),
                                 name="Entry Price"))
        
        fig.add_trace(go.Scatter(x=[date,expiration],
                                 y=[order.stop_loss_price,price],
                                 mode="lines",
                                 marker=dict(size=[10],color="red"),
                                 name="Stop Loss"))
        
        fig.add_trace(go.Scatter(x=[date,expiration],
                                    y=[order.take_profit_price,order.take_profit_price],
                                    mode="lines",
                                    marker=dict(size=[10],color="green"),
                                    name="Take Profit"))
        
        fig.update_layout(title=f"{self.parameters['Ticker']} - Short RSI Thrust",
                            xaxis_title="Date",
                            yaxis_title="Price",
                            template="plotly_dark")
        
        fig.write_html(f".\logs\charts\Chart {order.identifier}.html")        
        webbrowser.open(f".\logs\charts\Chart {order.identifier}.html")

        
        

    def on_trading_iteration(self):
        '''
        Entry : Next day, sell short 4 percent above the previous closing price.
        
        Stop loss : The day after we place the order,
                    place a buy stop of three times ATR of the last ten days above the execution price.
                    
        Take profit : If at the closing price the profit in the position is 4 percent or higher,
                      get out the next day’s market on close.
                         
        Expiration : If after two days the trade has not reached its profit target,
                     we place a market order on close for the next day.
                     
        Position size : 2 percent risk and 10 percent size, a maximum of ten positions 
        '''
        
        if  self.is_tradeable and  self.is_setup_met:
                # Place new orders
                
                # calculate entry price
                entry_price = self.ticker_bars["close"].iloc[-1] * (1 + self.entry_percent)
                # calculate stop loss and take profit
                tp = entry_price * (1 + self.profit_target) # TODO: 4% profit target
                sl = entry_price - self.get_atr() * self.atr_multiplier #TODO: 3 times ATR of the last ten days above the execution price
                # calculate position size
                position_size = self.position_sizing() 
                
                if position_size == 0:
                    return
                # place order
                order = self.create_order(
                    asset=self.parameters["Ticker"],
                    quantity=position_size,
                    side="sell_short",
                    stop_loss_price=sl,
                    take_profit_price=tp,
                    position_filled=True,
                    type="bracket",
                    time_in_force="gtc",
                    good_till_date=self.get_datetime() + timedelta(days=2),
                )
                
                print(f"\nPlacing order: {order.side} {position_size} {order.asset} at {entry_price} on {self.get_datetime()}")            
                order = self.submit_order(order)
                self.plot(order,entry_price,self.get_datetime())
    
    def on_filled_order(self, position, order, price, quantity,multiplier) :
        """Update position data after order is filled"""
        if order.asset == self.parameters["Ticker"]: # Only update data for the traded asset    
            # Print order details
            print(f"Order filled: {order.side} {quantity} {order.asset} at {price} on {self.get_datetime()}")  
            self.positions_data[order.identifier] = {"entry_date": self.get_datetime()} # Update entry date     
        return super().on_filled_order(position, order, price, quantity, multiplier)
        

def run_live():
        trader = Trader()
        broker = Alpaca(ALPACA_CONFIG)
        strategy = ShortRSIThrust(broker=broker,
                                         parameters={"Ticker": Asset(symbol="NIO",
                                                                    asset_type=Asset.AssetType.STOCK)
                                                     }
                                        )

        # Run the strategy live
        trader.add_strategy(strategy)
        trader.run_all()

def run_backtest():
        # Define parameters
        backtesting_start = datetime(2023, 10, 23)
        backtesting_end = datetime(2024, 10, 23)
        budget = 10000
        # Run the backtest    
        ShortRSIThrust.backtest(
            YahooDataBacktesting,
            backtesting_start,
            backtesting_end,
            budget=budget,
            parameters={"Ticker": Asset(symbol="NVDA", asset_type=Asset.AssetType.STOCK)}
        )


if __name__ == "__main__":
    run_backtest()
    #run_live()