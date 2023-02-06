# """
#     Title: Buy and Hold (NSE)
#     Description: This is a long only strategy which rebalances the 
#         portfolio weights every month at month start.
#     Style tags: Systematic
#     Asset class: Equities, Futures, ETFs, Currencies and Commodities
#     Dataset: NSE
# """
# from blueshift.api import(    symbol,
#                             order_target_percent,
#                             schedule_function,
#                             date_rules,
#                             time_rules,
#                        )

# def initialize(context):
#     """
#         A function to define things to do at the start of the strategy
#     """
    
#     # universe selection
#     context.long_portfolio = [
#                                symbol('DIVISLAB'),
#                                symbol('SUNPHARMA'),
#                                symbol('MARUTI'),
#                                symbol('AMARAJABAT'),
#                                symbol('BPCL'),                               
#                                symbol('BAJFINANCE'),
#                                symbol('HDFCBANK'),
#                                symbol('ASIANPAINT'),
#                                symbol('TCS')
#                              ]
    
#     # Call rebalance function on the first trading day of each month after 2.5 hours from market open
#     schedule_function(rebalance,
#                     date_rules.month_start(days_offset=0),
#                     time_rules.market_close(hours=2, minutes=30))


# def rebalance(context,data):
#     """
#         A function to rebalance the portfolio, passed on to the call
#         of schedule_function above.
#     """

#     # Position 50% of portfolio to be long in each security
#     for security in context.long_portfolio:
#         order_target_percent(security, 1.0/10)   

import numpy as np
import pandas as pd
from scipy.stats import linregress
from blueshift.finance import commission, slippage
from blueshift.api import(  symbol,
                            order_target_percent,
                            set_commission,
                            set_slippage,
                            schedule_function,
                            date_rules,
                            time_rules,
                       )

def initialize(context):
    """
        A function to define things to do at the start of the strategy
    """
    # universe selection
    context.securities = [symbol('TCS')]
    # define strategy parameters
    context.params = {'indicator_lookback':1100,
                      'indicator_freq':'1m',
                      'buy_signal_threshold':0.5,
                      'ROC_period_short':30,
                      'ROC_period_long':120,
                      'BBands_period':300,
                      'trade_freq':15,
                      'leverage':1,
                      'double_bottom_min_spread':3,
                      'double_bottom_max_spread':50,
                      'double_bottom_valley_tolerance':0.008,
                      'double_bottom_slope_tolerance':0.4
                      }

    # variable to control trading frequency
    context.bar_count = 0
    context.valley_reject = 0
    context.slope_reject = 0
    # Constants
    context.UP = 1
    context.DOWN = -1
    context.NO_DIR = 0
    context.up_thresh = 0.008
    context.down_thresh = -0.008

    context.apex = []
    context.window = 20

    context.backcandles = 100

    # variables to track signals and target portfolio
    context.signals = dict((security,0) for security in context.securities)
    context.target_position = dict((security,0) for security in context.securities)
    context.take_profit = dict((security,0) for security in context.securities)
    context.stop_loss = dict((security,0) for security in context.securities)
    context.holding = dict((security,False) for security in context.securities)
    context.zigzag_pivot_points = dict((security,[]) for security in context.securities)
    context.zigzag_pivot_values = dict((security,[]) for security in context.securities)
    context.zigzag_dir = dict((security,context.NO_DIR) for security in context.securities)

    context.curr_bar = dict((security,0) for security in context.securities)

    context.candles_5min = dict((security,[]) for security in context.securities)
    # set trading cost and slippage to zero
    set_commission(commission.PerShare(cost=0.0, min_trade_cost=0.0))
    set_slippage(slippage.FixedSlippage(0.00))
    
    freq = int(context.params['trade_freq'])
    schedule_function(run_strategy, date_rules.every_day(),
                      time_rules.every_nth_minute(freq))
    
    schedule_function(stop_trading, date_rules.every_day(),
                      time_rules.market_close(minutes=30))
    
    
    print("end of init")
    
def before_trading_start(context, data): 
    context.trade = True
    
def stop_trading(context, data):
    context.trade = False

def run_strategy(context, data):
    """
        A function to define core strategy steps
    """
    if not context.trade:
        return
    
    generate_signals(context, data)
    generate_target_position(context, data)
    rebalance(context, data)

def rebalance(context,data):
    """
        A function to rebalance - all execution logic goes here
    """
    
    for security in context.securities:
        order_id = order_target_percent(security, context.target_position[security])
        
        if order_id is None:
            continue
        
        if context.target_position[security] == 0:
            context.holding[security] = 0
            context.stop_loss[security] = 0
            context.take_profit[security] = 0
        else:
            context.holding[security] = 1

def generate_target_position(context, data):
    '''
        A function to define target portfolio
    '''
    num_secs = len(context.securities)
    weight = round(1.0/num_secs,2)*context.params['leverage']

    for security in context.securities:
        if context.signals[security] > context.params['buy_signal_threshold']:
            context.target_position[security] = weight
        else:
            context.target_position[security] = 0


def generate_signals(context, data):
    """
        A function to define define the signal generation
    """
   
    try:
        price_data = data.history(context.securities, ['open','high','low','close'],
            context.params['indicator_lookback'], context.params['indicator_freq'])
    except:
        return

    for security in context.securities:
        px = price_data.xs(security)
        if len(px) < context.params['trade_freq']:
            continue
        candle = get_candle(px, context.params['trade_freq'])
        context.candles_5min[security].append(candle)
        if len(context.candles_5min[security]) > context.params['indicator_lookback']:
            context.candles_5min[security] = context.candles_5min[security][-context.params['indicator_lookback'] : ]
        context.signals[security] = signal_function(context, security, context.candles_5min[security], context.params,
            context.signals[security])

def pivotid(df1, l, n1, n2): #n1 n2 before and after candle l
    if l - n1 < 0 or l + n2 >= len(df1):
        return 0
    
    pividlow = 1
    pividhigh = 1
    for i in range(l - n1, l + n2 + 1):
        if(df1[l]['low'] > df1[i]['low']):
            pividlow = 0
        if(df1[l]['high'] < df1[i]['high']):
            pividhigh = 0
    if pividlow and pividhigh:
        return 3
    elif pividlow:
        return 1
    elif pividhigh:
        return 2
    else:
        return 0

def signal_function(context, security, candles, params, last_signal): 
    """
        The main trading logic goes here, called by generate_signals above
    """
    res_signal = 0
    if len(candles) == 0:
        return 0

    sz = len(candles)

    for apex in context.apex:
        if abs(apex - sz) < context.window and sz > 3:
            if candles[-3]['close'] > candles[-4]['close'] and candles[-2]['close'] > candles[-3]['close'] and candles[-1]['close'] > candles[-2]['close']:
                res_signal = 1

    maxim = np.array([])
    minim = np.array([])
    xxmin = np.array([])
    xxmax = np.array([])

    # last_candle = candle[-1]

    for i in range(sz - context.backcandles - 1, sz - 5):
        pidx = pivotid(candles, i, 3, 3)
        # print("hello")
        # print(i)
        # print(pidx)
        # if i == 0:
        #     candle = candles[i]
        #     print(candle['high'])
        if pidx == 1:
            minim = np.append(minim, candles[i]['low'])
            xxmin = np.append(xxmin, i) #could be i instead df.iloc[i].name
        if pidx == 2:
            maxim = np.append(maxim, candles[i]['high'])
            xxmax = np.append(xxmax, i) # df.iloc[i].name

    if (xxmax.size < 3 and xxmin.size < 3) or xxmax.size == 0 or xxmin.size == 0:
        return res_signal
    
    slmin, intercmin, rmin, pmin, semin = linregress(xxmin, minim)
    slmax, intercmax, rmax, pmax, semax = linregress(xxmax, maxim)
    x_intersection = (intercmin - intercmax) / (slmax - slmin)
    print(sz, slmin, slmax, intercmin, intercmax, x_intersection, rmax, rmin)
    # cmin + slmin * x = cmax + x * slmax
    # x = (cmin - cmax) / (slmax - slmin)

    if x_intersection > sz:
        context.apex.append(x_intersection)

    if abs(rmax) >= 0.7 and abs(rmin) >= 0.7 and abs(slmin) <= 0.1 and slmax <= -0.0001:
        
        print(x_intersection)
        context.apex.append(x_intersection)

    return res_signal

def get_candle(px, n):
	
    candle = {
		"open":0,
		"high":-1e9,
		"close":0,
		"low":1e9
	    }
    Open = px.open.values[-n:]
    High = px.high.values[-n:]
    Close = px.close.values[-n:]
    Low = px.low.values[-n:]

    candle['open']=Open[0]
    candle['close']=Close[n-1]
    for x in High:
        candle['high']=max(candle['high'],x)

    for x in Low:
        candle['low']=min(candle['low'],x)
    return candle

