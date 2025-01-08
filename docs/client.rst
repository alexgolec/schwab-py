.. highlight:: python
.. py:module:: schwab.client


.. _client:

===========
HTTP Client
===========

A naive, unopinionated wrapper around the
`Schwab individual trader API 
<https://developer.schwab.com/products/trader-api--individual>`_. This
client provides access to all endpoints of the API in as easy and direct a way 
as possible.


**Do not attempt to use more than one Client object per token file, as
this will likely cause issues with the underlying OAuth2 session management**

.. code-block:: python

  from schwab.auth import client_from_manual_flow

  # Follow the instructions on the screen to authenticate your client.
  c = client_from_manual_flow(
          api_key='APIKEY',
          app_secret='APP_SECRET',
          callback_url='https://127.0.0.1',
          token_path='/tmp/token.json')

  resp = c.get_price_history_every_day('AAPL')
  assert resp.status_code == httpx.codes.OK
  history = resp.json()

Note we we create a new client using the ``auth`` package as described in
:ref:`auth`. Creating a client directly is possible, but not recommended.

+++++++++++++++++++
Asyncio Support
+++++++++++++++++++

An asynchronous variant is available through a keyword to the client
constructor. This allows for higher-performance API usage, at the cost
of slightly increased application complexity.

.. code-block:: python

  from schwab.auth import client_from_manual_flow

  async def main():
      c = easy_client(
              api_key='APIKEY',
              redirect_uri='https://localhost',
              token_path='/tmp/token.json',
              asyncio=True)

      resp = await c.get_price_history_every_day('AAPL')
      assert resp.status_code == httpx.codes.OK
      history = resp.json()

  if __name__ == '__main__':
      import asyncio
      loop = asyncio.get_event_loop()
      loop.run_until_complete(main())

+++++++++++++++++++
Calling Conventions
+++++++++++++++++++

Function parameters are categorized as either required or optional.  Required 
parameters are passed as positional arguments.  Optional parameters, are passed 
as keyword arguments. 

Parameters which have special values recognized by the API are 
represented by `Python enums <https://docs.python.org/3/library/enum.html>`_. 
This is because the API rejects requests which pass unrecognized values, and 
this enum wrapping is provided as a convenient mechanism to avoid consternation 
caused by accidentally passing an unrecognized value.

By default, passing values other than the required enums will raise a
``ValueError``. If you believe the API accepts a value that isn't supported 
here, you can use ``set_enforce_enums`` to disable this behavior at your own 
risk. If you *do* find a supported value that isn't listed here, please open an
issue describing it or submit a PR adding the new functionality.


+++++++++++++
Return Values
+++++++++++++

All methods return a response object generated under the hood by the
`HTTPX <https://www.python-httpx.org/quickstart/#response-content>`__ module. 
For a full listing of what's possible, read that module's documentation. Most if
not all users can simply use the following pattern:

.. code-block:: python

  r = client.some_endpoint()
  assert r.status_code == httpx.codes.OK, r.raise_for_status()
  data = r.json()

The API indicates errors using the response status code, and this pattern will 
raise the appropriate exception if the response is not a success. The data can 
be fetched by calling the ``.json()`` method. 

This data will be pure python data structures which can be directly accessed. 
You can also use your favorite data analysis library's dataframe format using 
the appropriate library. For instance you can create a `pandas
<https://pandas.pydata.org/>`__ dataframe using `its conversion method 
<https://pandas.pydata.org/pandas-docs/stable/reference/api/
pandas.DataFrame.from_dict.html>`__.

**Note:** Because the author has no relationship whatsoever with Charles Schwab,
this document makes no effort to describe the structure of the returned JSON 
objects. Schwab might change them at any time, at which point this document will 
become silently out of date. Instead, each of the methods described below 
contains a link to the official documentation. For endpoints that return 
meaningful JSON objects, it includes a JSON schema which describes the return 
value. Please use that documentation or your own experimentation when figuring 
out how to use the data returned by this API.


.. _account_hashes:

++++++++++++++
Account Hashes
++++++++++++++

Many methods of this API are parametrized by account. However, the API does not 
accept raw account numbers, but rather account hashes. You can fetch these 
hashes using the ``get_account_numbers`` method :ref:`(link) 
<account_hashes_method>`.  This method provides a mapping from raw account 
number to the account hash that must be passed when referring to that account in 
API calls.

Here is an example of how to fetch an account hash and use it to place an order:

.. code-block:: python

  import atexit
  import httpx
  from selenium import webdriver

  from schwab.auth import easy_client
  from schwab.orders.equities import equity_buy_market

  def make_webdriver():
      driver = webdriver.Firefox()
      atexit.register(lambda: driver.quit())
      return driver

  c = easy_client(
          token_path='/path/to/token.json',
          api_key='api-key',
          app_secret='app-secret',
          callback_url='https://callback.com',
          webdriver_func=make_webdriver)

  resp = c.get_account_numbers()
  assert resp.status_code == httpx.codes.OK

  # The response has the following structure. If you have multiple linked
  # accounts, you'll need to inspect this object to find the hash you want:
  # [
  #    {
  #        "accountNumber": "123456789",
  #        "hashValue":"123ABCXYZ"
  #    }
  #]
  account_hash = resp.json()[0]['hashValue']

  c.place_order(account_hash, equity_buy_market('AAPL', 1))



++++++++++++++++++
Timeout Management
++++++++++++++++++

Timeouts for HTTP calls are managed under the hood by the ``httpx`` library.  
``schwab-py`` defaults to 30 seconds, which experience has shown should be more 
than enough to allow even the slowest API calls to complete. A different timeout 
specification can be set using this method:

.. automethod:: schwab.client.Client.set_timeout


+++++++++
Token Age
+++++++++

.. automethod:: schwab.client.Client.token_age


++++++++++++
Account Info
++++++++++++

These methods provide access to useful information about accounts. An incomplete 
list of the most interesting bits:

* Account balances, including available trading balance
* Positions
* Order history

See the official documentation for each method for a complete response schema.

.. _account_hashes_method:

.. automethod:: schwab.client.Client.get_account_numbers
.. automethod:: schwab.client.Client.get_account
.. automethod:: schwab.client.Client.get_accounts
.. autoclass:: schwab.client.Client.Account
  :members:
  :undoc-members:


+++++++++++++
Price History
+++++++++++++

Schwab provides price history for equities and ETFs. It does not provide price 
history for options, futures, or any other instruments. 

In the raw API, fetching price history is somewhat complicated: the API offers a 
single endpoint :meth:`Client.get_price_history` that accepts a complex variety 
of inputs, but fails to document them in any meaningful way.

Thankfully, we've reverse engineered this endpoint and built some helpful 
utilities for fetching prices by minute, day, week, etc. Each method can be 
called with or without date bounds. When called without date bounds, it returns 
all data available. Each method offers a different lookback period, so make sure 
to read the documentation below to learn how much data is available. 


.. automethod:: schwab.client.Client.get_price_history_every_minute
.. automethod:: schwab.client.Client.get_price_history_every_five_minutes
.. automethod:: schwab.client.Client.get_price_history_every_ten_minutes
.. automethod:: schwab.client.Client.get_price_history_every_fifteen_minutes
.. automethod:: schwab.client.Client.get_price_history_every_thirty_minutes
.. automethod:: schwab.client.Client.get_price_history_every_day
.. automethod:: schwab.client.Client.get_price_history_every_week

For the sake of completeness, here is the documentation for the raw price 
history endpoint, in all its complexity.

.. automethod:: schwab.client.Client.get_price_history
.. autoclass:: schwab.client.Client.PriceHistory
  :members:
  :undoc-members:
  :member-order: bysource

.. _orders-section:

++++++++++++++
Current Quotes
++++++++++++++

.. automethod:: schwab.client.Client.get_quote
.. automethod:: schwab.client.Client.get_quotes

.. _option_chain:

+++++++++++++
Option Chains
+++++++++++++

Unfortunately, option chains are well beyond the ability of your humble author. 
You are encouraged to read the official API documentation to learn more.

If you *are* knowledgeable enough to write something more substantive here, 
please follow the instructions in :ref:`contributing` to send in a patch.

.. automethod:: schwab.client.Client.get_option_chain
.. autoclass:: schwab.client.Client.Options
  :members:
  :undoc-members:

+++++++++++++++++++++++++++++++++++++
Instrument Searching and Fundamentals
+++++++++++++++++++++++++++++++++++++

.. automethod:: schwab.client.Client.get_instruments
.. automethod:: schwab.client.Client.get_instrument_by_cusip
.. autoclass:: schwab.client.Client.Instrument
  :members:
  :undoc-members:

++++++
Orders
++++++


.. _placing_new_orders:

------------------
Placing New Orders
------------------

Placing new orders can be a complicated task. The :meth:`Client.place_order` 
method is used to create all orders, from equities to options. The precise order 
type is defined by a complex order spec. Schwab provides some `example order 
specs`_ to illustrate the process and provides a schema in the `place order 
documentation 
<https://developer.schwab.com/products/trader-api--individual/details/specifications/Retail%20Trader%20API%20Production>`__, 
but beyond that we're on our own.

``schwab-api`` includes some helpers, described in :ref:`order_templates`, which 
provide an incomplete utility for creating various order types. While it only 
scratches the surface of what's possible, we encourage you to use that module 
instead of creating your own order specs.

.. _`example order specs`: https://developer.schwab.com/products/trader-api--individual/details/documentation/Retail%20Trader%20API%20Production

.. automethod:: schwab.client.Client.place_order

.. _accessing_existing_orders:

-------------------------
Accessing Existing Orders
-------------------------

.. automethod:: schwab.client.Client.get_orders_for_account
.. automethod:: schwab.client.Client.get_orders_for_all_linked_accounts
.. automethod:: schwab.client.Client.get_order
.. autoclass:: schwab.client.Client.Order
  :members:
  :undoc-members:

-----------------------
Editing Existing Orders
-----------------------

Endpoints for canceling and replacing existing orders.

These endpoints require the order ID. Because the API does not return a JSON 
response when creating an order, the workflow for extracting this order ID is a 
little complicated.  You can fetch the order ID from the response to a 
:meth:`place_order <schwab.client.Client.place_order>` request using :ref:`this 
helper function <extract_order_id>`. Otherwise, see 
:ref:`accessing_existing_orders` to finding historical orders.

.. automethod:: schwab.client.Client.cancel_order
.. automethod:: schwab.client.Client.replace_order


+++++++++++++++
Other Endpoints
+++++++++++++++

Note If your account limited to delayed quotes, these quotes will also be 
delayed.

-------------------
Transaction History
-------------------

.. automethod:: schwab.client.Client.get_transaction
.. automethod:: schwab.client.Client.get_transactions
.. autoclass:: schwab.client.Client.Transactions
  :members:
  :undoc-members:

----------------
User Preferences
----------------

.. automethod:: schwab.client.Client.get_user_preferences

-------------
Market Movers
-------------

.. automethod:: schwab.client.Client.get_movers
.. autoclass:: schwab.client.Client.Movers
  :members:
  :undoc-members:


------------
Market Hours
------------

.. automethod:: schwab.client.Client.get_market_hours
.. autoclass:: schwab.client.Client.MarketHours
  :members:
  :undoc-members:

