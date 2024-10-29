'''
Strategy 5: Long Mean Reversion High ADX Reversal
To buy stocks that are in an uptrend, have a significant selloff (which is our buy point),
and revert to their mean. 
'''

import webbrowser
import pandas_ta as ta
import pandas as pd
from datetime import datetime, timedelta
from lumibot.backtesting import YahooDataBacktesting
from lumibot.strategies import Strategy
from lumibot.brokers import Alpaca
from lumibot.strategies.strategy import Strategy
from lumibot.entities import Asset
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


class LongMeanReversionHighADXReversal(Strategy):
    
    parameters = {
        "AvgDailyShares": 500000,
        "Ticker": Asset(symbol="AAPL", asset_type=Asset.AssetType.STOCK),
        "TrailStopLoss" : False, # True if you want to use a trail stop with no tp,
                              #False if you want to use a 2:1 tp:sl ratio
        "Plot": True # True if you want to plot the trades, False if you don't want to plot the trades
    }
    
    ##### CORE FUNCTIONS #####
        
    def initialize(self):
        self.sleeptime = "1D" # Execute strategy every day once
        self.will_plot = self.parameters["Plot"]
        self.risk_percent = 0.02 # 2% risk per trade

        if self.is_backtesting and self.will_plot: # Initialize the plot
            self.initialize_plot()
            self.position_ctr = 0
            self.plots = []
    
    def before_market_opens(self):
        
        self.ticker_bars = self.get_historical_prices(self.parameters["Ticker"], 200, "day").df
        
        self.tradeable = self.filter()
        
        self.techincal = self.setup()
        
    def on_trading_iteration(self): 
        
        if self.tradeable and self.techincal:     
            entry_price = self.get_entry_price()
            position_size = self.get_position_sizing()
            if position_size != 0:           
                order = self.create_order(asset = self.parameters["Ticker"],
                                        quantity=position_size,
                                        limit_price=entry_price,
                                        side="buy",
                                        time_in_force="gtd",
                                        good_till_date=self.get_datetime() + timedelta(days=1)
                                        )
                self.submit_order(order)
#               print(f"Order submitted: {order}. Date: {self.get_datetime()}")
    
    def after_market_closes(self):
        # Cancel all open orders apart from stop loss/ take profit orders
        orders = self.get_orders()
        for order in orders:
            if order.status == "new" and order.side == "buy":
                self.cancel_order(order)
            
            if order.status == "new" and order.side == "sell" and (order.good_till_date >= self.get_datetime()): 
                self.cancel_order(order) # cancel the order                
                ord = self.create_order( # Create market order and execute on next day open
                                        asset = self.parameters["Ticker"], 
                                        quantity=order.quantity,
                                        side="sell_on_open",
                                        )
                self.submit_order(ord) 
                
                                        
    def on_canceled_order(self, order):
        
#       print(f"Order canceled: {order}. Status:{order.status} Date: {self.get_datetime()}")
        pass
    
        
    
    def on_filled_order(self, position, order, price, quantity, multiplier):
        '''
        Time-based: After six trading days, if not stopped out and the profit target is not hit,
                    then exit next day market on open.
        '''
        # If the order is filled, we can print the order details
    #    print(f"Order filled: {order}.Status: {order.status} Date: {self.get_datetime()} . Remaining cash: {self.cash}")
        if  order.side == "sell":
            return
        
        take_profit = self.get_take_profit(price)
        stop_loss = self.get_stop_loss(price)
        
        # Update order's take profit and stop loss prices
        order2 = self.create_order(asset = self.parameters["Ticker"],
                                    quantity=order.quantity,
                                    take_profit_price=take_profit,
                                    stop_loss_price= stop_loss,
                                    side="sell",
                                    time_in_force="gtd",
                                    good_till_date=self.get_datetime() + timedelta(days=6)
                                    )
        
        order.add_child_order(order2)
    #    self.submit_order(order2)

        if self.is_backtesting and self.will_plot: 
            self.schedule_plot(price,self.get_datetime(),stop_loss,take_profit) 
            
    
     
    def on_strategy_end(self):
        if self.will_plot:
            self.plot()
            self.fig.write_html(r".\logs\charts\Chart.html")
            webbrowser.open(r".\logs\charts\Chart.html")
                    
    ########################
    
    
    ##### TRADING FUNCTIONS #####
    def filter(self):
        """
Average daily volume over the last fifty trading days of at least 500,000 shares
Average dollar volume of at least $2.5 million over the last fifty trading days.
These two filters combined ensure that if we trade low-priced stocks, we will have sufficient volume.
ATR greater than 4 percent. 
We want to trade volatile stocks because this is a mean reversion system and is only in the stock for a few days.
        """
        shares = self.ticker_bars["volume"].iloc[-50].mean() / self.ticker_bars["close"].iloc[-50].mean()
        if shares < self.parameters["AvgDailyShares"]:
            return False
        
        avg_dollar_volume = self.calculate_dollar_volume(self.ticker_bars, price_column='close', volume_column='volume', window=50)["avg_dollar_volume"].iloc[-1]
        if avg_dollar_volume < 2500000:
            return False
        
        atr = ta.atr(self.ticker_bars["high"], self.ticker_bars["low"], self.ticker_bars["close"], length=10)
        if atr is None or atr.iloc[-1] < 0.04:
            return False
        
        return True
        
    def setup(self):
        """
Close above 100-day SMA plus one ATR of the last ten days.
This measures a more significant uptrend.
Seven-day ADX is greater than fifty-five, showing good strength of movement.
Three-day RSI is less than fifty.
This indicates a moderate pullback.
        """
        sma100 = ta.sma(self.ticker_bars["close"], length=100)
        atr10 = ta.atr(self.ticker_bars["high"], self.ticker_bars["low"], self.ticker_bars["close"], length=10)
        
        if self.ticker_bars["close"].iloc[-1] < (sma100.iloc[-1] + atr10.iloc[-1]):
            return False
        
        adx7 = ta.adx(self.ticker_bars["high"], self.ticker_bars["low"], self.ticker_bars["close"], length=7)
        if adx7 is None or adx7["ADX_7"].iloc[-1] < 55.00:
            return False
        
        rsi3 = ta.rsi(self.ticker_bars["close"], length=3)
        if rsi3 is None or rsi3.iloc[-1] > 50.00:
            return False

        return True
        
    
    
    def calculate_dollar_volume(self,df, price_column='close', volume_column='volume', window=20):
        """
        Calculate dollar volume and related metrics.
        
        Parameters:
        -----------
        df : pandas.DataFrame
            DataFrame containing price and volume data
        price_column : str, default 'close'
            Name of the column containing price data
        volume_column : str, default 'volume'
            Name of the column containing volume data
        window : int, default 20
            Rolling window for average calculations
            
        Returns:
        --------
        pandas.DataFrame
            DataFrame with the original data plus volume metrics
        """
        # Create a copy of the dataframe
        df_vol = df.copy()
        
        # Calculate dollar volume
        df_vol['dollar_volume'] = df_vol[price_column] * df_vol[volume_column]
        
        # Calculate rolling average dollar volume
        df_vol['avg_dollar_volume'] = df_vol['dollar_volume'].rolling(window=window).mean()
        
        # Calculate relative volume (compared to moving average)
        df_vol['relative_volume'] = df_vol['dollar_volume'] / df_vol['avg_dollar_volume']
        
        # Calculate volume momentum (rate of change)
        df_vol['volume_momentum'] = df_vol['dollar_volume'].pct_change(periods=window)
        
        # Add some additional volume metrics
        df_vol['volume_ma'] = df_vol[volume_column].rolling(window=window).mean()
        df_vol['volume_std'] = df_vol[volume_column].rolling(window=window).std()
        df_vol['volume_zscore'] = (df_vol[volume_column] - df_vol['volume_ma']) / df_vol['volume_std']
        
        return df_vol    
    
    
        
    def get_entry_price(self):
        """Buy limit 3 percent below previous close"""
        return self.ticker_bars["close"].iloc[-1] * 0.97
        
        
    def get_stop_loss(self,entry):
        """
        3 times the ATR of the last ten days below the execution price.
        """
        atr = ta.atr(self.ticker_bars["high"], self.ticker_bars["low"], self.ticker_bars["close"], length=10)
        return entry - atr.iloc[-1] * 3
    
    def get_take_profit(self,entry):
        """
        One ATR of the last ten days, then sell next day market on open
        """
        atr10 = ta.atr(self.ticker_bars["high"], self.ticker_bars["low"], self.ticker_bars["close"], length=10)
        return entry + atr10.iloc[-1]
    
    def get_position_sizing(self): 
        """
        2 percent risk and 10 percent maximum percent size
        """
        return round((self.cash / self.ticker_bars["close"].iloc[-1]) * self.risk_percent)

    
    
    
    
    ############################
    
    ##### PLOT FUNCTIONS #####
    
    def schedule_plot(self,price,date,stop_loss,take_profit):
        """Schedule the plot to be executed after the order is filled"""
        self.plots.append({"price": price, "date": date,"stop_loss":stop_loss,"take_profit":take_profit})
        current_date = self.get_datetime()
#       current_date_timestamp = pd.Timestamp(current_date - timedelta(days=60))
        current_date_timestamp = pd.Timestamp(current_date)
        for plot in self.plots:
        #    print (current_date_timestamp - plot["date"])
            if (current_date_timestamp - plot["date"]).days > 0:
                self.position_ctr += 1
                self.plots.remove(plot)      
                # Return a scatter list  
                expiration = plot["date"] + timedelta(days=90)
                
                
                buy = go.Scatter(x=[plot["date"],expiration],
                                 y=[plot["price"],plot["price"]],
                                    mode="lines",
                                    marker=dict(size=[10],color="blue"),
                                    name= f"Order {self.position_ctr}"
                                    )
                
                stop_loss = go.Scatter(x=[plot["date"],expiration],
                                 y=[plot["stop_loss"],plot["stop_loss"]],
                                    mode="lines",
                                    marker=dict(size=[10],color="red"),
                                    name= f"Order {self.position_ctr}"
                                    )
                
                take_profit = go.Scatter(x=[plot["date"],expiration],
                                 y=[plot["take_profit"],plot["take_profit"]],
                                    mode="lines",
                                    marker=dict(size=[10],color="green"),
                                    name= f"Order {self.position_ctr}"
                                    )
                
            #    scatter = [buy,stop_loss,take_profit]
                self.scatters.append(buy)
                self.scatters.append(stop_loss)
                self.scatters.append(take_profit)               
                break        
       
    def initialize_plot(self):
        """Initialize the plot"""
        self.date = self.get_datetime()
        self.fig = go.Figure()
        
        self.scatters = []
        
        self.fig.update_layout(title=f"{self.parameters['Ticker']} - Long Trend High Momentum Strategy",
                            xaxis_title="Date",
                            yaxis_title="Price",
                            template="plotly_dark")
    
    
    def plot(self):
        """Plot the strategy"""
        diff = abs(self.get_datetime() - self.date).days
        data = self.get_historical_prices(self.parameters["Ticker"],diff,"day").df
        self.fig = go.Figure(data=[go.Candlestick(x=data.index,
                                                   open=data['open'],
                                                   high=data['high'],
                                                   low=data['low'],
                                                   close=data['close'])])
        for scatter in self.scatters:
            self.fig.add_traces(scatter)
                # Create buttons to toggle scatter traces
        
        buttons = []
        button_visibility = {}
        for i, scatter in enumerate(self.scatters):
            scatter_name = scatter.name
            if scatter_name not in button_visibility:
                button_visibility[scatter_name] = [True] * (len(self.fig.data) - len(self.scatters)) + [False] * len(self.scatters)
                button_visibility[scatter_name][len(self.fig.data) - len(self.scatters) + i] = True
                button = dict(
                    label=scatter_name,
                    method="update",
                    args=[{"visible": button_visibility[scatter_name]}]
                )
                buttons.append(button)
            else:
                button_visibility[scatter_name][len(self.fig.data) - len(self.scatters) + i] = True
        
        self.fig.update_layout(
        updatemenus=[
            dict(
                active=0,
                buttons=buttons,
                direction="down",
                showactive=True,
                x=0.17,
                xanchor="left",
                y=1.15,
                yanchor="top"
            )
        ]
    )
    
    
        ##### PLOT FUNCTIONS #####

    ############################



def run_live():
        trader = Trader()
        broker = Alpaca(ALPACA_CONFIG)
        strategy = LongMeanReversionHighADXReversal(broker=broker,
                                         parameters={"Ticker": Asset(symbol="NVDA",
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
        budget = 2000
        # Run the backtest    
        LongMeanReversionHighADXReversal.backtest(
            YahooDataBacktesting,
            backtesting_start,
            backtesting_end,
            budget=budget,
            parameters={"Ticker": Asset(symbol="NVDA", asset_type=Asset.AssetType.STOCK)}
        )


if __name__ == "__main__":
    run_backtest()
    #run_live()