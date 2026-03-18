import ccxt
import pandas as pd
import numpy as np


TIMEFRAME = '15h'
DI_CROSS_THRESHOLD = 5
DI_TREND_THRESHOLD = 10
EXCHANGE_FEE = 0.2
BUDGET = 50
MIN_NET_PROFIT = 0.5

def get_grid_parameters(symbol: str,
                        pct_atr: float,
                        current_price: float,
                        min_net_profit: float = MIN_NET_PROFIT,
                        exchange_fee: float = EXCHANGE_FEE,
                        budget: int | float = BUDGET) -> dict:
    """
    Рассчитывает параметры сетки на основе волатильности и бюджета.
    """
    # диапазон = ATR% * 3 (эмпирический коэффициент)
    range_width_pct = pct_atr * 3
    lower_p = current_price * (1 - range_width_pct / 200)
    upper_p = current_price * (1 + range_width_pct / 200)

    target_gross_profit = min_net_profit + exchange_fee

    # количество сеток = общая ширина / целевая прибыль на одну сетку
    calculated_grids = int(range_width_pct / target_gross_profit)

    # ограничение по бюджету (минимум 2 USDT на сетку для стабильности на Bybit)
    max_grids_by_budget = int(budget / 2)
    final_grids = min(calculated_grids, max_grids_by_budget)

    if final_grids == 0:
        return {
            'Symbol': symbol,
            'Price': -1,
            'Range': f"{-1} - {-1}",
            'Interval': -1,
            'Profit': f"{-1}%",
            'Final grids': final_grids
        }

    grid_interval = (upper_p - lower_p) / final_grids
    actual_net_profit = (range_width_pct / final_grids) - exchange_fee

    return {
        'Symbol': symbol,
        'Price': current_price,
        'Range': f"{round(lower_p, 4)} - {round(upper_p, 4)}",
        'Interval': round(grid_interval, 5),
        'Profit': f"{round(actual_net_profit, 2)}%",
        'Final grids': final_grids
    }

class Bot:
    exchange = ccxt.bybit()

    def calculate_indicators(self, df: pd.DataFrame, period=14):
        """
        Полный расчёт ADX, +DI, -DI, %ATR, ширины полос Боллинджера,
        а также дополнительных фильтров (диапазон, тренд по DI).
        """
        # True Range
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)

        # Направленное движение
        df['up_move'] = df['high'] - df['high'].shift(1)
        df['down_move'] = df['low'].shift(1) - df['low']

        df['+dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
        df['-dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)

        # Сглаживание методом Уайлдера (EWM с alpha=1/period)
        alpha = 1 / period
        df['tr_s'] = df['tr'].ewm(alpha=alpha, adjust=False).mean()
        df['+dm_s'] = df['+dm'].ewm(alpha=alpha, adjust=False).mean()
        df['-dm_s'] = df['-dm'].ewm(alpha=alpha, adjust=False).mean()

        # ATR (теперь тоже сглаженный по Уайлдеру)
        df['atr'] = df['tr_s'].copy()

        # +DI и -DI с защитой от деления на ноль
        epsilon = 1e-10
        df['+di'] = 100 * (df['+dm_s'] / (df['tr_s'] + epsilon))
        df['-di'] = 100 * (df['-dm_s'] / (df['tr_s'] + epsilon))

        # DX
        di_sum = df['+di'] + df['-di']
        di_diff = abs(df['+di'] - df['-di'])
        df['dx'] = 100 * (di_diff / (di_sum + epsilon))

        # ADX
        df['adx'] = df['dx'].ewm(alpha=alpha, adjust=False).mean()

        # %ATR
        df['pct_atr'] = (df['atr'] / df['close']) * 100

        # Полосы Боллинджера (20,2)
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        df['bb_std'] = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_middle'] - 2 * df['bb_std']
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle'] * 100

        # Флаги пересечения / тренда DI
        df['di_cross'] = ((df['+di'] - df['-di']).abs() < DI_CROSS_THRESHOLD)
        df['di_trend'] = ((df['+di'] - df['-di']).abs() > DI_TREND_THRESHOLD)

        # Диапазон за последние 50 свечей
        lookback = 50
        df['recent_high'] = df['high'].rolling(window=lookback).max()
        df['recent_low'] = df['low'].rolling(window=lookback).min()
        df['range_percent'] = ((df['recent_high'] - df['recent_low']) / df['recent_low']) * 100

        # Очистка от промежуточных колонок (опционально)
        cols_to_drop = ['h-l', 'h-pc', 'l-pc', 'up_move', 'down_move', '+dm', '-dm']
        df = df.drop(columns=[col for col in cols_to_drop if col in df.columns])

        return df

    def get_suitable_symbols(self):
        candidates = []

        markets = self.exchange.fetch_markets()
        symbols = [m['symbol'] for m in markets if m['spot'] and m['quote'] == 'USDT']

        for symbol in symbols:
            try:

                # Суточный объём
                ticker = self.exchange.fetch_ticker(symbol)
                volume_24h = round(ticker['quoteVolume'])

                # Загружаем свечи
                ohlcv = self.exchange.fetch_ohlcv(symbol=symbol,
                                                   timeframe=TIMEFRAME,
                                                   limit=300)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high',
                                                   'low', 'close', 'volume'])
                df = self.calculate_indicators(df)

                # Последняя свеча
                last_row = df.iloc[-1]

                # Первый этап: грубые фильтры
                # TODO: проверка на константах
                if (volume_24h < 3_000_000 or 
                    last_row['adx'] > 30 or 
                    last_row['pct_atr'] < 0.8 or 
                    last_row['pct_atr'] > 8 or
                    last_row['range_percent'] > 30):
                    continue  # пропускаем
                
                adx_val = round(last_row['adx'], 2)
                pct_atr = round(last_row['pct_atr'], 2)
                current_price = last_row['close']

                # Параметры сетки
                grid_params = get_grid_parameters(symbol=symbol,
                                                   pct_atr=pct_atr,
                                                   current_price=current_price)

                candidates.append({
                    'symbol': symbol,
                    'adx': adx_val,
                    'pct_atr': pct_atr,
                    'volume': volume_24h,
                    'bb_width': last_row['bb_width'],
                    'range_percent': last_row['range_percent'],
                    'di_trend': last_row['di_trend'],
                    'grid_params': grid_params
                })

            except Exception as e:
                print(f"[ERROR] Ошибка: {e}. Пропускаем...")
                continue

            if not candidates:
                return []



if __name__ == '__main__':
    bot = Bot()
    bot.get_suitable_symbols()

