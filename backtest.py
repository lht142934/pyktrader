import datetime
import pandas as pd
import numpy as np
import misc
import platform

sim_margin_dict = { 'au': 0.06, 'ag': 0.08, 'cu': 0.07, 'al':0.05,
                'zn': 0.06, 'rb': 0.06, 'ru': 0.12, 'a': 0.05,
                'm':  0.05, 'RM': 0.05, 'y' : 0.05, 'p': 0.05,
                'c':  0.05, 'CF': 0.05, 'i' : 0.05, 'j': 0.05,
                'jm': 0.05, 'pp': 0.05, 'l' : 0.05, 'SR': 0.06,
                'TA': 0.06, 'TC': 0.05, 'ME': 0.06, 'IF': 0.1,
                'jd': 0.06, 'ni': 0.07, 'sn': 0.07, 'IC': 0.1, 
                'IH': 0.01, 'FG': 0.05, 'TF':0.015, 'OI': 0.05,
                'T': 0.015, 'MA': 0.06, 'cs': 0.05, 'bu': 0.07, 
                'ni': 0.07, 'sn': 0.05, 'v': 0.05 }

def get_bktest_folder():
    folder = ''
    system = platform.system()
    if system == 'Linux':
        folder = '/home/harvey/dev/pyctp2/results/'
    elif system == 'Windows':
        folder = 'C:\\dev\\pyktlib\\pyktrader\\results\\'
    return folder
    
def get_asset_tradehrs(asset):
    exch = 'SHFE'
    for ex in misc.product_code:
        if asset in misc.product_code[ex]:
            exch = ex
            break
    hrs = [(1500, 1615), (1630, 1730), (1930, 2100)]
    if exch in ['SSE', 'SZE']:
        hrs = [(1530, 1730), (1900, 2100)]
    elif exch == 'CFFEX':
        hrs = [(1515, 1730), (1900, 2115)]
    else:
        if asset in misc.night_session_markets:
            night_idx = misc.night_session_markets[asset]
            hrs = [misc.night_trading_hrs[night_idx]] + hrs
    return hrs
    
def cleanup_mindata(df, asset):
    cond = None
    tradehrs = get_asset_tradehrs(asset)
    for idx, hrs in enumerate(tradehrs):
        if idx == 0:
            cond = (df.min_id>= tradehrs[idx][0]) & (df.min_id < tradehrs[idx][1])
        else:
            cond = cond | (df.min_id>= tradehrs[idx][0]) & (df.min_id < tradehrs[idx][1])
    df = df.ix[cond]
    return df

def get_pnl_stats(df, start_capital, marginrate, freq):
    df['pnl'] = df['pos'].shift(1)*(df['close'] - df['close'].shift(1)).fillna(0.0)
    df['margin'] = pd.concat([df.pos*marginrate[0]*df.close, -df.pos*marginrate[1]*df.close], join='outer', axis=1).max(1)
    if freq == 'm':
        daily_pnl = pd.Series(df['pnl']).resample('1d',how='sum').dropna()
        daily_margin = pd.Series(df['margin']).resample('1d',how='last').dropna()
        daily_cost = pd.Series(df['cost']).resample('1d',how='sum').dropna()
    else:
        daily_pnl = pd.Series(df['pnl'])
        daily_margin = pd.Series(df['margin'])
        daily_cost = pd.Series(df['cost'])
    daily_pnl.name = 'daily_pnl'
    daily_margin.name = 'daily_margin'
    daily_cost.name = 'daily_cost'
    cum_pnl = pd.Series(daily_pnl.cumsum() + daily_cost.cumsum() + start_capital, name = 'cum_pnl')
    available = cum_pnl - daily_margin
    res = {}
    res['avg_pnl'] = daily_pnl.mean()
    res['std_pnl'] = daily_pnl.std()
    res['tot_pnl'] = daily_pnl.sum()
    res['tot_cost'] = daily_cost.sum()
    res['num_days'] = len(daily_pnl)
    res['sharp_ratio'] = res['avg_pnl']/res['std_pnl']*np.sqrt(252.0)
    max_dd, max_dur = max_drawdown(cum_pnl)
    res['max_margin'] = daily_margin.max()
    res['min_avail'] = available.min() 
    res['max_drawdown'] =  max_dd
    res['max_dd_period'] =  max_dur
    if abs(max_dd) > 0:
        res['profit_dd_ratio'] = res['tot_pnl']/abs(max_dd)
    else:
        res['profit_dd_ratio'] = 0
    ts = pd.concat([cum_pnl, daily_margin, daily_cost], join='outer', axis=1)
    return res, ts

def get_trade_stats(trade_list):
    res = {}
    res['n_trades'] = len(trade_list)
    res['all_profit'] = sum([trade.profit for trade in trade_list])
    res['win_profit'] = sum([trade.profit for trade in trade_list if trade.profit>0])
    res['loss_profit'] = sum([trade.profit for trade in trade_list if trade.profit<0])
    sorted_profit = sorted([trade.profit for trade in trade_list])
    res['largest_profit'] = sorted_profit[-1]
    res['second largest'] = sorted_profit[-2]
    res['third_profit'] = sorted_profit[-3]
    res['largest_loss'] = sorted_profit[0]
    res['second_loss'] = sorted_profit[1]
    res['third_loss'] = sorted_profit[2]
    res['num_win'] = len([trade.profit for trade in trade_list if trade.profit>0])
    res['num_loss'] = len([trade.profit for trade in trade_list if trade.profit<0])
    res['win_ratio'] = 0
    if res['n_trades'] > 0:
        res['win_ratio'] = float(res['num_win'])/float(res['n_trades'])
    res['profit_per_win'] = 0
    if res['num_win'] > 0:
        res['profit_per_win'] = res['win_profit']/float(res['num_win'])
    res['profit_per_loss'] = 0
    if res['num_loss'] > 0:    
        res['profit_per_loss'] = res['loss_profit']/float(res['num_loss'])
    
    return res

def create_drawdowns(ts):
    """
    Calculate the largest peak-to-trough drawdown of the PnL curve
    as well as the duration of the drawdown. Requires that the 
    pnl_returns is a pandas Series.
    Parameters:
    pnl - A pandas Series representing period percentage returns.
    Returns:
    drawdown, duration - Highest peak-to-trough drawdown and duration.
    """

    # Calculate the cumulative returns curve 
    # and set up the High Water Mark
    # Then create the drawdown and duration series
    ts_idx = ts.index
    drawdown = pd.Series(index = ts_idx)
    duration = pd.Series(index = ts_idx)
    hwm = pd.Series([0]*len(ts), index = ts_idx)
    last_t = ts_idx[0]
    # Loop over the index range
    for idx, t in enumerate(ts_idx):
        if idx > 0:
            cur_hwm = max(hwm[last_t], ts_idx[idx])
            hwm[t] = cur_hwm
            drawdown[t]= hwm[t] - ts[t]
            duration[t]= 0 if drawdown[t] == 0 else duration[last_t] + 1
        last_t = t
    return drawdown.max(), duration.max()

def max_drawdown(ts):
    i = np.argmax(np.maximum.accumulate(ts)-ts)
    j = np.argmax(ts[:i])
    max_dd = ts[i] - ts[j]
    max_duration = (i - j).days
    return max_dd, max_duration
