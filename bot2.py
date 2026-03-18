import ccxt
import time
import pandas as pd
import numpy as np

from bcolors import bcolors

# ==================== КОНСТАНТЫ ====================
MAX_ADX = 25
MIN_ATR_PERCENT = 1.5           # минимальная волатильность для "маятника"
MAX_ATR_PERCENT = 4.0           # максимальная волатильность, чтобы не вылететь за сетку
DI_CROSS_THRESHOLD = 5          # порог "переплетения" линий DI (не используется напрямую)
DI_TREND_THRESHOLD = 10         # расхождение DI, считающееся трендом

MIN_VOLUME_24H = 5_000_000
MIN_NET_PROFIT = 0.5            # минимум 0.5% чистой прибыли на сделку
EXCHANGE_FEE = 0.2              # суммарная комиссия Bybit (0.1% * 2)
BUDGET = 50
TIMEFRAME = '15m'

# ==================== ФУНКЦИЯ РАСЧЁТА ПАРАМЕТРОВ СЕТКИ ====================
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


# ==================== ОСНОВНОЙ КЛАСС БОТА ====================
class Bot:
    def __init__(self, exchange_name: str):
        self.exchange_name = exchange_name
        # инициализация подключения к бирже (атрибут экземпляра)
        self.exchange = ccxt.bybit({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            }
        })

    # ========== РАСЧЁТ ИНДИКАТОРОВ ==========
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

    # ========== ФИЛЬТР ПРИГОДНОСТИ ДЛЯ GRID ==========
    def filter_for_grid(self, df: pd.DataFrame, current_idx=-1) -> bool:
        """
        Комплексная проверка индикаторов для отбора активов под grid-бота.
        Возвращает True, если актив подходит.
        """
        last = df.iloc[current_idx]

        # Условия
        cond1 = last['adx'] < MAX_ADX                               # ADX < 25
        cond2 = MIN_ATR_PERCENT <= last['pct_atr'] <= MAX_ATR_PERCENT  # ATR% в диапазоне
        cond3 = not last['di_trend']                                 # DI не расходятся (нет тренда)
        # Ширина полос Боллинджера меньше среднего за 50 свечей (сжатие)
        bb_mean = df['bb_width'].rolling(50).mean().iloc[current_idx]
        cond4 = last['bb_width'] < bb_mean
        # Общий диапазон за 50 свечей не превышает 20%
        cond5 = last['range_percent'] <= 20

        # Отладка (можно закомментировать)
        if not all([cond1, cond2, cond3, cond4, cond5]):
            failed = []
            if not cond1: failed.append(f'ADX > {MAX_ADX}')
            if not cond2: failed.append(f'ATR% not in [{MIN_ATR_PERCENT}, {MAX_ATR_PERCENT}]')
            if not cond3: failed.append('DI_trend')
            if not cond4: failed.append(f'BB_width > {bb_mean}')
            if not cond5: failed.append(f'range_percent > 20')
            print(f"DEBUG: {failed}")

        return all([cond1, cond2, cond3, cond4, cond5])

    # ========== ПОИСК ПОДХОДЯЩИХ АКТИВОВ ==========
    def get_suitable_symbols(self):
        """
        Перебирает все спотовые пары USDT, загружает данные,
        рассчитывает индикаторы и отбирает подходящие для grid-бота.
        """
        suitable_symbols = []

        markets = self.exchange.fetch_markets()
        symbols = [m['symbol'] for m in markets if m['spot'] and m['quote'] == 'USDT']

        for symbol in symbols:
            try:
                # Загружаем свечи
                ohlcv = self.exchange.fetch_ohlcv(symbol=symbol,
                                                   timeframe=TIMEFRAME,
                                                   limit=300)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

                # Суточный объём
                ticker = self.exchange.fetch_ticker(symbol)
                volume_24h = round(ticker['quoteVolume'])

                # Индикаторы
                df = self.calculate_indicators(df)

                # Последняя свеча
                last_row = df.iloc[-1]
                adx_val = round(last_row['adx'], 2)
                pct_atr = round(last_row['pct_atr'], 2)
                current_price = last_row['close']

                # Параметры сетки
                grid_params = get_grid_parameters(symbol=symbol,
                                                   pct_atr=pct_atr,
                                                   current_price=current_price)
                final_grids = grid_params.get('Final grids', 0)

                # Проверка по индикаторам
                is_indicator_ok = self.filter_for_grid(df)

                # Финальное решение
                if (is_indicator_ok and
                    volume_24h >= MIN_VOLUME_24H and
                    final_grids >= 10):

                    print(bcolors.OKGREEN + "[SUCCESS] " + bcolors.ENDC +
                          f"{bcolors.OKBLUE}{symbol}{bcolors.ENDC}: "
                          f"ADX {bcolors.OKBLUE}{adx_val}{bcolors.ENDC} | "
                          f"ATR% {bcolors.OKBLUE}{pct_atr}{bcolors.ENDC} | "
                          f"VOL {bcolors.OKBLUE}{volume_24h}{bcolors.ENDC} | "
                          f"GRIDS {bcolors.OKBLUE}{final_grids}{bcolors.ENDC}")
                    # print(grid_params)
                    print('=======================================')
                    suitable_symbols.append(grid_params)

                else:
                    fail_reason = "индикаторы" if not is_indicator_ok else "объём или сетки"
                    print(bcolors.FAIL + "[FAIL] " + bcolors.ENDC +
                          f"{bcolors.OKBLUE}{symbol}{bcolors.ENDC}: "
                          f"ADX {bcolors.OKBLUE}{adx_val}{bcolors.ENDC} | "
                          f"ATR% {bcolors.OKBLUE}{pct_atr}{bcolors.ENDC} | "
                          f"VOL {bcolors.OKBLUE}{volume_24h}{bcolors.ENDC} | "
                          f"GRIDS {bcolors.OKBLUE}{final_grids}{bcolors.ENDC} | "
                          f"REASON: {fail_reason}")
                    
                    print('=======================================')

            except Exception as e:
                print(bcolors.WARNING + f"[ERROR] {symbol}: {e}" + bcolors.ENDC)
                continue

        return suitable_symbols


# ==================== ТОЧКА ВХОДА ====================
if __name__ == "__main__":
    print(bcolors.OKBLUE + "======= КОНФИГУРАЦИЯ =======" + bcolors.ENDC)
    print(f"Макс. значение ADX: {bcolors.OKBLUE}{MAX_ADX}{bcolors.ENDC}")
    print(f"Мин. волатильность: {bcolors.OKBLUE}{MIN_ATR_PERCENT}%{bcolors.ENDC}")
    print(f"Макс. волатильность: {bcolors.OKBLUE}{MAX_ATR_PERCENT}%{bcolors.ENDC}")
    print(f"Мин. торговый объём (24ч): {bcolors.OKBLUE}{MIN_VOLUME_24H} USDT{bcolors.ENDC}")
    print("------------")
    print(f"Таймфрейм для замера индикаторов: {bcolors.OKBLUE}{TIMEFRAME}{bcolors.ENDC}")
    print(f"Депозит: {bcolors.OKBLUE}{BUDGET} USDT{bcolors.ENDC}")
    print(f"Суммарная комиссия (taker + maker): {bcolors.OKBLUE}{EXCHANGE_FEE}%{bcolors.ENDC}")
    print(f"Мин. чистая прибыль на сетку: {bcolors.OKBLUE}{MIN_NET_PROFIT}%{bcolors.ENDC}")
    print(bcolors.OKBLUE + "============================" + bcolors.ENDC)

    ans = input("Начать поиск? (y - да / n - нет): ").strip().lower()
    if ans == 'y':
        bot = Bot('bybit')
        try:
            start = time.time()
            suitable_symbols = bot.get_suitable_symbols()
            stop = time.time()
            working_time = (stop - start) * 1000  # миллисекунды

            if suitable_symbols:
                print("===== ПОДХОДЯЩИЕ АКТИВЫ =====")
                for sym in suitable_symbols:
                    print(f"Актив: {sym['Symbol']}")
                    print(f"Цена: {sym['Price']}")
                    print(f"Ценовой диапазон: {sym['Range']}")
                    print(f"Интервал: {sym['Interval']}")
                    print(f"Профит: {sym['Profit']}")
                    print()
            else:
                print("Подходящих активов не найдено(")

            print(f"Время выполнения: {working_time:.2f} мс")

        except KeyboardInterrupt:
            print(f"{bcolors.OKCYAN}[STOP]{bcolors.ENDC} Программа остановлена.")
    else:
        print("Выход.")