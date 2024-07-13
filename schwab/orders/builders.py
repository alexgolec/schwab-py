from .generic import OrderBuilder
from .common import OrderStrategyType


def one_cancels_other(order1, order2):
    '''
    If one of the orders is executed, immediately cancel the other.
    '''

    return (OrderBuilder()
            .set_order_strategy_type(OrderStrategyType.OCO)
            .add_child_order_strategy(order1)
            .add_child_order_strategy(order2))


def first_triggers_second(first_order, second_order):
    '''
    If ``first_order`` is executed, immediately place ``second_order``.
    '''

    return (first_order
            .set_order_strategy_type(OrderStrategyType.TRIGGER)
            .add_child_order_strategy(second_order))
