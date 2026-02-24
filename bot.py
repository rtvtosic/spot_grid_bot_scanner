import ccxt


class Bot:
    def __init__(self, exchange: str):
        self.exchange = exchange
    
    def get_exchange(self):
        return self.exchange
    def set_exchange(self, new_exchange: str):
        self.exchange = new_exchange

    # загрузка данных с биржи
    def get_market_data(self):
        if self.exchange == 'bybit':
            exchange = ccxt.bybit()
        
        # запрос данных с биржи
        markets = exchange.fetch_markets()

        # спотовые пары к USDT
        symbols = [m['symbol'] for m in markets if m['spot'] and m['quote'] == 'USDT']
        return symbols


if __name__ == "__main__":
    bot = Bot('bybit')

    print(bot.get_exchange())
    
    print(bot.get_market_data())

