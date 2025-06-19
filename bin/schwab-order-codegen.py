#!/usr/bin/env python
from schwab.scripts.orders_codegen import latest_order_main

# added main becaus it is a required entry point to make executable.
def main():
    import sys
    sys.exit(latest_order_main(sys.argv[1:]))


if __name__ == '__main__':
    main()