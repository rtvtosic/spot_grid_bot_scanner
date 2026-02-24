import ccxt


class Bot:
    exchange: str
    fee: float
    deposit: float

    def __init__(self, exchange: str, fee: float = 0, deposit: float = 0):
        self.exchange = exchange
        self.fee = fee
        self.deposit = deposit
    
    def get_exchange(self):
        return self.exchange
    def set_exchange(self, new_exchange: str):
        self.exchange = new_exchange

    # загрузка спотовых пар к USDT с биржи
    def get_market_data(self) -> list[dict]:
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
    
    print(bot.get_market_data()[0])


