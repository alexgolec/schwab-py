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
