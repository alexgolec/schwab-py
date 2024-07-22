``schwab-py``: A Charles Schwab API Wrapper
===========================================

.. image:: https://img.shields.io/discord/720378361880248621.svg?label=&logo=discord&logoColor=ffffff&color=7389D8&labelColor=6A7EC2
  :target: https://discord.gg/BEr6y6Xqyv

.. image:: 
   https://img.shields.io/endpoint.svg?url=https%3A%2F%2Fshieldsio-patreon.vercel.app%2Fapi%3Fusername%TDAAPI%26type%3Dpatrons&style=flat
  :target: https://patreon.com/TDAAPI

.. image:: https://readthedocs.org/projects/schwab-py/badge/?version=latest
  :target: https://schwab-py.readthedocs.io/en/latest/?badge=latest

.. image:: https://github.com/alexgolec/schwab-py/workflows/tests/badge.svg
  :target: https://github.com/alexgolec/schwab-py/actions?query=workflow%3Atests

.. image:: https://badge.fury.io/py/schwab-py.svg
  :target: https://badge.fury.io/py/schwab-py

.. image:: 
   http://codecov.io/github/alexgolec/schwab-py/coverage.svg?branch=master
  :target: http://codecov.io/github/alexgolec/schwab-py?branch=master

What is ``schwab-py``?
----------------------

``schwab-py`` is an unofficial wrapper around the Charles Schwab Consumer APIs.  
It strives to be as thin and unopinionated as possible, offering an elegant 
programmatic interface over each endpoint. Notable functionality includes:

* Login and authentication
* Quotes, fundamentals, and historical pricing data
* Options chains
* Streaming quotes and order book depth data
* Trades and trade management
* Account info

I used to use ``tda-api``, how do I migrate?
--------------------------------------------

Now that TDAmeritrade is no more, the old ``tda-api`` library will no longer 
work. Check out our `transition guide 
<https://schwab-py.readthedocs.io/en/latest/tda-transition.html>`__ for 
instructions on getting started.


How do I use ``schwab-py``?
---------------------------

For a full description of ``schwab-py``'s functionality, check out the 
`documentation <https://schwab-py.readthedocs.io/en/latest/>`__. Meawhile, 
here's a quick getting started guide:

Before you do anything, create an account and an application on the
`Charles Schwab developer site <https://developer.schwab.com/login>`__.
You'll receive an API key and app secret, which you can pass to this wrapper.  
You'll also want to take note of your callback URI, as the login flow requires 
it. You app must be approved by Schwab before you can use it (this can take 
several days).  You can find more detailed instructions `here 
<https://schwab-py.readthedocs.io/en/latest/getting-started.html>`__.

Next, install ``schwab-py``:

.. code-block:: python

  pip install schwab-py

You're good to go! To demonstrate, here's how you can authenticate and fetch
daily historical price data for the past twenty years:

.. code-block:: python

  from schwab import auth, client
  import json

  api_key = 'YOUR_API_KEY'
  app_secret = 'YOUR_APP_SECRET'
  callback_url = 'https://127.0.0.1:8182/'
  token_path = '/path/to/token.json'

  c = auth.easy_client(api_key, app_secret, callback_url, token_path)

  r = c.get_price_history_every_day('AAPL')
  r.raise_for_status()
  print(json.dumps(r.json(), indent=4))

Why should I use ``schwab-py``?
-------------------------------

``schwab-py`` was designed to provide a few important pieces of functionality:

1. **Safe Authentication**: Schwab's API supports OAuth authentication, but too 
   many people online end up rolling their own implementation of the OAuth 
   callback flow. This is both unnecessarily complex and dangerous.  
   ``schwab-py`` handles token fetch and refreshing for you.

2. **Minimal API Wrapping**: Unlike some other API wrappers, which build in lots 
   of logic and validation, ``schwab-py`` takes raw values and returns raw 
   responses, allowing you to interpret the complex API responses as you see 
   fit. Anything you can do with raw HTTP requests you can do with 
   ``schwab-py``, only more easily.

Why should I *not* use ``schwab-py``?
-------------------------------------

As excellent as Schwab's API is, there are a few popular features it does not 
offer: 

 * While Charles Schwab owns `thinkorswim (AKA TOS)
   <https://www.schwab.com/trading/thinkorswim/desktop>`__, this API is 
   unaffiliated with it. You can access and trade against the same accounts as 
   TOS, but some of TOS's functionality is not supported by ``schwab-py``
 * Paper trading is not supported
 * Historical options pricing data is not available. 

What else?
----------

We have a `Discord server <https://discord.gg/BEr6y6Xqyv>`__! You can join to 
get help using ``schwab-py`` or just to chat with interesting people.

Bug reports, suggestions, and patches are always welcome! Submit issues
`here <https://github.com/alexgolec/schwab-py/issues>`__ and pull requests
`here <https://github.com/alexgolec/schwab-py/pulls>`__.

``schwab-py`` is released under the
`MIT license <https://github.com/alexgolec/schwab-py/blob/master/LICENSE>`__.

**Disclaimer:** *schwab-py is an unofficial API wrapper. It is in no way 
endorsed by or affiliated with Charles Schwab or any associated organization.
Make sure to read and understand the terms of service of the underlying API 
before using this package. This authors accept no responsibility for any
damage that might stem from use of this package. See the LICENSE file for
more details.*

