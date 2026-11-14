========================
Live Schwab API Tests
========================

The tests in this directory exercise ``schwab-py`` against the real Schwab
API. They are never run by CI or ``make test``. They must be invoked
manually, and they are interactive: you will complete a real Schwab login
in your browser when the suite starts.

----------------
Prerequisites
----------------

You need a Schwab developer application with:

* An API key and app secret
* A callback URL whose hostname is ``127.0.0.1``, registered in your app
  configuration on `Schwab's developer portal
  <https://developer.schwab.com/>`__

----------------
Configuration
----------------

Copy the credentials template and fill it in:

.. code-block:: shell

  cp livetests/schwab-credentials.env.template \
     livetests/schwab-credentials.env

``schwab-credentials.env`` is gitignored, so your credentials can never be
committed. Environment variables of the same names override the file
values, e.g. ``SCHWAB_API_KEY=... make test-live``. The suite *fails* if
required credentials are missing, so a broken configuration can never
masquerade as a passing run.

----------------
Running
----------------

.. code-block:: shell

  make test-live

This runs ``uv run pytest livetests -sv``. The ``-s`` is required: the
suite needs your keyboard input and shows you the login URL. When the
suite starts it will prompt you to press ENTER, open your browser on the
Schwab login page, and wait for you to log in. Schwab then redirects to
the local callback server the test started on this machine, and the token
is written to a temporary directory and deleted when the run finishes.

-------------------------
Reusing a token between runs
-------------------------

To avoid logging in on every run, point ``RETAINED_TOKEN_PATH`` at a
filename. The first run performs the browser login and writes the token
there; later runs load it until it expires, at which point you'll be asked
to log in again and the file is rewritten:

.. code-block:: shell

  RETAINED_TOKEN_PATH=~/.schwab-test-token.json make test-live

This can also be set in ``schwab-credentials.env``. Note the file contains
a live refresh token — it is *not* covered by this repo's gitignore rules,
so keep it outside the repository and treat it like a password.

.. warning::

  These tests use real credentials and create real tokens. Never commit
  your ``schwab-credentials.env`` file or paste token contents anywhere.
