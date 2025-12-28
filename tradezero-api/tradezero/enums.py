from enum import Enum

class Order(Enum):
    BUY = 'buy'
    SELL = 'sell'
    SHORT = 'short'
    COVER = 'cover'

class TIF(Enum):
    DAY = 'DAY'
    GTC = 'GTC'
    GTX = 'GTX'
