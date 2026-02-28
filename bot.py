import ccxt
import pandas as pd
import numpy as np

from bcolors import bcolors


MAX_ADX = 25
MIN_VOLATILITY = 0.3
MIN_VOLUME_24H = 5_000_000 
MIN_NET_PROFIT = 0.5    # Мы хотим минимум 0.5% чистой прибыли на сделку
EXCHANGE_FEE = 0.2      # Суммарная комиссия Bybit (0.1% * 2)
BUDGET = 50


class Bot:
    exchange = ccxt.bybit()

    def __init__(self, exchange_name: str):
        self.exchange_name = exchange_name
    
    def get_exchange(self):
        return self.exchange
    def set_exchange(self, new_exchange_name: str):
        self.exchange_name = new_exchange_name

    # расчет индикаторов ADX и %ATR
    def calculate_indicators(self, df: pd.DataFrame, period=14):
        
        # Расчет True Range (TR)
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)

        # Направленное движение (DM)
        df['up_move'] = df['high'] - df['high'].shift(1)
        df['down_move'] = df['low'].shift(1) - df['low']
        
        df['+dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
        df['-dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)

        # Сглаживание методом Уайлдера (через EWM)
        alpha = 1 / period
        df['tr_s'] = df['tr'].ewm(alpha=alpha, adjust=False).mean()
        df['+dm_s'] = df['+dm'].ewm(alpha=alpha, adjust=False).mean()
        df['-dm_s'] = df['-dm'].ewm(alpha=alpha, adjust=False).mean()

        # Расчет +DI, -DI и DX
        df['+di'] = 100 * (df['+dm_s'] / df['tr_s'])
        df['-di'] = 100 * (df['-dm_s'] / df['tr_s'])
        df['dx'] = 100 * (abs(df['+di'] - df['-di']) / (df['+di'] + df['-di']))

        # Финальный ADX
        df['adx'] = df['dx'].ewm(alpha=alpha, adjust=False).mean()
        
        # %ATR (Средняя волатильность в процентах от цены)
        df['atr'] = df['tr'].rolling(window=period).mean()
        df['pct_atr'] = (df['atr'] / df['close']) * 100

        return df


    # поиск подходящих активов
    def get_suitable_symbols(self):
        suitable_symbols = [] # список подходящих активов
        
        # запрос данных с биржи
        markets = self.exchange.fetch_markets()
        # спотовые пары к USDT
        symbols = [m['symbol'] for m in markets if m['spot'] and m['quote'] == 'USDT']
        
        # загрузка свечей опр. пары
        for symbol in symbols:
            ohlcv = self.exchange.fetch_ohlcv(symbol=symbol,
                                              timeframe='5m',
                                              limit=300)
            df = pd.DataFrame(data=ohlcv,
                              columns=['timestamp', 'open', 'high',
                                        'low', 'close', 'volume'])
            
            # проверка обьема за 24ч
            ticker = self.exchange.fetch_ticker(symbol)
            volume_24h = ticker['quoteVolume']
            
            df = self.calculate_indicators(df)
            last_row = df.iloc[-1]
            adx_val = last_row['adx']
            pct_atr = last_row['pct_atr']
            current_price = last_row['close']

            if  (adx_val < MAX_ADX and pct_atr >= MIN_VOLATILITY and volume_24h >= MIN_VOLUME_24H):
                print(bcolors.OKGREEN + "[SUCCESS] " + bcolors.ENDC + f" АКТИВ НАЙДЕН: {symbol}  %ATR: {pct_atr} НЕОБХОДИМО: {MIN_VOLATILITY}")

                # расчет диапазона
                range_width_pct = pct_atr * 3
                lower_p = current_price * (1 - range_width_pct / 200)
                upper_p = current_price * (1 + range_width_pct / 200)

                target_gross_profit = MIN_NET_PROFIT + EXCHANGE_FEE

                # Кол-во сеток = Общая ширина / Целевая прибыль на одну
                calculated_grids = int(range_width_pct / target_gross_profit)

                # Ограничение по бюджету (минимум 2 USDT на сетку для стабильности на Bybit)
                max_grids_by_budget = int(BUDGET / 2)
                final_grids = min(calculated_grids, max_grids_by_budget)

                if final_grids < 10:
                    continue

                grid_interval = (upper_p - lower_p) / final_grids
                actual_net_profit = (range_width_pct / final_grids) - EXCHANGE_FEE

                suitable_symbols.append({
                    'Symbol': symbol,
                    'Price': current_price,
                    'Range': f"{round(lower_p, 4)} - {round(upper_p, 4)}",
                    'Interval': round(grid_interval, 5),
                    'Profit': f"{round(actual_net_profit, 2)}%",
                })
                
            else:
                print(bcolors.FAIL +"[FAIL] " + bcolors.ENDC + f"АКТИВ {symbol} НЕ ПОДХОДИТ")
            
        return suitable_symbols
    

if __name__ == "__main__":
    bot = Bot('bybit')

    print(bot.get_exchange())
    
    suitable_symbols = bot.get_suitable_symbols()

    print(len(suitable_symbols))
    print("===== ПОДХОДЯЩИЕ АКТИВЫ =====")
    for symbol in suitable_symbols:
        print(f"Актив: {symbol['Symbol']}")
        print(f"Цена: {symbol['Price']}")
        print(f"Ценовой диапазон: {symbol['Range']}")
        print(f"Интервал: {symbol['Interval']}")
        print(f"Профит: {symbol['Profit']}")
        print()


