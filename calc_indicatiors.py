import pandas as pd
import numpy as np

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
