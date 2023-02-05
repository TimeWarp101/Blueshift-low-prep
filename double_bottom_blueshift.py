"""
    Title: Double bottom
"""
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
    context.securities = [symbol('INFY'), ]
    # define strategy parameters
    context.params = {'indicator_lookback':1100,
                      'indicator_freq':'1m',
                      'buy_signal_threshold':0.5,
                      'ROC_period_short':30,
                      'ROC_period_long':120,
                      'BBands_period':300,
                      'trade_freq':5,
                      'leverage':1,
                      'double_bottom_min_spread':15,
                      'double_bottom_max_spread':500,
                      'double_bottom_valley_tolerance':0.01
                      }

    # variable to control trading frequency
    context.bar_count = 0

    # Constants
    context.UP = 1
    context.DOWN = -1
    context.NO_DIR = 0
    context.up_thresh = 0.01
    context.down_thresh = -0.01

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
        candle = convert_into_5min(px)
        context.candles_5min[security].append(candle)
        if len(context.candles_5min[security]) > context.params['indicator_lookback']:
            context.candles_5min[security] = context.candles_5min[security][-context.params['indicator_lookback'] : ]
        context.signals[security] = signal_function(context, security, context.candles_5min[security], context.params,
            context.signals[security])



def signal_function(context, security, candles, params, last_signal):
    """
        The main trading logic goes here, called by generate_signals above
    """
    res_signal = last_signal
    if len(candles) == 0:
        return 0
    double_btm_found = False
    context.curr_bar[security] = context.curr_bar[security] + 1
    curr_bar = context.curr_bar[security]
    
    prices = [(candle['low'] + candle['close']) / 2 for candle in candles]
    last_price = prices[-1]
    pivot_values = context.zigzag_pivot_values[security]
    pivot_points = context.zigzag_pivot_points[security]
    direction = context.zigzag_dir[security]
    try:
        if len(pivot_values) == 0:
            pivot_points.append(curr_bar)
            pivot_values.append(prices[-1])
        elif prices[-1]/pivot_values[-1] - 1 > context.up_thresh:
            if direction == context.UP:
                pivot_points[-1] = curr_bar
                pivot_values[-1] = last_price
            else:
                pivot_points.append(curr_bar)
                pivot_values.append(last_price)

            if is_double_bottom(context, pivot_points, pivot_values):
                res_signal = 1
                double_btm_found = True
            direction = context.UP
        elif prices[-1]/pivot_values[-1] - 1 < context.down_thresh:
            if direction == context.DOWN:
                pivot_points[-1] = curr_bar
                pivot_values[-1] = last_price
            else:
                pivot_points.append(curr_bar)
                pivot_values.append(last_price)

            direction = context.DOWN
        
        if context.holding[security]:
            curr_value = prices[-1]
            if curr_value > context.take_profit[security] or curr_value < context.stop_loss[security]:
                res_signal = 0
            else:
                res_signal = 1
    
        context.zigzag_dir[security] = direction
        if double_btm_found and last_signal == 0:
            context.stop_loss[security] = 0.998 * pivot_values[-2]
            context.take_profit[security] = 2 * pivot_values[-1] - pivot_values[-2]
            

        if len(pivot_values) > 10:
            pivot_values = pivot_values[-10:]
            pivot_points = pivot_points[-10:]
    except Exception as e:
        print(e)
        return 0
    
    if last_signal == 0 and res_signal == 1 and double_btm_found:
        start_index = max(-1000, pivot_points[-5] - curr_bar - 1)
        print_str = ""
        for i in range(start_index, 0):
            print_str = print_str + " " + str(prices[i])
        print(print_str)
        
    return res_signal


def is_double_bottom(context, pivot_points, pivot_values):
    min_spread = context.params['double_bottom_min_spread']
    max_spread = context.params['double_bottom_max_spread']
    valley_tolerance = context.params['double_bottom_valley_tolerance']
    if len(pivot_values) < 5:
        return False
    if pivot_values[-5] <= pivot_values[-3]:
        return False
    if pivot_points[-1] - pivot_points[-3] > max_spread or pivot_points[-1] - pivot_points[-3] < min_spread or pivot_points[-2] - pivot_points[-4] > max_spread or pivot_points[-2] - pivot_points[-4] < min_spread:
        return False
    if abs(1 - pivot_values[-1]/pivot_values[-3]) <= valley_tolerance and abs(1 - pivot_values[-2]/pivot_values[-4]) <= valley_tolerance:
        return True
    
    return False
                    
def convert_into_5min(px):
	
    print(px)
    candle = {
		"open":0,
		"high":-1e9,
		"close":0,
		"low":1e9
	    }
    Open = px.open.values[-5:]
    High = px.high.values[-5:]
    Close = px.close.values[-5:]
    Low = px.low.values[-5:]

    candle["open"]=Open[0]
    candle["close"]=Close[4]
    for x in High:
        candle["high"]=max(candle["high"],x)

    for x in Low:
        candle["low"]=min(candle["low"],x)
    return candle
