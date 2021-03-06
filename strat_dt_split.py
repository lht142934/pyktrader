#-*- coding:utf-8 -*-
#from base import *
from misc import *
import data_handler as dh
from strategy import *
 
class DTSplitTrader(Strategy):
    def __init__(self, name, underliers, volumes,
                 agent = None,
                 trade_unit = [],
                 ratios = [],
                 lookbacks=[],
                 daily_close = False,
                 email_notify = None,
                 ma_win = 10,
                 open_period = [300, 1500, 2115],
                 min_rng = [0.00]):
        Strategy.__init__(self, name, underliers, volumes, trade_unit, agent, email_notify)
        self.lookbacks = lookbacks
        numAssets = len(underliers)
        self.ratios = [[0.5, 0.5]] * numAssets
        if len(ratios) > 1:
            self.ratios = ratios
        elif len(ratios) == 1: 
            self.ratios = ratios * numAssets
        if len(lookbacks) > 0:
            self.lookbacks = lookbacks
        else: 
            self.lookbacks = [0] * numAssets
        self.cur_rng = [0.0] * numAssets
        self.cur_ma  = [0.0] * numAssets
        self.tday_open = [0.0] * numAssets
        self.open_period = open_period
        self.open_idx = [0] * numAssets
        self.tick_base = [0.0] * numAssets
        self.order_type = OPT_LIMIT_ORDER
        self.daily_close_buffer = 3
        self.close_tday = [False] * numAssets
        if len(daily_close) > 1:
            self.close_tday = daily_close
        elif len(daily_close) == 1: 
            self.close_tday = daily_close * numAssets 
        self.ma_win = ma_win
        self.num_tick = 1
        self.min_rng = [0.0] * numAssets
        if len(min_rng) > 1:
            self.min_rng = min_rng
        elif len(min_rng) == 1:
            self.min_rng = min_rng * numAssets

    def initialize(self):
        self.load_state()
        for idx, underlier in enumerate(self.underliers):
            inst = underlier[0]
            self.tick_base[idx] = self.agent.instruments[inst].tick_base
            min_id = self.agent.instruments[inst].last_tick_id/1000
            min_id = int(min_id/100)*60 + min_id % 100 - self.daily_close_buffer
            self.last_min_id[idx] = int(min_id/60)*100 + min_id % 60
            ddf = self.agent.day_data[inst]
            mdf = self.agent.min_data[inst][1]
            last_date = ddf.index[-1]
            self.open_idx[idx] = 0
            if last_date < mdf.index[-1].date():
                last_min = mdf['min_id'][-1]
                pid = 0
                for i in range(1, len(self.open_period)):
                    if self.open_period[i] >= last_min:
                        break
                    else:
                        pid = i
                df = mdf[(mdf.index.date <= last_date)|(mdf['min_id'] < self.open_period[pid])]
                post_df = mdf[(mdf.index.date > last_date) & (mdf['min_id'] >= self.open_period[pid])]
                self.open_idx[idx] = pid
                self.tday_open[idx] = post_df['open'][0]
            else:
                df = mdf
                self.tday_open[idx] = mdf['close'][-1]
            self.recalc_rng(idx, df)
        self.save_state()
        return

    def recalc_rng(self, idx, mdf):
        inst = self.underliers[idx][0]
        mdf['min_idx'] = pd.Series(0, index = mdf.index)
        for i in range(1, len(self.open_period)-1):
            mdf.loc[(mdf['min_id']>= self.open_period[i]) & (mdf['min_id']<self.open_period[i+1]), 'min_idx'] = i
            mdf['date_idx'] = mdf.index.date
        ddf = mdf.groupby([mdf['date_idx'], mdf['min_idx']]).apply(dh.ohlcsum).reset_index().set_index('datetime')
        win = self.lookbacks[idx]
        if win > 0:
            self.cur_rng[idx] = max(max(ddf.ix[-win:,'high'])- min(ddf.ix[-win:,'close']), max(ddf.ix[-win:,'close']) - min(ddf.ix[-win:,'low']))
        elif win == 0:
            self.cur_rng[idx] = max(max(ddf.ix[-2:,'high'])- min(ddf.ix[-2:,'close']), max(ddf.ix[-2:,'close']) - min(ddf.ix[-2:,'low']))
            self.cur_rng[idx] = max(self.cur_rng[idx] * 0.5, ddf.ix[-1,'high']-ddf.ix[-1,'close'],ddf.ix[-1,'close']-ddf.ix[-1,'low'])
        else:
            self.cur_rng[idx] = max(ddf.ix[-1,'high']- ddf.ix[-1,'low'], abs(ddf.ix[-1,'close'] - ddf.ix[-2,'close']))

    def save_local_variables(self, file_writer):
        for idx, underlier in enumerate(self.underliers):
            inst = underlier[0]
            row = ['CurrRange', str(inst), self.cur_rng[idx]]
            file_writer.writerow(row)
        return
    
    def load_local_variables(self, row):
        if row[0] == 'CurrRange':
            inst = str(row[1])
            idx = self.under2idx[inst]
            if idx >= 0:
                self.cur_rng[idx] = float(row[2])
        return

    def register_bar_freq(self):
        for idx, under in enumerate(self.underliers):
            inst = under[0]
            self.agent.inst2strat[inst][self.name].append(1)
            #self.logger.debug("stat = %s register bar event for inst=%s freq = 1" % (self.name, inst, ))

    def on_bar(self, idx, freq):
        inst = self.underliers[idx][0]
        min_id = self.agent.cur_min[inst]['min_id']
        curr_min = self.agent.instruments[inst].last_update/1000
        pid = self.open_idx[idx]
        if pid < len(self.open_period)-1:
            if (self.open_period[pid+1] > min_id) and (self.open_period[pid+1] <= curr_min):
                self.recalc_rng(idx, self.agent.min_data[inst][1])
                self.tday_open[idx] = self.agent.instruments[inst].price
                self.logger.info("Note: the new split open is set to %s for inst=%s for stat = %s" % (self.tday_open[idx], inst, self.name, ))

    def on_tick(self, idx, ctick):
        if len(self.submitted_trades[idx]) > 0:
            return
        inst = self.underliers[idx][0]
        if self.open_idx[idx] == 0:
            self.tday_open[idx] = self.agent.cur_day[inst]['open']
        if (self.tday_open[idx] <= 0.0) or (self.cur_rng[idx] <= 0) or (self.curr_prices[idx] <= 0.001):
            self.logger.warning("warning: open price =0.0 or range = 0.0 or curr_price=0 for inst=%s for stat = %s" % (inst, self.name))
            return
        min_id = self.agent.tick_id/1000.0
        num_pos = len(self.positions[idx])
        buysell = 0
        if num_pos > 1:
            self.logger.warning('something wrong with position management - submitted trade is empty but trade position is more than 1')
            return
        elif num_pos == 1:
            buysell = self.positions[idx][0].direction
        tick_base = self.tick_base[idx]
        t_open = self.tday_open[idx]
        rng = max(self.cur_rng[idx] * self.ratios[idx][0], t_open * self.min_rng[idx])
        buy_trig  = t_open + rng
        sell_trig = t_open - rng
        if self.cur_ma[idx] > t_open:
            buy_trig += self.ratios[idx][1] * rng
        elif self.cur_ma[idx] < t_open:
            sell_trig -= self.ratios[idx][1] * rng

        if (min_id >= self.last_min_id[idx]):
            if (buysell!=0) and (self.close_tday[idx]):
                msg = 'DT to close position before EOD for inst = %s, direction=%s, volume=%s, current tick_id = %s' \
                        % (inst, buysell, self.trade_unit[idx], min_id)
                self.close_tradepos(idx, self.positions[idx][0], self.curr_prices[idx] - buysell * self.num_tick * tick_base)
                self.status_notifier(msg)
                self.save_state()
            return

        if ((self.curr_prices[idx] >= buy_trig) and (buysell <=0)) or ((self.curr_prices[idx] <= sell_trig) and (buysell >=0)):
            if buysell!=0:
                msg = 'DT to close position for inst = %s, open= %s, buy_trig=%s, sell_trig=%s, curr_price= %s, direction=%s, volume=%s' \
                                    % (inst, t_open, buy_trig, sell_trig, self.curr_prices[idx], buysell, self.trade_unit[idx])
                self.close_tradepos(idx, self.positions[idx][0], self.curr_prices[idx] - buysell * self.num_tick * tick_base)
                self.status_notifier(msg)
            if self.trade_unit[idx] <= 0:
                return
            if  (self.curr_prices[idx] >= buy_trig):
                buysell = 1
            else:
                buysell = -1
            msg = 'DT to open position for inst = %s, open= %s, buy_trig=%s, sell_trig=%s, curr_price= %s, direction=%s, volume=%s' \
                                    % (inst, t_open, buy_trig, sell_trig, self.curr_prices[idx], buysell, self.trade_unit[idx])
            self.open_tradepos(idx, buysell, self.curr_prices[idx] + buysell * self.num_tick * tick_base)
            self.status_notifier(msg)
            self.save_state()
        return 
        
    def update_trade_unit(self):
        pass
