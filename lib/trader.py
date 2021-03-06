#!/usr/bin/env python

from lib.bittrex import bittrex
from secrets import BITTREX_KEY, BITTREX_SECRET, DEMO, TRADE, SAFE_ORDER
import datetime


class Trader:
    signal = None
    api = None
    bot = None
    target = None
    stop_loss = None
    profit_btc = None
    profit_percent = None
    chat_id = None
    btc_price = None

    def __init__(self, signal=None, bot=None, chat_id=None):
        self.signal = signal
        self.bot = bot
        self.api = bittrex(BITTREX_KEY, BITTREX_SECRET)
        if self.signal:
            self.current_price = self.get_last_price()
            self.btc_price = self.getBTCPrice()
            self.chat_id = self.signal.chat_id
        if chat_id:
            self.chat_id = chat_id

    # Load the basic properties
    def load(self):
        # Calculate the target price
        self.target = self.calc_target_price()
        # Calculate the stoploss price
        self.stop_loss = self.calc_stoploss_price()
        # Calculate the current profit in BTC
        self.profit_btc = self.calc_profit(self.current_price)
        # Calculate the current profit percentage
        self.profit_percent = self.calc_profit_precent(self.current_price)

    # Analises the signal and perform the necessary market orders
    def process(self):
        # Bittrex API error (probably a 5xx error)
        if not self.current_price:
            self.message('Bittrex: price error!')
            return

        self.load()

        self.log(
            'Current: %s | Bought: %s | Target: %s | Stoploss: %s | Profit: %s %s (%s %%)'
            % (
                format(self.current_price, '.8f'),
                format(self.signal.b_price, '.8f'),
                format(self.target, '.8f'),
                format(self.stop_loss, '.8f'),
                format(self.profit_btc, '.8f'),
                TRADE,
                round(self.profit_percent, 2)
            )
        )

        # Update the signal with the current / highest / lowest prices
        self.prices_update()

        # Bought signals
        if self.signal.status == 3:
            # Profit sell (current price higher or equal to the target)
            if self.current_price >= self.target:
                self.log('Profit!')
                self.sell()
                return

            # Stop loss sell (current price lower or equal to the stop loss)
            if self.stop_loss and self.current_price <= float(self.stop_loss):
                self.log('Stop loss reached!')
                self.sell()
                return

        # Buy or Sell open orders
        elif self.signal.status == 2 or self.signal.status == 4:
            if self.signal.status == 2:
                uuid = self.signal.b_uuid
            elif self.signal.status == 4:
                uuid = self.signal.s_uuid
            # Check the order status
            order = self.api.getorder(uuid)
            print order
            if order['IsOpen'] is not True:
                # Update the order
                if order['CancelInitiated'] is True:
                    self.cancelled(order)
                else:
                    self.processed(order)
                return

    # Get the last market price
    def get_last_price(self, coin=None):
        if coin is None:
            coin = self.signal.market
        try:
            summary = self.api.getmarketsummary(coin)
            return float(summary[0]['Last'])
        except:
            pass

    # Calculate the stop loss price
    def calc_stoploss_price(self):
        # Price source
        if self.signal.b_price:
            b_price = self.signal.b_price
        else:
            b_price = self.current_price
        # Percentage
        if self.signal.stop_loss_percent is not None:
            return float(b_price) - ((
                float(self.signal.stop_loss_percent) *
                float(b_price)
            ) / 100)
        # Amount
        elif self.signal.stop_loss is not None:
            return self.signal.stop_loss
        # No stop loss
        return 0

    # Calculate the target price
    def calc_target_price(self):
        # Percentage
        if self.signal.win_percent is not None:
            return float(self.signal.b_price) + ((
                float(self.signal.win_percent) *
                float(self.signal.b_price)
            ) / 100)
        # Amount
        else:
            return self.signal.win_price

    # Calculate the price to sell
    # (current price - SAFE ORDER %, for faster processing)
    def calc_sell_price(self):
        return float(self.current_price) - ((
                    float(SAFE_ORDER) *
                    float(self.current_price)
                ) / 100)

    # Calc a profit in BTC based on a sell price
    def calc_profit(self, sell_price):
        price_change = float(sell_price) - float(self.signal.b_price)
        return (price_change * float(self.signal.quantity))

    # Calc a profit percent based on a sell price
    def calc_profit_precent(self, sell_price):
        top = float(self.signal.b_price) - float(sell_price)
        bottom = float(self.signal.b_price) + float(sell_price)
        bottom = bottom / 2
        total = top / bottom * 100
        if float(self.signal.b_price) > float(sell_price):
            total = -abs(total)
        else:
            total = abs(total)
        return float(total)

    # Create a buy order
    def buy(self):

        # Bittrex API error (probably a 5xx error)
        if not self.current_price:
            self.message('Bittrex: price error!')
            return

        # stop loss protection
        stop_loss = self.calc_stoploss_price()
        if stop_loss and self.current_price <= float(stop_loss):
            self.message('Can\'t buy, stop loss reached (%s)' % format(self.current_price, '.8f'))
            return

        if DEMO:
            return self.buy_update()

        # Places the order
        quantity = self.signal.btc / self.current_price
        order = self.api.buylimit(
            self.signal.market,
            quantity,
            self.current_price
        )

        # Possible API errors
        try:
            order['uuid']
        except:
            self.message('%s (%s): API Error: %s' % (self.signal.id, self.signal.coin, order))
            return

        # Updates the order
        self.buy_update(order['uuid'])

    # Create a sell order
    def sell(self):
        # Reduces the sell price for faster processing
        sell_price = self.calc_sell_price()
        self.log('Adjusted sell price: %s' % format(sell_price, '.8f'))

        if DEMO:
            return self.sell_update()

        # Places the order
        order = self.api.selllimit(
            self.signal.market,
            self.signal.quantity,
            sell_price
        )

        # Possible API errors
        try:
            order['uuid']
        except:
            self.message('API Error: %s' % order)
            self.message('Quantity: %s | Price: %s' % (
                format(self.signal.quantity, '.8f'),
                format(sell_price, '.8f')
            ))
            return

        # Updates the order
        self.sell_update(order['uuid'])

    # Mark the order as cancelled
    def cancelled(self, order):
        self.signal.status = 6
        self.signal.save()

        # Message
        self.message('%s order cancelled!' % (self.signal.coin))

    # Mark the order as processed
    def processed(self, order):
        # Buy order
        if order['Type'] == 'LIMIT_BUY':
            order_type = 'Buy'
            self.signal.status = 3
        # Sell order
        else:
            order_type = 'Sell'
            self.signal.status = 5
        self.signal.save()

        # Message
        self.message('%s %s order processed!' % (self.signal.coin, order_type))

    # Updates a completed buy order
    def buy_update(self, uuid=None):
        # Real order
        if uuid:
            order = self.api.getorder(uuid)
            print order
            quantity = order['Quantity']
            price = order['Limit']
            comission = order['CommissionPaid']
            status = 2
            uuid = uuid

        # Demo order
        else:
            price = self.current_price
            quantity = self.signal.btc / self.current_price
            comission = 0
            status = 3
            uuid = 'DEMO'

        self.signal.quantity = quantity
        self.signal.b_price = price
        self.signal.b_uuid = uuid
        self.signal.b_comision = comission
        self.signal.b_date = datetime.datetime.now()
        self.signal.status = status
        self.signal.save()

        # Message
        self.message(
            'Buy order placed: %s %s at %s for %s %s (%s USD)' %
            (
                quantity,
                self.signal.coin,
                format(price, '.8f'),
                self.signal.btc,
                TRADE,
                round(self.btc_price * self.signal.btc, 2)
            )
        )

    # Updates a completed sell order
    def sell_update(self, uuid=None):
        # Real order
        if uuid:
            order = self.api.getorder(uuid)
            print order
            price = order['Limit']
            comission = order['CommissionPaid']
            status = 4
            uuid = uuid

        # Demo order
        else:
            price = self.calc_sell_price()
            comission = 0
            status = 5
            uuid = 'DEMO'

        self.signal.s_price = price
        self.signal.s_uuid = uuid
        self.signal.s_comision = round(comission, 8)
        self.signal.s_date = datetime.datetime.now()
        self.signal.status = status

        # BTC Price
        btc_price = float(self.signal.s_price) * float(self.signal.quantity)

        # Profit
        self.signal.profit_btc = self.calc_profit(self.signal.s_price)
        self.signal.profit_percent = self.calc_profit_precent(self.signal.s_price)

        self.signal.save()

        # Message
        self.message(
            'Sell order placed: %s %s at %s for %s %s \n(%s %% profit! | %s %s | %s USD)' %
            (
                self.signal.quantity,
                self.signal.coin,
                format(price, '.8f'),
                format(btc_price, '.8f'),
                TRADE,
                round(self.signal.profit_percent, 2),
                format(self.signal.profit_btc, '.8f'),
                TRADE,
                round(self.btc_price * self.profit_btc, 2)
            )
        )

    # Update the signal with the current / highest / lowest prices
    def prices_update(self):
        highest_price = self.signal.highest_price
        if highest_price < self.current_price or highest_price is None:
            self.signal.highest_price = self.current_price

        lowest_price = self.signal.lowest_price
        if lowest_price > self.current_price or lowest_price is None:
            self.signal.lowest_price = self.current_price

        self.signal.current_price = self.current_price
        self.signal.save()

    # Shows a console log message
    def log(self, text):
        if self.signal:
            print '[%d][%s] %s' % (self.signal.id, self.signal.market, text)
        else:
            print '%s' % text

    # Sends the current signal status
    def status(self):
        self.message(
            '%s: \nCurrent: %s \nBought: %s \nTarget: %s \nStoploss: %s \nProfit: %s %s (%s %% | %s USD)'
            % (
                self.signal.coin,
                format(self.current_price, '.8f'),
                format(self.signal.b_price, '.8f'),
                format(self.target, '.8f'),
                format(self.stop_loss, '.8f'),
                format(self.profit_btc, '.8f'),
                TRADE,
                round(self.profit_percent, 2),
                round(self.btc_price * self.profit_btc, 2)
            )
        )

    # Sends the current amount of BTCs (available / used) and its price
    def btcs(self):
        availableBTCs = self.getAvailableBTCs()
        price = self.getBTCPrice()
        total = self.getTotalBTCs()
        usd = total * price

        self.message('Available BTCs: %s' % format(availableBTCs, '.8f'))
        self.message('Total BTCs: %s' % format(total, '.8f'))
        self.message('Total USD: %s' % int(usd))

    # Get the BTC Price
    def getBTCPrice(self):
        response = self.api.getBTCPrice()
        return response['bpi']['USD']['rate_float']

    # Get the available BTCs
    def getAvailableBTCs(self):
        response = self.api.getbalance('BTC')
        return response['Available']

    # Get total BTCs
    def getTotalBTCs(self):
        availableBTCs = self.getAvailableBTCs()
        balances = self.api.getbalances()
        total = 0
        for balance in balances:
            amount = balance['Available']
            if amount > 0:
                coin = balance['Currency']
                if coin is TRADE:
                    total += amount
                else:
                    price = self.get_last_price(TRADE + '-' + coin)
                    if price:
                        btcs = amount * price
                        total += btcs
        return total + availableBTCs

    # Sends a telegram message
    def message(self, text):
        if self.bot:
            try:
                self.bot.send_message(self.chat_id, text)
            except Exception as e:
                self.log('Telegram error: %s' % str(e))
                self.log('Message: %s' % text)
        print text
