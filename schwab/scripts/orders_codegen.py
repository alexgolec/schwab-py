import argparse
import httpx
import json

from schwab.auth import client_from_token_file
from schwab.contrib.orders import construct_repeat_order, code_for_builder


def latest_order_main(sys_args):
    parser = argparse.ArgumentParser(
            description='Utilities for generating code from historical orders')

    required = parser.add_argument_group('required arguments')
    required.add_argument(
            '--token_file', required=True, help='Path to token file')
    required.add_argument('--api_key', required=True)
    required.add_argument('--app_secret', required=True)

    account_spec_group = parser.add_mutually_exclusive_group()
    account_spec_group.add_argument('--account_id', type=int,
            help='Restrict lookups to a specific account ID')

    account_spec_group.add_argument('--account_hash', type=str,
            help='Restrict lookups to the account with the specified hash')

    args = parser.parse_args(args=sys_args)
    client = client_from_token_file(
            args.token_file, args.app_secret, args.api_key)

    # If the account ID is specified, find the corresponding account hash
    if args.account_id is not None:
        r = client.get_account_numbers()
        assert r.status_code == httpx.codes.OK

        for val in r.json():
            if val['accountNumber'] == str(args.account_id):
                account_hash = val['hashValue']
                break
        else:
            print(('Failed to find account has for account ID {}. Searched ' +
                   'the following accounts:\n{}').format(
                       args.account_id, json.dumps(r.json(), indent=4)))
            return -1
    else:
        account_hash = args.account_hash


    # Fetch orders
    def get_orders(method):
        r = method()
        if r.status_code != httpx.codes.OK:
            print(('Returned HTTP status code {}. This is most often caused ' +
                   'by an invalid account ID or hash.').format(r.status_code))
            return None
        return r.json()

    if account_hash is not None:
        orders = get_orders(lambda: client.get_orders_for_account(account_hash))
        if orders is None:
            return -1

        if 'error' in orders:
            print(('Schwab returned error: "{}", This is most often caused ' +
                   'by an invalid account ID or hash').format(orders['error']))
            return -1
    else:
        orders = get_orders(lambda: client.get_orders_for_all_linked_accounts())
        if orders is None:
            return -1

        if 'error' in orders:
            print('Schwab returned error: "{}"'.format(orders['error']))
            return -1

    # Construct and emit order code
    if orders:
        order = sorted(orders, key=lambda o: -o['orderId'])[0]

        # XXX: If necessary, warn about the jank around destinations
        emit_destination_warning_newline = False
        if ('requestedDestination' in order
                and order['requestedDestination'] != 'AUTO'):
            print(('# Warning: This order contains a non-"AUTO" value of ' +
                   '"requestedDestination" ("{}").').format(
                       order['requestedDestination']))
            print('#          This parameter appears to be broken in ' +
                  'the API, so it is omitted in this generated code.')
            emit_destination_warning_newline = True
        if ('destinationLinkName' in order
                and order['destinationLinkName'] != 'AutoRoute'):
            print(('# Warning: This order contains a non-"AutoRoute" value of ' +
                   '"destinationLinkName" ("{}").').format(
                           order['destinationLinkName']))
            print('           This parameter appears to be broken in the ' +
                  'API, so it is omitted in this generated code.''')
            emit_destination_warning_newline = True
        if emit_destination_warning_newline:
            print()

        print('# Order ID', order['orderId'])
        print(code_for_builder(construct_repeat_order(order)))
    else:
        print('No recent orders found')

    return 0
