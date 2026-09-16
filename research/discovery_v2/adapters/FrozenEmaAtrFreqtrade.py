from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class FrozenEmaAtrFreqtrade(IStrategy):
    """Signal-equivalent implementation of mexc_8h_ema24_96_atr025_v1.

    This file exists only for engine calibration. It is not a promoted strategy and
    does not authorize live trading.
    """

    INTERFACE_VERSION = 3
    timeframe = "8h"
    can_short = True
    startup_candle_count = 96
    process_only_new_candles = True
    minimal_roi = {"0": 100.0}
    stoploss = -0.99
    use_exit_signal = True

    fast_ema = 24
    slow_ema = 96
    atr_period = 14
    threshold = 0.25

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"].astype(float)
        fast = close.ewm(span=self.fast_ema, adjust=False, min_periods=self.fast_ema).mean()
        slow = close.ewm(span=self.slow_ema, adjust=False, min_periods=self.slow_ema).mean()
        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                (dataframe["high"].astype(float) - dataframe["low"].astype(float)).abs(),
                (dataframe["high"].astype(float) - previous_close).abs(),
                (dataframe["low"].astype(float) - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = true_range.rolling(self.atr_period, min_periods=self.atr_period).mean()
        normalized = (fast - slow) / atr.replace(0.0, np.nan)
        dataframe["cal_fast_ema"] = fast
        dataframe["cal_slow_ema"] = slow
        dataframe["cal_atr"] = atr
        dataframe["cal_normalized"] = normalized
        dataframe["cal_target"] = np.where(
            normalized > self.threshold,
            1.0,
            np.where(normalized < -self.threshold, -1.0, 0.0),
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["cal_target"] == 1.0, "enter_long"] = 1
        dataframe.loc[dataframe["cal_target"] == -1.0, "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["cal_target"] != 1.0, "exit_long"] = 1
        dataframe.loc[dataframe["cal_target"] != -1.0, "exit_short"] = 1
        return dataframe
