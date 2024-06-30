.. _tda_transition:

===============================================
Transitioning from TDAmeritrade and ``tda-api``
===============================================

*Note: If you are reading this and you are not a former tda-api user, please 
see* :ref:`getting_started`.

As of May 13th, 2024, the underlying API that powered ``tda-api`` is no longer 
working. All former ``tda-api`` users must now transition to this ``schwab-py``.  
Fortunately, this library was heavy modeled on ``tda-api``, and so most users 
will find it a relatively smooth transition. However, there are some important 
differences. This page will explain them and provide guidance for adjusting.


+++++++++++++++++++++++++
You must create a new app
+++++++++++++++++++++++++

TDAmeritrade developer apps created for use with ``tda-api`` are not valid for 
use with ``schwab-py``. In order to use the new library, you must create a new 
app by following the instructions outlined in :ref:`getting_started`. Note a few 
important differences: 

*Application approval is no longer instant.* New apps must be approved by 
Schwab, and from the outside this process appears to be manual. Once you create 
your app, you can expect to linger in the "Approved - Pending" state for 
multiple days. Until your app status changes to "Ready For Use," you cannot do 
anything. If you encounter any issues, please check this first **before** you 
ask for help on our Discord server.

*localhost cannot be used as a callback URL.* You can still use your local 
machine, but you must enter ``127.0.0.1`` instead.

*Old tokens are invalid*. Once you create your first app, you cannot re-use your 
old that worked under ``tda-api``. You must delete that one and create a new 
one.


+++++++++++++++++++++++++++++++++
Tokens lifetimes are much shorter
+++++++++++++++++++++++++++++++++

When you create a token using ``tda-api``, you had up to ninety days before it 
would expire and require replacing. What's more, ``tda-api`` implemented a 
mechanism by which tokens could be refreshed beyond ninety days, meaning for 
most users tokens were effectively eternal. 

This is no longer the case. Schwab's documentation indicates that tokens are 
valid for only seven days, after which they must be deleted and regenerated 
using the login flow described above. There appears to be no equivalent 
mechanism to the one that allowed for indefinite token use.

If your code works during trading hours, we recommend making a habit of 
pre-emptively cycling your token on Sunday before the market opens so that you 
aren't surprised by an invalid token on Monday morning.

It's important to underscore: this is a constraint imposed and enforced by 
Schwab.  **The library authors have no control over this.** Please do not 
pollute our Discord server with requests to extend token lifecycles.


+++++++++++++++++++++++++++++++
Some endpoints are gone forever
+++++++++++++++++++++++++++++++

While most endpoints are have been carried over from the old API, some endpoints 
were not. In particular, saved orders and watchlists are not provided by Schwab.  
If did not export your saved orders and watchlists from TDAmeritrade before May 
10th, we're sorry, but we're pretty sure your data is gone. You're welcome to 
contact Schwab to confirm this. 

Again, **this is not a choice by the library authors.** Please do not go to our 
Discord server asking to recover your data or add this functionality.


+++++++++++++++++++++++++++++++++++++++++
Options symbols are formatted differently
+++++++++++++++++++++++++++++++++++++++++

Options symbols on Schwab use a different format than they did on TDAmeritrade.  
Code that manipulates them may need to be updated. ``schwab-py`` provides a 
:ref:`helper class<options_symbols>` to make parsing and generating options 
symbols easier.


++++++++++++++++++++++++++++++++++
Equity index symbols are different
++++++++++++++++++++++++++++++++++

TDAmeritrade used equity index symbols that ended in ``.X``. For instance, the 
symbol for the S&P 500 index used to be ``$SPX.X``. Now, these indices are 
referred to without that suffix, so S&P 500 is just ``$SPX``.


++++++++++++++++++++++++++++++++++++++++++++++
``schwab-py`` only supports python 3.10 and up
++++++++++++++++++++++++++++++++++++++++++++++

``schwab-py`` depends heavily on async/await syntax and libraries for both its 
functionality and development harnesses. The python ecosystem has been migrating 
from older, less elegant implementations of these concepts for years. At the 
time of ``tda-api``'s writing (early 2020), support for these features was still 
being evolving, and so the library was written with many concessions to the 
older style in mind. 

Fast forward to 2024, and the python ecosystem has pretty much fully 
transitioned to the async/await style. Since ``schwab-py`` is a brand-new 
library with no legacy users, the authors decided to shed all the old code and 
write it only modern style and libraries. This broke support for versions of 
python older than 3.10. 

If you attempt to ``pip install schwab-py`` on a python installation older than 
3.10, you will be greeted with something to the effect of ``Could not find a 
version that satisfies the requirement schwab-py``. You must install a newer 
version of python before you can use ``schwab-py``. We recommend using ``pyenv`` 
to manage your python installations.

Note further that this library will periodically shed support for obsolete 
versions of python, as outlined on `this page 
<https://devguide.python.org/versions/>`__.
