"""
schwab-py: Unofficial API wrapper for the Schwab HTTP API

This package provides a set of tools and utilities for interacting with
the Charles Schwab API, including authentication, order placement,
streaming data, and more.

Modules:
    auth: Handles authentication with the Schwab API.
    client: Provides the main client interface for API interactions.
    debug: Offers debugging and logging utilities.
    orders: Contains order-related functionality.
    streaming: Manages real-time data streaming.
    utils: Provides various utility functions.
"""


from . import auth
from . import client
# from . import contrib
from . import debug
from . import orders
from . import streaming
from . import utils

from .version import version as __version__
