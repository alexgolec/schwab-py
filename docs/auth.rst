.. highlight:: python
.. py:module:: schwab.auth

.. _auth:

==================================
Authentication and Client Creation
==================================

By now, you should have followed the instructions in :ref:`getting_started` and 
are ready to start making API calls. Read this page to learn how to get over the 
last remaining hurdle: OAuth authentication.

Before we begin, however, note that this guide is meant to users who want to run 
applications on their own machines, without distributing them to others. If you 
plan on distributing your app, or if you plan on running it on a server and 
allowing access to other users, this login flow is not for you.


---------------
OAuth Refresher
---------------

*This section is purely for the curious. If you already understand OAuth (wow,
congrats) or if you don't care and just want to use this package as fast as
possible, feel free to skip this section. If you encounter any weird behavior, 
this section may help you understand what's going on.*

Webapp authentication is a complex beast. The OAuth protocol was created to 
allow applications to access one anothers' APIs securely and with the minimum 
level of trust possible. A full treatise on this topic is well beyond the scope
of this guide, but in order to alleviate some of the complexity that seems to 
surround this part of the API, let's give a quick explanation of how OAuth works 
in the context of Schwab's API.

The first thing to understand is that the OAuth webapp flow was created to allow 
client-side applications consisting of a webapp frontend and a remotely hosted 
backend to interact with a third party API. Unlike the `backend application flow
<https://requests-oauthlib.readthedocs.io/en/latest/oauth2_workflow.html
#backend-application-flow>`__, in which the remotely hosted backend has a secret 
which allows it to access the API on its own behalf, the webapp flow allows 
either the webapp frontend or the remotely host backend to access the API *on 
behalf of its users*.

If you've ever installed a GitHub, Facebook, Twitter, GMail, etc. app, you've 
seen this flow. You click on the "install" link, a login window pops up, you
enter your password, and you're presented with a page that asks whether you want 
to grant the app access to your account.

Here's what's happening behind the scenes: A pop-up window appears, which 
is the authentication URL, leading you to a login page specifically for the 
target API. The purpose here is to enable you to enter your username and 
password directly into the API's system, bypassing the web application's 
frontend and the remotely hosted backend. This process is secure on web 
browsers because they enforce a policy that prevents your login credentials 
from being sent to any domain other than the one you are currently interacting with.

Once login here is successful, the API replies with a redirect to a URL that the 
remotely hosted backend controls. This is the callback URL. This redirect will 
contain a code which securely identifies the user to the API, embedded in the 
query of the request.

You might think that code is enough to access the API, and it would be if the 
API author were willing to sacrifice long-term security. The exact reasons why 
it doesn't work involve some deep security topics like robustness against replay
attacks and session duration limitation, but we'll skip them here.

This code is useful only for fetching a token from the authentication endpoint.  
*This token* is what we want: a secure secret which the client can use to access 
API endpoints, and can be refreshed over time.

If you've gotten this far and your head isn't spinning, you haven't been paying 
attention. Security-sensitive protocols can be very complicated, and you should 
**never** build your own implementation. Fortunately there exist very robust 
implementations of this flow, and ``schwab-py``'s authentication module makes 
using them easy.


--------------------------------------
Fetching a Token and Creating a Client
--------------------------------------

``schwab-py`` provides an easy implementation of the client-side login flow in 
the ``auth`` package. It uses a `selenium 
<https://selenium-python.readthedocs.io/>`__ webdriver to open the Schwab
authentication URL, take your login credentials, catch the post-login redirect, 
and fetch a reusable token. It returns a fully-configured :ref:`client`, ready 
to send API calls. It also handles token refreshing, and writes updated tokens 
to the token file.

These functions are webdriver-agnostic, meaning you can use whatever 
webdriver-supported browser you have available on your system. You can find 
information about available webdriver on the `Selenium documentation
<https://www.selenium.dev/documentation/en/getting_started_with_webdriver/
browsers/>`__.

.. autofunction:: schwab.auth.client_from_login_flow

.. _manual_login:

If for some reason you cannot open a web browser, such as when running in a 
cloud environment, the following function will guide you through the process of 
manually creating a token by copy-pasting relevant URLs.

.. autofunction:: schwab.auth.client_from_manual_flow

Once you have a token written on disk, you can reuse it without going through 
the login flow again. 

.. autofunction:: schwab.auth.client_from_token_file

The following is a convenient wrapper around these two methods, calling each 
when appropriate: 

.. autofunction:: schwab.auth.easy_client

If you don't want to create a client and just want to fetch a token, you can use
the ``schwab-generate-token.py`` script that's installed with the library. This 
method is particularly useful if you want to create your token on one machine 
and use it on another. The script will attempt to open a web browser and perform 
the login flow. If it fails, it will fall back to the manual login flow: 

.. code-block:: bash

  # Notice we don't prefix this with "python" because this is a script that was 
  # installed by pip when you installed schwab-py
  > schwab-generate-token.py --help
  usage: schwab-generate-token.py [-h] --token_file TOKEN_FILE --api_key API_KEY 
  --redirect_uri REDIRECT_URI

  Fetch a new token and write it to a file

  optional arguments:
    -h, --help            show this help message and exit

  required arguments:
    --token_file TOKEN_FILE
                        Path to token file. Any existing file will be overwritten
    --api_key API_KEY
    --redirect_uri REDIRECT_URI


This script is installed by ``pip``, and will only be accessible if you've added
pip's executable locations to your ``$PATH``. If you're having a hard time, feel
free to ask for help on our `Discord server <https://discord.gg/BEr6y6Xqyv>`__.


----------------------
Advanced Functionality
----------------------

The default token fetcher functions are designed for ease of use. They make some 
common assumptions, most notably a writable filesystem, which are valid for 99% 
of users. However, some very specialized users, for instance those hoping to 
deploy ``schwab-py`` in serverless settings, require some more advanced 
functionality.  This method provides the most flexible facility for fetching 
tokens possible. 

**Important:** This is an extremely advanced method. If you read the 
documentation and think anything other than "oh wow, this is exactly what I've 
been looking for," you don't need this function. Please use the other helpers 
instead.

.. autofunction:: schwab.auth.client_from_access_functions

---------------
Troubleshooting
---------------

As simple as it seems, this process is complex and mistakes are easy to make. 
This section outlines some of the more common issues you might encounter. If you 
find yourself dealing with something that isn't listed here, or if you try the 
suggested remedies and are still seeing issues, see the :ref:`help` page. You 
can also `join our Discord server <https://discord.gg/M3vjtHj>`__ to ask questions.



.. _missing_chromedriver:

++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
``WebDriverException: Message: 'chromedriver' executable needs to be in PATH``
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

When creating a ``schwab-py`` token using a webrowser-based method like 
:func:`~schwab.auth.client_from_login_flow` or :func:`~schwab.auth.easy_client`, 
the library must control the browser using `selenium 
<https://selenium-python.readthedocs.io/>`__. This is a Python library that 
sends commands to the browser to perform operations like load pages, inject 
synthetic clicks, enter text, and so on. The component which is used to send 
these commands is called a *driver*. 

Drivers are generally not part of the standard web browser installation, meaning 
you must install them manually. If you're seeing this or a similar message, you 
probably haven't installed the appropriate webdriver. Drivers are 
available for most of the common web browsers, including `Chrome 
<https://chromedriver.chromium.org/getting-started/>`__, `Firefox 
<https://github.com/mozilla/geckodriver/releases>`__, and `Safari 
<https://developer.apple.com/documentation/webkit/testing_with_webdriver_in_safari>`__.  
Make sure you've installed the driver *before* attempting to create a token 
using ``schwab-py``.


.. _invalid_grant:


++++++++++++++++++++++
Token Parsing Failures
++++++++++++++++++++++

``schwab-py`` handles creating and refreshing tokens. Simply put, *the user 
should never create or modify the token file*. If you are experiencing parse 
errors when accessing the token file or getting exceptions when accessing it, 
it's probably because you created it yourself or modified it. If you're 
experiencing token parsing issues, remember that:

1. You should never create the token file yourself. If you don't already have a
   token, you should pass a nonexistent file path to 
   :func:`~schwab.auth.client_from_login_flow` or 
   :func:`~schwab.auth.easy_client`.  If the file already exists, these methods 
   assume it's a valid token file. If the file does not exist, they will go 
   through the login flow to create one.
2. You should never modify the token file. The token file is automatically 
   managed by ``schwab-py``, and modifying it will almost certainly break it.
3. You should never share the token file. If the token file is shared between 
   applications, one of them will beat the other to refreshing, locking the 
   slower one out of using ``schwab-py``.

If you didn't do any of this and are still seeing issues using a token file that 
you're confident is valid, please `file a ticket 
<https://github.com/alexgolec/schwab-py/issues>`__. Just remember, **never share 
your token file, not even with** ``schwab-py`` **developers**. Sharing the token
file is as dangerous as sharing your Schwab username and password. 


++++++++++++++++++++++++++++++
What If I Can't Use a Browser?
++++++++++++++++++++++++++++++

Launching a browser can be inconvenient in some situations, most notably in 
containerized applications running on a cloud provider. ``schwab-py`` supports 
two alternatives to creating tokens by opening a web browser. 

Firstly, the :ref:`manual login flow<manual_login>` flow allows you to go 
through the login flow on a different machine than the one on which 
``schwab-py`` is running. Instead of starting the web browser and automatically 
opening the relevant URLs, this flow allows you to manually copy-paste around 
the URLs. It's a little more cumbersome, but it has no dependency on selenium.

Alterately, you can take advantage of the fact that token files are portable. 
Once you create a token on one machine, such as one where you can open a web 
browser, you can easily copy that token file to another machine, such as your 
application in the cloud. However, make sure you don't use the same token on 
two machines. It is recommended to delete the token created on the 
browser-capable machine as soon as it is copied to its destination. 

