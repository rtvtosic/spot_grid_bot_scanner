import ccxt
import time
import pandas as pd
import numpy as np

from bcolors import bcolors


MAX_ADX = 25
MIN_VOLATILITY = 0.3
MIN_VOLUME_24H = 5_000_000 
MIN_NET_PROFIT = 0.5    # Мы хотим минимум 0.5% чистой прибыли на сделку
EXCHANGE_FEE = 0.2      # Суммарная комиссия Bybit (0.1% * 2)
BUDGET = 50
TIMEFRAME = '15m'


def get_grid_parameters(symbol: str, 
                        pct_atr: float, 
                        current_price: float, 
                        min_net_profit: float = MIN_NET_PROFIT, 
                        exchange_fee: float = EXCHANGE_FEE, 
                        budget: int | float = BUDGET) -> dict:
    # расчет диапазона
    range_width_pct = pct_atr * 3
    lower_p = current_price * (1 - range_width_pct / 200)
    upper_p = current_price * (1 + range_width_pct / 200)

    target_gross_profit = min_net_profit + exchange_fee

    # Кол-во сеток = Общая ширина / Целевая прибыль на одну
    calculated_grids = int(range_width_pct / target_gross_profit)

    # Ограничение по бюджету (минимум 2 USDT на сетку для стабильности на Bybit)
    max_grids_by_budget = int(budget / 2)
    final_grids = min(calculated_grids, max_grids_by_budget)

    # если 0 сеток, то возвращаем пустой словарь
    if not final_grids: 
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

    def __init__(self, exchange_name: str):
        self.exchange_name = exchange_name
    
    def get_exchange(self):
        return self.exchange
    def set_exchange(self, new_exchange_name: str):
        self.exchange_name = new_exchange_name

    # # расчет индикаторов ADX и %ATR
    # def calculate_indicators(self, df: pd.DataFrame, period=14):
        
    #     # Расчет True Range (TR)
    #     df['h-l'] = df['high'] - df['low']
    #     df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    #     df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    #     df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)

    #     # Направленное движение (DM)
    #     df['up_move'] = df['high'] - df['high'].shift(1)
    #     df['down_move'] = df['low'].shift(1) - df['low']
        
    #     df['+dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
    #     df['-dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)

    #     # Сглаживание методом Уайлдера (через EWM)
    #     alpha = 1 / period
    #     df['tr_s'] = df['tr'].ewm(alpha=alpha, adjust=False).mean()
    #     df['+dm_s'] = df['+dm'].ewm(alpha=alpha, adjust=False).mean()
    #     df['-dm_s'] = df['-dm'].ewm(alpha=alpha, adjust=False).mean()

    #     # Расчет +DI, -DI и DX
    #     df['+di'] = 100 * (df['+dm_s'] / df['tr_s'])
    #     df['-di'] = 100 * (df['-dm_s'] / df['tr_s'])
    #     df['dx'] = 100 * (abs(df['+di'] - df['-di']) / (df['+di'] + df['-di']))

    #     # Финальный ADX
    #     df['adx'] = df['dx'].ewm(alpha=alpha, adjust=False).mean()
        
    #     # %ATR (Средняя волатильность в процентах от цены)
    #     df['atr'] = df['tr'].rolling(window=period).mean()
    #     df['pct_atr'] = (df['atr'] / df['close']) * 100

    #     return df

    def calculate_indicators(self, df: pd.DataFrame, period=14):
        """
        Расчет ADX, +DI, -DI и %ATR для поиска боковиков
        """
        # Расчет True Range (TR) - оставляем как есть, тут верно
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)

        # Направленное движение (DM) - тоже верно
        df['up_move'] = df['high'] - df['high'].shift(1)
        df['down_move'] = df['low'].shift(1) - df['low']
        
        df['+dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
        df['-dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)

        # Сглаживание методом Уайлдера (EWM с alpha=1/period)
        alpha = 1 / period
        
        # ВАЖНО: для ATR используем ТОТ ЖЕ метод сглаживания, что и для DM
        # Начинаем с SMA для первого значения, затем EWM
        df['tr_s'] = df['tr'].ewm(alpha=alpha, adjust=False).mean()
        df['+dm_s'] = df['+dm'].ewm(alpha=alpha, adjust=False).mean()
        df['-dm_s'] = df['-dm'].ewm(alpha=alpha, adjust=False).mean()
        
        # ИСПРАВЛЕНИЕ: ATR должен использовать Wilder's Smoothing, а не SMA
        df['atr'] = df['tr_s'].copy()  # Теперь ATR - это сглаженный TR по методу Уайлдера

        # Расчет +DI, -DI с защитой от деления на ноль
        # Добавляем epsilon, чтобы избежать деления на 0
        epsilon = 1e-10
        df['+di'] = 100 * (df['+dm_s'] / (df['tr_s'] + epsilon))
        df['-di'] = 100 * (df['-dm_s'] / (df['tr_s'] + epsilon))

        # DX с защитой от деления на ноль
        di_sum = df['+di'] + df['-di']
        di_diff = abs(df['+di'] - df['-di'])
        df['dx'] = 100 * (di_diff / (di_sum + epsilon))

        # Финальный ADX (сглаживание DX тем же методом)
        df['adx'] = df['dx'].ewm(alpha=alpha, adjust=False).mean()

        # ДОПОЛНЕНИЕ 1: Расчет %ATR правильно (используем исправленный atr)
        df['pct_atr'] = (df['atr'] / df['close']) * 100

        # ДОПОЛНЕНИЕ 2: Индикатор сжатия/расширения полос Боллинджера (BB Width)
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        df['bb_std'] = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_middle'] - 2 * df['bb_std']
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle'] * 100

        # ДОПОЛНЕНИЕ 3: Фильтр "переплетения" +DI и -DI
        # Полезно для отсеивания ложных боковиков, где линии расходятся
        df['di_cross'] = ((df['+di'] - df['-di']).abs() < 5)  # Расхождение меньше 5%

        # ДОПОЛНЕНИЕ 4: Проверка на наличие тренда через соотношение DI
        # Если одна из DI значительно выше другой - это тренд, даже при низком ADX
        df['di_trend'] = ((df['+di'] - df['-di']).abs() > 10)  # Сильное расхождение

        # ДОПОЛНЕНИЕ 5: Уровень поддержки/сопротивления на основе последних экстремумов
        # Для определения границ будущей сетки
        lookback = 50
        df['recent_high'] = df['high'].rolling(window=lookback).max()
        df['recent_low'] = df['low'].rolling(window=lookback).min()
        df['range_percent'] = ((df['recent_high'] - df['recent_low']) / df['recent_low']) * 100

        # Очистка от промежуточных колонок (опционально)
        # Можно закомментировать, если нужно видеть все шаги расчета
        cols_to_drop = ['h-l', 'h-pc', 'l-pc', 'up_move', 'down_move', '+dm', '-dm']
        df = df.drop(columns=[col for col in cols_to_drop if col in df.columns])

        return df



    # # поиск подходящих активов
    # def get_suitable_symbols(self):
    #     suitable_symbols = [] # список подходящих активов
        
    #     # запрос данных с биржи
    #     markets = self.exchange.fetch_markets()
    #     # спотовые пары к USDT
    #     symbols = [m['symbol'] for m in markets if m['spot'] and m['quote'] == 'USDT']
        
    #     # загрузка свечей опр. пары
    #     for symbol in symbols:
    #         ohlcv = self.exchange.fetch_ohlcv(symbol=symbol,
    #                                           timeframe=TIMEFRAME,
    #                                           limit=300)
    #         df = pd.DataFrame(data=ohlcv,
    #                           columns=['timestamp', 'open', 'high',
    #                                     'low', 'close', 'volume'])
            
    #         # проверка обьема за 24ч
    #         ticker = self.exchange.fetch_ticker(symbol)
    #         volume_24h = round(ticker['quoteVolume'])
            
    #         df = self.calculate_indicators(df)
    #         last_row = df.iloc[-1]
    #         adx_val = round(last_row['adx'], 2)
    #         pct_atr = round(last_row['pct_atr'], 2)
    #         current_price = last_row['close']

    #         symbol_with_grid_parameters = get_grid_parameters(symbol=symbol,
    #                                                           pct_atr=pct_atr,
    #                                                           current_price=current_price,
    #                                                         )
    #         final_grids = symbol_with_grid_parameters['Final grids']

    #         if  (adx_val < MAX_ADX and 
    #              pct_atr >= MIN_VOLATILITY and 
    #              volume_24h >= MIN_VOLUME_24H and 
    #              final_grids >= 10):
    #             print(bcolors.OKGREEN + "[SUCCESS] " + bcolors.ENDC + f"{bcolors.OKBLUE}{symbol}{bcolors.ENDC}: ADX {bcolors.OKBLUE}{adx_val}{bcolors.ENDC} | ATR {bcolors.OKBLUE}{pct_atr}{bcolors.ENDC} | VOL {bcolors.OKBLUE}{volume_24h}{bcolors.ENDC} | final_grids {bcolors.OKBLUE}{final_grids}{bcolors.ENDC}")
    #             print(symbol_with_grid_parameters)
    #             print('=======================================')
    #             suitable_symbols.append(symbol_with_grid_parameters)
                
    #         else:
    #             # print(bcolors.FAIL +"[FAIL] " + bcolors.ENDC + f"АКТИВ {symbol} НЕ ПОДХОДИТ")
    #             print(bcolors.FAIL +"[FAIL] " + bcolors.ENDC + f"{bcolors.OKBLUE}{symbol}{bcolors.ENDC}: ADX {bcolors.OKBLUE}{adx_val}{bcolors.ENDC} | ATR {bcolors.OKBLUE}{pct_atr}{bcolors.ENDC} | VOL {bcolors.OKBLUE}{volume_24h}{bcolors.ENDC} | final_grids {bcolors.OKBLUE}{final_grids}{bcolors.ENDC}")
                

    #             print(symbol_with_grid_parameters)
    #             print('=======================================')

    #     return suitable_symbols

    def get_suitable_symbols(self):
        """
        Поиск активов, подходящих для запуска спотового grid-бота.
        Использует расширенную фильтрацию на основе ADX, ATR%, DI, полос Боллинджера и диапазона.
        """
        suitable_symbols = []
        
        # Получаем список спотовых пар к USDT
        markets = self.exchange.fetch_markets()
        symbols = [m['symbol'] for m in markets if m['spot'] and m['quote'] == 'USDT']
        
        for symbol in symbols:
            try:
                # Загружаем свечи
                ohlcv = self.exchange.fetch_ohlcv(symbol=symbol,
                                                timeframe=TIMEFRAME,
                                                limit=300)  # 300 свечей достаточно для всех расчётов
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                # Суточный объём (в USDT)
                ticker = self.exchange.fetch_ticker(symbol)
                volume_24h = round(ticker['quoteVolume'])
                
                # Рассчитываем индикаторы (обновлённая версия)
                df = self.calculate_indicators(df)
                
                # Берём последнюю завершённую свечу
                last_row = df.iloc[-1]
                adx_val = round(last_row['adx'], 2)
                pct_atr = round(last_row['pct_atr'], 2)
                current_price = last_row['close']
                
                # Параметры сетки (количество уровней и т.д.)
                # Предполагается, что get_grid_parameters использует pct_atr и current_price
                grid_params = get_grid_parameters(symbol=symbol,
                                                pct_atr=pct_atr,
                                                current_price=current_price)
                final_grids = grid_params.get('Final grids', 0)
                
                # Основная фильтрация по индикаторам (новый метод)
                is_indicator_ok = self.filter_for_grid(df)
                
                # Дополнительные рыночные условия
                if (is_indicator_ok and 
                    volume_24h >= MIN_VOLUME_24H and 
                    final_grids >= 10):
                    
                    print(bcolors.OKGREEN + "[SUCCESS] " + bcolors.ENDC + 
                        f"{bcolors.OKBLUE}{symbol}{bcolors.ENDC}: "
                        f"ADX {bcolors.OKBLUE}{adx_val}{bcolors.ENDC} | "
                        f"ATR% {bcolors.OKBLUE}{pct_atr}{bcolors.ENDC} | "
                        f"VOL {bcolors.OKBLUE}{volume_24h}{bcolors.ENDC} | "
                        f"GRIDS {bcolors.OKBLUE}{final_grids}{bcolors.ENDC}")
                    print(grid_params)
                    print('=======================================')
                    suitable_symbols.append(grid_params)
                    
                else:
                    # Если не прошёл – выводим причину (из filter_for_grid уже напечатано, но можно и здесь)
                    fail_reason = "не прошёл индикаторы" if not is_indicator_ok else "объём или сетки"
                    print(bcolors.FAIL + "[FAIL] " + bcolors.ENDC + 
                        f"{bcolors.OKBLUE}{symbol}{bcolors.ENDC}: "
                        f"ADX {bcolors.OKBLUE}{adx_val}{bcolors.ENDC} | "
                        f"ATR% {bcolors.OKBLUE}{pct_atr}{bcolors.ENDC} | "
                        f"VOL {bcolors.OKBLUE}{volume_24h}{bcolors.ENDC} | "
                        f"GRIDS {bcolors.OKBLUE}{final_grids}{bcolors.ENDC} | "
                        f"REASON: {fail_reason}")
                    print(grid_params)
                    print('=======================================')
                    
            except Exception as e:
                print(bcolors.WARNING + f"[ERROR] {symbol}: {e}" + bcolors.ENDC)
                continue
        
        return suitable_symbols
    

if __name__ == "__main__":
    print(bcolors.OKBLUE + "======= КОНФИГУРАЦИЯ =======" + bcolors.ENDC)
    print(f"Макс. значение ADX: {bcolors.OKBLUE}{MAX_ADX}{bcolors.ENDC}")
    print(f"Мин. волатильность: {bcolors.OKBLUE}{MIN_VOLATILITY}{bcolors.ENDC}")
    print(f"Мин. торговый обьем (24ч): {bcolors.OKBLUE}{MIN_VOLUME_24H}{bcolors.ENDC}")
    print("------------")
    print(f"Таймфрейм для замера индикаторов: {bcolors.OKBLUE}{TIMEFRAME}{bcolors.ENDC}")
    print(f"Депозит: {bcolors.OKBLUE}{BUDGET}${bcolors.ENDC}")
    print(f"Суммарная комиссия (taker + maker): {bcolors.OKBLUE}{EXCHANGE_FEE}${bcolors.ENDC}")
    print(f"Мин. чистая прибыль на сетку: {bcolors.OKBLUE}{MIN_NET_PROFIT}${bcolors.ENDC}")
    print(bcolors.OKBLUE + "============================" + bcolors.ENDC)
    
    ans = input("Начать поиск? (y - да / n - нет): ")
    
    if ans == 'y':
        bot = Bot('bybit')
        try:
            start = time.time()
            suitable_symbols = bot.get_suitable_symbols()
            stop = time.time()

            working_time = (stop - start) * 1000

            if len(suitable_symbols):
                print("===== ПОДХОДЯЩИЕ АКТИВЫ =====")
                for symbol in suitable_symbols:
                    print(f"Актив: {symbol['Symbol']}")
                    print(f"Цена: {symbol['Price']}")
                    print(f"Ценовой диапазон: {symbol['Range']}")
                    print(f"Интервал: {symbol['Interval']}")
                    print(f"Профит: {symbol['Profit']}")
                    print()
            else:
                print("Подходящих активов не найдено(") 
            
            print(f"Время выполнения: {working_time:.2f} мс")

        except KeyboardInterrupt:
            print(f"{bcolors.OKCYAN}[STOP]{bcolors.ENDC} Программа остановлена.")