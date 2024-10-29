'''
System 4: Long Trend Low Volatility


'''

import webbrowser
import numpy as np
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


class LongTrendLowVolatility(Strategy):
    
    parameters = {
        "AvgDailyShares": 1000000,
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
        
        self.snp_bars = self.get_historical_prices(Asset(symbol="SPY", asset_type=Asset.AssetType.STOCK), 200, "day").df
        
        self.tradeable = self.filter()
        
        self.techincal = self.setup()
        
    def on_trading_iteration(self): 
        '''
        Entry on market open.
        No TP.
        Trailing stop of 20%.
        SL of 1.5 * ATR40
        '''
        if self.tradeable and self.techincal:
            # Entry market on open
            position_size = self.get_position_sizing()
            if position_size != 0:           
                order = self.create_order(asset = self.parameters["Ticker"],
                                        quantity=position_size,
                                        side="buy",
                                        trail_percent=0.2,
                                        )
                self.submit_order(order)
#               print(f"Order submitted: {order}. Date: {self.get_datetime()}")
 
        
           
    def on_filled_order(self, position, order, price, quantity, multiplier):
        
        # If the order is filled, we can print the order details
    #    print(f"Order filled: {order}.Status: {order.status} Date: {self.get_datetime()} . Remaining cash: {self.cash}")
        if  order.side == "sell":
            return
        
        stop_loss = self.get_stop_loss(price)
        # Update order's take profit and stop loss prices
        order2 = self.create_order(asset = self.parameters["Ticker"],
                                    quantity=order.quantity,
                                    stop_loss_price= stop_loss,
                                    side="sell_to_open",
                                    time_in_force="gtc"
                                    )
        
        order.add_child_order(order2)
    #    self.submit_order(order2)

        if self.is_backtesting and self.will_plot: 
            self.schedule_plot(price,self.get_datetime(),stop_loss,None) 
            
    
     
    def on_strategy_end(self):
        if self.will_plot:
            self.plot()
            self.fig.write_html(r".\logs\charts\Chart.html")
            webbrowser.open(r".\logs\charts\Chart.html")
                    
    ########################
    
    
    ##### TRADING FUNCTIONS #####
    def filter(self):
        """
        Average daily dollar volume greater than $100 million over the last fifty days.
        Historic volatility rating between 10 and 40 percent, which puts us in the lower range on that metric.
        """
        if self.ticker_bars["volume"].iloc[-50].mean() < 100000000:
            return False
        
        historical_volatility = self.calculate_historical_volatility(self.ticker_bars, price_column='close', window=21, trading_days=252)["annualized_volatility"].iloc[-1]
        
#       print(historical_volatility)
        
        if historical_volatility < 0.1 or historical_volatility > 0.4:
            return False
        
        return True
        
    def setup(self):
        """
        Close of the S&P 500 is above 200-day simple moving average. 
        Close of the stock is above the 200-day simple moving average.
        """
        sma200 = ta.sma(self.ticker_bars["close"], length=200)
        if self.ticker_bars["close"].iloc[-1] < sma200.iloc[-1]:
            return False
        
        sma200_snp = ta.sma(self.snp_bars["close"], length=200)
        
        if self.snp_bars["close"].iloc[-1] < sma200_snp.iloc[-1]:
            return False
        
        return True
    
    
    def calculate_historical_volatility(self,df, price_column='close', window=21, trading_days=252):
        """
        Calculate historical volatility for a given price series.
        
        Parameters:
        -----------
        df : pandas.DataFrame
            DataFrame containing the price data
        price_column : str, default 'close'
            Name of the column containing price data
        window : int, default 21
            Rolling window for volatility calculation (typically 21 for monthly)
        trading_days : int, default 252
            Number of trading days in a year
            
        Returns:
        --------
        pandas.DataFrame
            DataFrame with the original data plus volatility metrics
        """
        # Create a copy of the dataframe
        df_vol = df.copy()
        
        # Calculate daily returns
        df_vol['daily_return'] = df_vol[price_column].pct_change()
        
        # Calculate daily log returns
        df_vol['log_return'] = np.log(df_vol[price_column] / df_vol[price_column].shift(1))
        
        # Calculate rolling standard deviation of log returns
        df_vol['volatility'] = df_vol['log_return'].rolling(window=window).std()
        
        # Annualize the volatility
        df_vol['annualized_volatility'] = df_vol['volatility'] * np.sqrt(trading_days)
        
        # Convert volatility to percentage
        df_vol['volatility_pct'] = df_vol['volatility'] * 100
        df_vol['annualized_volatility_pct'] = df_vol['annualized_volatility'] * 100
        
        return df_vol    
        
        
    def get_stop_loss(self,entry):
        """
        The day after execution, we place a stop-loss of 
        one-and-a-half times the average true range (ATR) 
        of the last forty days below the execution price.        
        """
        atr = ta.atr(self.ticker_bars["high"], self.ticker_bars["low"], self.ticker_bars["close"], length=40)
        return entry - atr.iloc[-1] * 1.5
    
    
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
                
                self.scatters.append(buy)

                
                if plot["stop_loss"]:
                
                    stop_loss = go.Scatter(x=[plot["date"],expiration],
                                 y=[plot["stop_loss"],plot["stop_loss"]],
                                    mode="lines",
                                    marker=dict(size=[10],color="red"),
                                    name= f"Order {self.position_ctr}"
                                    )
                    
                    self.scatters.append(stop_loss)
                
                if plot["take_profit"]:
                    take_profit = go.Scatter(x=[plot["date"],expiration],
                                 y=[plot["take_profit"],plot["take_profit"]],
                                    mode="lines",
                                    marker=dict(size=[10],color="green"),
                                    name= f"Order {self.position_ctr}"
                                    )
                    self.scatters.append(take_profit)               

            #    scatter = [buy,stop_loss,take_profit]
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
        strategy = LongTrendLowVolatility(broker=broker,
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
        budget = 10000
        # Run the backtest    
        LongTrendLowVolatility.backtest(
            YahooDataBacktesting,
            backtesting_start,
            backtesting_end,
            budget=budget,
            parameters={"Ticker": Asset(symbol="NVDA", asset_type=Asset.AssetType.STOCK)}
        )


if __name__ == "__main__":
    run_backtest()
    #run_live()