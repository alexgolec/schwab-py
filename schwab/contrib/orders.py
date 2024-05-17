import autopep8
import schwab

from schwab.orders.generic import OrderBuilder
from schwab.orders.common import (
        EquityInstrument,
        OptionInstrument,
        OrderStrategyType,
)

from collections import defaultdict


def _call_setters_with_values(order, builder):
    '''
    For each field in fields_and_setters, if it exists as a key in the order
    object, pass its value to the appropriate setter on the order builder.
    '''
    for field_name, setter_name, enum_class in _FIELDS_AND_SETTERS:
        try:
            value = order[field_name]
        except KeyError:
            continue

        if enum_class:
            value = enum_class[value]

        setter = getattr(builder, setter_name)
        setter(value)


# Top-level fields
_FIELDS_AND_SETTERS = (
    ('session', 'set_session', schwab.orders.common.Session),
    ('duration', 'set_duration', schwab.orders.common.Duration),
    ('orderType', 'set_order_type', schwab.orders.common.OrderType),
    ('complexOrderStrategyType', 'set_complex_order_strategy_type',
        schwab.orders.common.ComplexOrderStrategyType),
    ('quantity', 'set_quantity', None),
    # XXX: Destinations are weird/busted
    #       * As of 2024-05-16, the example in the place_order documentation 
    #         references destinationLinkName but not requestedDestination.
    #       * The same documentation lists requestedDestination as a parameter 
    #         to the method, but doesn't list destinationLinkName.
    #       * Fetching historical orders returns orders which contain both.
    #      These parameters are being ignored until we gain more clarity.
    #('destinationLinkName', 'set_destination_link_name',
    #    schwab.orders.common.Destination),
    ('stopPrice', 'copy_stop_price', None),
    ('stopPriceLinkBasis', 'set_stop_price_link_basis',
        schwab.orders.common.StopPriceLinkBasis),
    ('stopPriceLinkType', 'set_stop_price_link_type',
        schwab.orders.common.StopPriceLinkType),
    ('stopPriceOffset', 'set_stop_price_offset', None),
    ('stopType', 'set_stop_type', schwab.orders.common.StopType),
    ('priceLinkBasis', 'set_price_link_basis',
        schwab.orders.common.PriceLinkBasis),
    ('priceLinkType', 'set_price_link_type',
        schwab.orders.common.PriceLinkType),
    ('price', 'copy_price', None),
    ('activationPrice', 'set_activation_price', None),
    ('specialInstruction', 'set_special_instruction',
        schwab.orders.common.SpecialInstruction),
    ('orderStrategyType', 'set_order_strategy_type',
        schwab.orders.common.OrderStrategyType),
)

def construct_repeat_order(historical_order):
    builder = schwab.orders.generic.OrderBuilder()

    # Top-level fields
    _call_setters_with_values(historical_order, builder)

    # Composite orders
    if 'orderStrategyType' in historical_order:
        if historical_order['orderStrategyType'] == 'TRIGGER':
            builder = schwab.orders.common.first_triggers_second(
                    builder, construct_repeat_order(
                        historical_order['childOrderStrategies'][0]))
        elif historical_order['orderStrategyType'] == 'OCO':
            builder = schwab.orders.common.one_cancels_other(
                    construct_repeat_order(
                        historical_order['childOrderStrategies'][0]),
                    construct_repeat_order(
                        historical_order['childOrderStrategies'][1]))
    else:
        raise ValueError('historical order is missing orderStrategyType')

    # Order legs
    if 'orderLegCollection' in historical_order:
        for leg in historical_order['orderLegCollection']:
            if leg['orderLegType'] == 'EQUITY':
                builder.add_equity_leg(
                        schwab.orders.common.EquityInstruction[leg['instruction']],
                        leg['instrument']['symbol'],
                        leg['quantity'])
            elif leg['orderLegType'] == 'OPTION':
                builder.add_option_leg(
                        schwab.orders.common.OptionInstruction[leg['instruction']],
                        leg['instrument']['symbol'],
                        leg['quantity'])
            else:
                raise ValueError(
                        'unknown orderLegType {}'.format(leg['orderLegType']))

    return builder


################################################################################
# AST generation


def code_for_builder(builder, var_name=None):
    '''
    Returns code that can be executed to construct the given builder, including
    import statements.

    :param builder: :class:`~schwab.orders.generic.OrderBuilder` to generate.
    :param var_name: If set, emit code that assigns the builder to a variable
                     with this name.
    '''
    ast = construct_order_ast(builder)

    imports = defaultdict(set)
    lines = []
    ast.render(imports, lines)

    import_lines = []
    for module, names in imports.items():
        line = 'from {} import {}'.format(
                module, ', '.join(names))
        if len(line) > 80:
            line = 'from {} import (\n{}\n)'.format(
                    module, ',\n'.join(names))
        import_lines.append(line)

    if var_name:
        var_prefix = f'{var_name} = '
    else:
        var_prefix = ''

    return autopep8.fix_code(
            '\n'.join(import_lines) + 
            '\n\n' +
            var_prefix +
            '\n'.join(lines))


class FirstTriggersSecondAST:
    def __init__(self, first, second):
        self.first = first
        self.second = second

    def render(self, imports, lines, paren_depth=0):
        imports['schwab.orders.common'].add('first_triggers_second')

        lines.append('first_triggers_second(')
        self.first.render(imports, lines, paren_depth + 1)
        lines[-1] += ','
        self.second.render(imports, lines, paren_depth + 2)
        lines.append(')')


class OneCancelsOtherAST:
    def __init__(self, one, other):
        self.one = one
        self.other = other

    def render(self, imports, lines, paren_depth=0):
        imports['schwab.orders.common'].add('one_cancels_other')

        lines.append('one_cancels_other(')
        self.one.render(imports, lines, paren_depth + 1)
        lines[-1] += ','
        self.other.render(imports, lines, paren_depth + 2)
        lines.append(')')


class FieldAST:
    def __init__(self, setter_name, enum_type, value):
        self.setter_name = setter_name
        self.enum_type = enum_type
        self.value = value

    def render(self, imports, lines, paren_depth=0):
        value = self.value
        if self.enum_type:
            imports[self.enum_type.__module__].add(self.enum_type.__qualname__)
            value = self.enum_type.__qualname__ + '.' + value

        lines.append(f'.{self.setter_name}({value})')


class EquityOrderLegAST:
    def __init__(self, instruction, symbol, quantity):
        self.instruction = instruction
        self.symbol = symbol
        self.quantity = quantity

    def render(self, imports, lines, paren_depth=0):
        imports['schwab.orders.common'].add('EquityInstruction')
        lines.append('.add_equity_leg(EquityInstruction.{}, "{}", {})'.format(
            self.instruction, self.symbol, self.quantity))


class OptionOrderLegAST:
    def __init__(self, instruction, symbol, quantity):
        self.instruction = instruction
        self.symbol = symbol
        self.quantity = quantity

    def render(self, imports, lines, paren_depth=0):
        imports['schwab.orders.common'].add('OptionInstruction')
        lines.append('.add_option_leg(OptionInstruction.{}, "{}", {})'.format(
            self.instruction, self.symbol, self.quantity))


class GenericBuilderAST:
    def __init__(self, builder):
        self.top_level_fields = []
        for name, setter, enum_type in sorted(_FIELDS_AND_SETTERS):
            value = getattr(builder, '_'+name)
            if value is not None:
                self.top_level_fields.append(FieldAST(setter, enum_type, value))

        for leg in builder._orderLegCollection:
            if leg['instrument']._assetType == 'EQUITY':
                self.top_level_fields.append(EquityOrderLegAST(
                    leg['instruction'], leg['instrument']._symbol, 
                    leg['quantity']))
            elif leg['instrument']._assetType == 'OPTION':
                self.top_level_fields.append(OptionOrderLegAST(
                    leg['instruction'], leg['instrument']._symbol, 
                    leg['quantity']))
            else:
                raise ValueError('unknown leg asset type {}'.format(
                    leg['instrument']._assetType))

    def render(self, imports, lines, paren_depth=0):
        imports['schwab.orders.generic'].add('OrderBuilder')

        lines.append('OrderBuilder() \\')
        for idx, field in enumerate(self.top_level_fields):
            field.render(imports, lines, paren_depth)

            if paren_depth == 0 and idx != len(self.top_level_fields) - 1:
                lines[-1] += ' \\'


def construct_order_ast(builder):
    if builder._orderStrategyType == 'OCO':
        return OneCancelsOtherAST(
                construct_order_ast(builder._childOrderStrategies[0]),
                construct_order_ast(builder._childOrderStrategies[1]))
    elif builder._orderStrategyType == 'TRIGGER':
        return FirstTriggersSecondAST(
                GenericBuilderAST(builder),
                construct_order_ast(builder._childOrderStrategies[0]))
    else:
        return GenericBuilderAST(builder)
