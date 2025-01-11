from enum import Enum
from schwab.orders.common import Duration, EquityInstruction, OrderStrategyType, OrderType, \
                                 Session, StopType, StopPriceLinkType, StopPriceLinkBasis
from schwab.orders.generic import OrderBuilder


gtc_days_default = 120


##########################################################################
# Buy orders

def equity_buy_market(symbol, quantity, session=Session.NORMAL, duration=Duration.DAY):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    buy market order.
    '''
    return (OrderBuilder()
            .set_order_type(OrderType.MARKET)
            .set_session(session)
            .set_duration(duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.BUY, symbol, quantity))


def equity_buy_limit(symbol, quantity, price, session=Session.NORMAL, duration=Duration.DAY, date_input=gtc_days_default):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    buy limit order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.LIMIT)
            .set_price(price)
            .set_session(session)
            .set_duration(duration)
            .set_cancel_date(date_input, duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.BUY, symbol, quantity))

def equity_buy_stop(symbol, quantity, price, session=Session.NORMAL, duration=Duration.DAY, date_input=gtc_days_default):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    buy limit order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.STOP)
            .set_stop_price(price)
            .set_stop_type(StopType.STANDARD)
            .set_session(session)
            .set_duration(duration)
            .set_cancel_date(date_input, duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.BUY, symbol, quantity))


def equity_buy_trailing_stop(symbol, quantity, price_offset,
                             session=Session.NORMAL, duration=Duration.DAY, date_input=gtc_days_default,
                             stop_price_link_type=StopPriceLinkType.VALUE,
                             stop_price_link_basis=StopPriceLinkBasis.MARK,
                             stop_type=StopType.MARK
                             ):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    buy limit order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.TRAILING_STOP)
            .set_stop_price_offset(price_offset)
            .set_price_link_type(stop_price_link_type)
            .set_stop_price_link_basis(stop_price_link_basis)
            .set_stop_type(stop_type)
            .set_session(session)
            .set_duration(duration)
            .set_cancel_date(date_input, duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.BUY, symbol, quantity))

##########################################################################
# Sell orders


def equity_sell_market(symbol, quantity, session=Session.NORMAL, duration=Duration.DAY):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    sell market order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.MARKET)
            .set_session(session)
            .set_duration(duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.SELL, symbol, quantity))


def equity_sell_limit(symbol, quantity, price, session=Session.NORMAL, duration=Duration.DAY, date_input=gtc_days_default):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    sell limit order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.LIMIT)
            .set_price(price)
            .set_session(session)
            .set_duration(duration)
            .set_cancel_date(date_input, duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.SELL, symbol, quantity))

def equity_sell_stop(symbol, quantity, price, session=Session.NORMAL, duration=Duration.DAY, date_input=gtc_days_default):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    buy limit order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.STOP)
            .set_stop_price(price)
            .set_stop_type(StopType.STANDARD)
            .set_session(session)
            .set_duration(duration)
            .set_cancel_date(date_input, duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.SELL, symbol, quantity))


def equity_sell_trailing_stop(symbol, quantity, price_offset,
                             session=Session.NORMAL, duration=Duration.DAY, date_input=gtc_days_default,
                             stop_price_link_type=StopPriceLinkType.VALUE,
                             stop_price_link_basis=StopPriceLinkBasis.MARK,
                             stop_type=StopType.MARK
                             ):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    buy limit order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.TRAILING_STOP)
            .set_stop_price_offset(price_offset)
            .set_price_link_type(stop_price_link_type)
            .set_stop_price_link_basis(stop_price_link_basis)
            .set_stop_type(stop_type)
            .set_session(session)
            .set_duration(duration)
            .set_cancel_date(date_input, duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.SELL, symbol, quantity))



##########################################################################
# Short sell orders


def equity_sell_short_market(symbol, quantity, session=Session.NORMAL, duration=Duration.DAY):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    short sell market order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.MARKET)
            .set_session(session)
            .set_duration(duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.SELL_SHORT, symbol, quantity))


def equity_sell_short_limit(symbol, quantity, price, session=Session.NORMAL, duration=Duration.DAY, date_input=gtc_days_default):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    short sell limit order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.LIMIT)
            .set_price(price)
            .set_session(session)
            .set_duration(duration)
            .set_cancel_date(date_input, duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.SELL_SHORT, symbol, quantity))

def equity_sell_short_stop(symbol, quantity, price, session=Session.NORMAL, duration=Duration.DAY, date_input=gtc_days_default):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    buy limit order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.STOP)
            .set_stop_price(price)
            .set_stop_type(StopType.STANDARD)
            .set_session(session)
            .set_duration(duration)
            .set_cancel_date(date_input, duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.SELL_SHORT, symbol, quantity))


def equity_sell_short_trailing_stop(symbol, quantity, price_offset,
                             session=Session.NORMAL, duration=Duration.DAY, date_input=gtc_days_default,
                             stop_price_link_type=StopPriceLinkType.VALUE,
                             stop_price_link_basis=StopPriceLinkBasis.MARK,
                             stop_type=StopType.MARK
                             ):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    buy limit order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.TRAILING_STOP)
            .set_stop_price_offset(price_offset)
            .set_price_link_type(stop_price_link_type)
            .set_stop_price_link_basis(stop_price_link_basis)
            .set_stop_type(stop_type)
            .set_session(session)
            .set_duration(duration)
            .set_cancel_date(date_input, duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.SELL_SHORT, symbol, quantity))
##########################################################################
# Buy to cover orders


def equity_buy_to_cover_market(symbol, quantity, session=Session.NORMAL, duration=Duration.DAY,):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    buy-to-cover market order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.MARKET)
            .set_session(session)
            .set_duration(duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.BUY_TO_COVER, symbol, quantity))


def equity_buy_to_cover_limit(symbol, quantity, price, session=Session.NORMAL, duration=Duration.DAY, date_input=gtc_days_default):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    buy-to-cover limit order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.LIMIT)
            .set_price(price)
            .set_session(session)
            .set_duration(duration)
            .set_cancel_date(date_input, duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.BUY_TO_COVER, symbol, quantity))

def equity_buy_to_cover_stop(symbol, quantity, price, session=Session.NORMAL, duration=Duration.DAY, date_input=gtc_days_default):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    buy limit order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.STOP)
            .set_stop_price(price)
            .set_stop_type(StopType.STANDARD)
            .set_session(session)
            .set_duration(duration)
            .set_cancel_date(date_input, duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.BUY_TO_COVER, symbol, quantity))


def equity_buy_to_cover_trailing_stop(symbol, quantity, price_offset,
                             session=Session.NORMAL, duration=Duration.DAY, date_input=gtc_days_default,
                             stop_price_link_type=StopPriceLinkType.VALUE,
                             stop_price_link_basis=StopPriceLinkBasis.MARK,
                             stop_type=StopType.MARK
                             ):
    '''
    Returns a pre-filled :class:`~schwab.orders.generic.OrderBuilder` for an equity
    buy limit order.
    '''

    return (OrderBuilder()
            .set_order_type(OrderType.TRAILING_STOP)
            .set_stop_price_offset(price_offset)
            .set_price_link_type(stop_price_link_type)
            .set_stop_price_link_basis(stop_price_link_basis)
            .set_stop_type(stop_type)
            .set_session(session)
            .set_duration(duration)
            .set_cancel_date(date_input, duration)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.BUY_TO_COVER, symbol, quantity))
