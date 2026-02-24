import ccxt
import pandas as pd


class Bot:
    exchange = ccxt.bybit()

    def __init__(self, exchange_name: str):
        self.exchange_name = exchange_name
    
    def get_exchange(self):
        return self.exchange
    def set_exchange(self, new_exchange_name: str):
        self.exchange_name = new_exchange_name

    # загрузка спотовых пар к USDT с биржи
    def get_market_data(self) -> list[dict]:
        if self.exchange_name == 'bybit':
            exchange = ccxt.bybit()
        
        # запрос данных с биржи
        markets = self.exchange.fetch_markets()

        # спотовые пары к USDT
        symbols = [m['symbol'] for m in markets if m['spot'] and m['quote'] == 'USDT']
        
        # загрузка свечей опр. пары
        for symbol in symbols:
            ohlcv = self.exchange.fetch_ohlcv(symbol)
            df = pd.DataFrame(data=ohlcv,
                              columns=['timestamp', 'open', 'high',
                                        'low', 'close', 'volume'])
            



            print(df.head())
            break
    



if __name__ == "__main__":
    bot = Bot('bybit')

    print(bot.get_exchange())
    
    print(bot.get_market_data())


