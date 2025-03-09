from authlib.integrations.httpx_client import AsyncOAuth2Client, OAuth2Client

import collections
import contextlib
import httpx
import json
import logging
import multiprocess
import os
import psutil
import queue
import sys
import time
import urllib
import urllib3
import warnings
import webbrowser

from schwab.client import AsyncClient, Client
from schwab.debug import register_redactions


TOKEN_ENDPOINT = 'https://api.schwabapi.com/v1/oauth/token'


def get_logger():
    return logging.getLogger(__name__)


def __make_update_token_func(token_path):
    def update_token(t, *args, **kwargs):
        get_logger().info('Updating token to file %s', token_path)

        with open(token_path, 'w') as f:
            json.dump(t, f)
    return update_token


def __token_loader(token_path):
    def load_token():
        get_logger().info('Loading token from file %s', token_path)

        with open(token_path, 'rb') as f:
            return json.load(f)
    return load_token


class TokenMetadata:
    '''
    Provides the functionality required to maintain and update our view of the
    token's metadata.
    '''
    def __init__(self, token, creation_timestamp, unwrapped_token_write_func):
        '''
        :param token: The token to wrap in metadata
        :param creation_timestamp: Timestamp at which this token was initially 
                                   created. Notably, this timestamp does not 
                                   change when the token is updated.
        :unwrapped_token_write_func: Function that accepts a non-metadata
                                     wrapped token and writes it to disk or 
                                     other persistent storage.
        '''

        self.creation_timestamp = creation_timestamp

        # The token write function is ultimately stored in the session. When we
        # get a new token we immediately wrap it in a new sesssion. We hold on
        # to the unwrapped token writer function to allow us to inject the
        # appropriate write function.
        self.unwrapped_token_write_func = unwrapped_token_write_func

        # The current token. Updated whenever the wrapped token update function 
        # is called.
        self.token = token

    @classmethod
    def from_loaded_token(cls, token, unwrapped_token_write_func):
        '''
        Returns a new ``TokenMetadata`` object extracted from the metadata of
        the loaded token object. If the token has a legacy format which contains
        no metadata, assign default values.
        '''
        if 'creation_timestamp' not in token:
            raise ValueError(
                    'WARNING: The token format has changed since this token '+
                    'was created. Please delete it and create a new one.')

        return TokenMetadata(
                token['token'],
                token['creation_timestamp'],
                unwrapped_token_write_func)

    def token_age(self):
        '''Returns the number of second elapsed since this token was initially 
        created.'''
        return int(time.time()) - self.creation_timestamp

    def wrapped_token_write_func(self):
        '''
        Returns a version of the unwrapped write function which wraps the token 
        in metadata and updates our view on the most recent token.
        '''
        def wrapped_token_write_func(token, *args, **kwargs):
            # If the write function is going to raise an exception, let it do so 
            # here before we update our reference to the current token.
            ret = self.unwrapped_token_write_func(
                self.wrap_token_in_metadata(token), *args, **kwargs)

            self.token = token

            return ret

        return wrapped_token_write_func

    def wrap_token_in_metadata(self, token):
        return {
            'creation_timestamp': self.creation_timestamp,
            'token': token,
        }


################################################################################
# client_from_login_flow


# This runs in a separate process and is invisible to coverage
def __run_client_from_login_flow_server(
        q, callback_port, callback_path):  # pragma: no cover
    '''Helper server for intercepting redirects to the callback URL. See
    client_from_login_flow for details.'''

    import flask

    app = flask.Flask(__name__)

    @app.route(callback_path)
    def handle_token():
        q.put(flask.request.url)
        return 'schwab-py callback received! You may now close this window/tab.'

    @app.route('/schwab-py-internal/status')
    def status():
        return 'running'

    if callback_port == 443:
        return

    # Wrap this call in some hackery to suppress the flask startup messages
    with open(os.devnull, 'w') as devnull:
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)

        old_stdout = sys.stdout
        sys.stdout = devnull
        app.run(port=callback_port, ssl_context='adhoc')
        sys.stdout = old_stdout


class RedirectTimeoutError(Exception):
    pass

class RedirectServerExitedError(Exception):
    pass

# Capture the real time.time so that we can use it in server initialization 
# while simultaneously mocking it in testing
__TIME_TIME = time.time

def client_from_login_flow(api_key, app_secret, callback_url, token_path,
                           asyncio=False, enforce_enums=False, 
                           token_write_func=None, callback_timeout=300.0,
                           interactive=True, requested_browser=None):
    '''
    Open a web browser to perform an OAuth webapp login flow and creates a 
    client wrapped around the resulting token. The client will be configured to 
    refresh the token as necessary, writing each updated version to 
    ``token_path``.

    .. _callback_url_advisory:

    **Important Note:** This method operates by starting an HTTP server on the 
    port specified in your callback URL. When you complete the Schwab login 
    flow, Schwab sends a request to the callback URL with the required login 
    data encoded in the request parameters. *Anyone who receives this request 
    can steal your token and act on your account as though they were you.*

    ``schwab-py`` takes your security seriously. As a result, we only allow
    ``127.0.0.1`` as a host. We *strongly* recommend using a port number higher 
    than ``1024``, as most operating systems require superuser privileges to listen 
    on ports below ``1024``, and some also require changes to system firewalls 
    to accept connections to those ports, even when the connections originate from
    the same machine. The vast majority of users should just use
    ``https://127.0.0.1:8182`` as a callback URL.

    Note in particular that specifying *no* port number is equivalent to 
    specifying port 443, which is the default port number for HTTPS. Your 
    operating system will likely refuse to open this port for you, and this 
    method will fail.

    If you want to use this method but haven't specified a compatible callback 
    URL, you must update your app's configuration on `Schwab's developer portal 
    <https://developer.schwab.com/>`__. Note making this change will likely 
    require app re-approval from Schwab, which typically takes a few days.

    :param api_key: Your Schwab application's app key.
    :param app_secret: Application secret provided upon :ref:`app approval 
                       <approved_pending>`.
    :param callback_url: Your Schwab application's callback URL. Note this must
                         *exactly* match the value you've entered in your
                         application configuration, otherwise login will fail
                         with a security error. Be sure to check case and 
                         trailing slashes. :ref:`See the above note for
                         important information about setting your callback URL.
                         <callback_url_advisory>`
    :param token_path: Path to which the new token will be written. If the token
                       file already exists, it will be overwritten with a new
                       one. Updated tokens will be written to this path as well.
    :param asyncio: If set to ``True``, this will enable async support allowing
                    the client to be used in an async environment. Defaults to
                    ``False``
    :param enforce_enums: Set it to ``False`` to disable the enum checks on ALL
                          the client methods. Only do it if you know you really
                          need it. For most users, it is advised to use enums
                          to avoid errors.
    :param token_write_func: Function that writes the token on update. Will be
                             called whenever the token is updated, such as when
                             it is refreshed. See the above-mentioned example 
                             for what parameters this method takes.
    :param callback_timeout: How long to wait for a callback from the server 
                             before giving up, in seconds. Wait forever if set
                             to zero or ``None``.
    :param interactive: Require user input before starting the browser.
    :param requested_browser: Name of the browser to attempt to open. This 
                              function uses the standard ``webbrowser`` library 
                              under the hood, so you can find a table of valid 
                              values
                              `here <https://docs.python.org/3/library/webbrowser.html#webbrowser.register>`__
    '''

    if callback_timeout is None:
        callback_timeout = 0
    if callback_timeout < 0:
        raise ValueError('callback_timeout must be positive')

    # Start the server
    parsed = urllib.parse.urlparse(callback_url)

    if parsed.hostname != '127.0.0.1':
        # TODO: document this error
        raise ValueError(
                ('Disallowed hostname {}. client_from_login_flow only allows '+
                 'callback URLs with hostname 127.0.0.1. See here for ' +
                 'more information: https://schwab-py.readthedocs.io/en/' +
                 'latest/auth.html#callback-url-advisory').format(
                     parsed.hostname))

    callback_port = parsed.port if parsed.port else 443
    callback_path = parsed.path if parsed.path else '/'

    output_queue = multiprocess.Queue()

    server = multiprocess.Process(
            target=__run_client_from_login_flow_server,
            args=(output_queue, callback_port, callback_path))

    # Context manager to kill the server upon completion
    @contextlib.contextmanager
    def callback_server():
        server.start()

        try:
            yield
        finally:
            try:
                psutil.Process(server.pid).kill()
            except psutil.NoSuchProcess:
                pass

    with callback_server():
        # Wait until the server successfully starts
        while True:
            # Check if the server is still alive
            if server.exitcode is not None:
                # TODO: document this error
                raise RedirectServerExitedError(
                        'Redirect server exited. Are you attempting to use a ' +
                        'callback URL without a port number specified?')

            import traceback

            # Attempt to send a request to the server
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                            'ignore',
                            category=urllib3.exceptions.InsecureRequestWarning)

                    resp = httpx.get(
                            'https://127.0.0.1:{}/schwab-py-internal/status'.format(
                                callback_port), verify=False)
                break
            except httpx.ConnectError as e:
                pass

            time.sleep(0.1)

        # Open the browser
        auth_context = get_auth_context(api_key, callback_url)

        print()
        print('***********************************************************************')
        print()
        print('This is the browser-assisted login and token creation flow for')
        print('schwab-py. This flow automatically opens the login page on your')
        print('browser, captures the resulting OAuth callback, and creates a token')
        print('using the result. The authorization URL is:')
        print()
        print('>>', auth_context.authorization_url)
        print()
        print('IMPORTANT: Your browser will give you a security warning about an')
        print('invalid certificate prior to issuing the redirect. This is because')
        print('schwab-py has started a server on your machine to receive the OAuth')
        print('redirect using a self-signed SSL certificate. You can ignore that')
        print('warning, but make sure to first check that the URL matches your')
        print('callback URL, ignoring URL parameters. As a reminder, your callback URL')
        print('is:')
        print()
        print('>>',callback_url)
        print()
        print('See here to learn more about self-signed SSL certificates:')
        print('https://schwab-py.readthedocs.io/en/latest/auth.html#ssl-errors')
        print()
        print('If you encounter any issues, see here for troubleshooting:')
        print('https://schwab-py.readthedocs.io/en/latest/auth.html#troubleshooting')
        print('***********************************************************************')
        print()

        if interactive:
            input('Press ENTER to open the browser. Note you can call ' +
                  'this method with interactive=False to skip this input.')

        controller = webbrowser.get(requested_browser)
        controller.open(auth_context.authorization_url)

        # Wait for a response
        now = __TIME_TIME()
        timeout_time = now + callback_timeout
        received_url = None
        while True:
            now = __TIME_TIME()
            if now >= timeout_time:
                if callback_timeout == 0:
                    # XXX: We're detecting a test environment here to avoid an 
                    #      infinite sleep. Surely there must be a better way to do 
                    #      this...
                    if __TIME_TIME != time.time:  # pragma: no cover
                        raise ValueError('endless wait requested')
                else:
                    break

            # Attempt to fetch from the queue
            try:
                received_url = output_queue.get(
                        timeout=min(timeout_time - now, 0.1))
                break
            except queue.Empty:
                pass

        if not received_url:
            raise RedirectTimeoutError(
                    'Timed out waiting for a post-authorization callback. You '+
                    'can set a longer timeout by passing a value of ' +
                    'callback_timeout to client_from_login_flow.')

        token_write_func = (
            __make_update_token_func(token_path) if token_write_func is None
            else token_write_func)

        return client_from_received_url(
                api_key, app_secret, auth_context, received_url, 
                token_write_func, asyncio, enforce_enums)


################################################################################
# client_from_token_path


def client_from_token_file(token_path, api_key, app_secret, asyncio=False,
                           enforce_enums=True):
    '''
    Returns a session from an existing token file. The session will perform
    an auth refresh as needed. It will also update the token on disk whenever
    appropriate.

    :param token_path: Path to an existing token. Updated tokens will be written
                       to this path. If you do not yet have a token, use
                       :func:`~schwab.auth.client_from_login_flow` or
                       :func:`~schwab.auth.easy_client` to create one.
    :param api_key: Your Schwab application's app key.
    :param app_secret: Application secret. Provided upon :ref:`app approval 
                       <approved_pending>`.
    :param asyncio: If set to ``True``, this will enable async support allowing
                    the client to be used in an async environment. Defaults to
                    ``False``
    :param enforce_enums: Set it to ``False`` to disable the enum checks on ALL
                          the client methods. Only do it if you know you really
                          need it. For most users, it is advised to use enums
                          to avoid errors.
    '''

    load = __token_loader(token_path)

    return client_from_access_functions(
        api_key, app_secret, load, __make_update_token_func(token_path),
        asyncio=asyncio, enforce_enums=enforce_enums)


################################################################################
# client_from_manual_flow


def client_from_manual_flow(api_key, app_secret, callback_url, token_path,
                            asyncio=False, token_write_func=None,
                            enforce_enums=True):
    '''
    Walks the user through performing an OAuth login flow by manually
    copy-pasting URLs, and returns a client wrapped around the resulting token.
    The client will be configured to refresh the token as necessary, writing
    each updated version to ``token_path``.

    :param api_key: Your Schwab application's app key.
    :param app_secret: Application secret provided upon :ref:`app approval 
                       <approved_pending>`.
    :param callback_url: Your Schwab application's callback URL. Note this must
                         *exactly* match the value you've entered in your
                         application configuration, otherwise login will fail
                         with a security error. Be sure to check case and 
                         trailing slashes.
    :param token_path: Path to which the new token will be written. If the token
                       file already exists, it will be overwritten with a new
                       one. Updated tokens will be written to this path as well.
    :param asyncio: If set to ``True``, this will enable async support allowing
                    the client to be used in an async environment. Defaults to
                    ``False``
    :param enforce_enums: Set it to ``False`` to disable the enum checks on ALL
                          the client methods. Only do it if you know you really
                          need it. For most users, it is advised to use enums
                          to avoid errors.
    '''
    get_logger().info('Creating new token with callback URL \'%s\' ' +
                       'and token path \'%s\'', callback_url, token_path)

    auth_context = get_auth_context(api_key, callback_url)

    print('\n**************************************************************\n')
    print('This is the manual login and token creation flow for schwab-py.')
    print('Please follow these instructions exactly:')
    print()
    print(' 1. Open the following link by copy-pasting it into the browser')
    print('    of your choice:')
    print()
    print('        ' + auth_context.authorization_url)
    print()
    print(' 2. Log in with your account credentials. You may be asked to')
    print('    perform two-factor authentication using text messaging or')
    print('    another method, as well as whether to trust the browser.')
    print()
    print(' 3. When asked whether to allow your app access to your account,')
    print('    select "Allow".')
    print()
    print(' 4. Your browser should be redirected to your callback URI. Copy')
    print('    the ENTIRE address, paste it into the following prompt, and press')
    print('    Enter/Return.')
    print()
    print('If you encounter any issues, see here for troubleshooting:')
    print('https://schwab-py.readthedocs.io/en/latest/auth.html#troubleshooting')
    print('\n**************************************************************\n')

    if callback_url.startswith('http://'):
        print(('WARNING: Your callback URL ({}) will transmit data over HTTP, ' +
               'which is a potentially severe security vulnerability. ' +
               'Please go to your app\'s configuration with Schwab ' +
               'and update your callback URL to begin with \'https\' ' +
               'to stop seeing this message.').format(callback_url))

    received_url = input('Redirect URL> ').strip()

    token_write_func = (
        __make_update_token_func(token_path) if token_write_func is None
        else token_write_func)

    return client_from_received_url(
            api_key, app_secret, auth_context, received_url, token_write_func, 
            asyncio, enforce_enums)


################################################################################
# client_from_access_functions


def client_from_access_functions(api_key, app_secret, token_read_func,
                                 token_write_func, asyncio=False,
                                 enforce_enums=True):
    '''
    Returns a session from an existing token file, using the accessor methods to
    read and write the token. This is an advanced method for users who do not
    have access to a standard writable filesystem, such as users of AWS Lambda
    and other serverless products who must persist token updates on
    non-filesystem places, such as S3. 99.9% of users should not use this
    function.

    Users are free to customize how they represent the token file. In theory,
    since they have direct access to the token, they can get creative about how
    they store it and fetch it. In practice, it is *highly* recommended to
    simply accept the token object and use ``json`` to serialize and
    deserialize it, without inspecting it in any way.

    Note the read and write methods must take particular arguments. Please see 
    `this example <https://github.com/alexgolec/schwab-py/tree/master/examples/
    client_from_access_functions.py>`__ for details.

    :param api_key: Your Schwab application's app key.
    :param app_secret: Application secret. Provided upon :ref:`app approval 
                       <approved_pending>`.
    :param token_read_func: Function that takes no arguments and returns a token
                            object.
    :param token_write_func: Function that writes the token on update. Will be
                             called whenever the token is updated, such as when
                             it is refreshed. See the above-mentioned example 
                             for what parameters this method takes.
    :param asyncio: If set to ``True``, this will enable async support allowing
                    the client to be used in an async environment. Defaults to
                    ``False``
    :param enforce_enums: Set it to ``False`` to disable the enum checks on ALL
                          the client methods. Only do it if you know you really
                          need it. For most users, it is advised to use enums
                          to avoid errors.
    '''
    token = token_read_func()

    # Extract metadata and unpack the token, if necessary
    metadata = TokenMetadata.from_loaded_token(token, token_write_func)
    token = metadata.token

    # Don't emit token details in debug logs
    register_redactions(token)

    wrapped_token_write_func = metadata.wrapped_token_write_func()

    if asyncio:
        async def oauth_client_update_token(t, *args, **kwargs):
            wrapped_token_write_func(t, *args, **kwargs)  # pragma: no cover
        session_class = AsyncOAuth2Client
        client_class = AsyncClient
    else:
        oauth_client_update_token = wrapped_token_write_func
        session_class = OAuth2Client
        client_class = Client

    return client_class(
        api_key,
        session_class(api_key,
                      client_secret=app_secret,
                      token=token,
                      token_endpoint=TOKEN_ENDPOINT,
                      update_token=oauth_client_update_token,
                      leeway=300),
        token_metadata=metadata,
        enforce_enums=enforce_enums)


################################################################################
# Tools for incorporating token generation into webapp workflows


AuthContext = collections.namedtuple(
        'AuthContext', ['callback_url', 'authorization_url', 'state'])

def get_auth_context(api_key, callback_url, state=None):
    oauth = OAuth2Client(api_key, redirect_uri=callback_url)
    authorization_url, state = oauth.create_authorization_url(
        'https://api.schwabapi.com/v1/oauth/authorize',
        state=state)

    return AuthContext(callback_url, authorization_url, state)


def client_from_received_url(
        api_key, app_secret, auth_context, received_url, token_write_func, 
        asyncio=False, enforce_enums=True):
    # XXX: The AuthContext must be serializable, which means the original 
    #      OAuth2Client created in get_auth_context cannot be passed around. 
    #      Instead, we reconstruct it here.
    oauth = OAuth2Client(api_key, redirect_uri=auth_context.callback_url)

    token = oauth.fetch_token(
        TOKEN_ENDPOINT,
        authorization_response=received_url,
        client_id=api_key, auth=(api_key, app_secret),
        state=auth_context.state)

    # Don't emit token details in debug logs
    register_redactions(token)

    # Set up token writing and perform the initial token write
    metadata_manager = TokenMetadata(token, int(time.time()), token_write_func)
    token_write_func = metadata_manager.wrapped_token_write_func()
    token_write_func(token)

    # The synchronous and asynchronous versions of the OAuth2Client are similar
    # enough that can mostly be used interchangeably. The one currently known
    # exception is the token update function: the synchronous version expects a
    # synchronous one, the asynchronous requires an async one. The
    # oauth_client_update_token variable will contain the appropriate one.
    if asyncio:
        async def oauth_client_update_token(t, *args, **kwargs):
            token_write_func(t, *args, **kwargs)  # pragma: no cover
        session_class = AsyncOAuth2Client
        client_class = AsyncClient
    else:
        oauth_client_update_token = token_write_func
        session_class = OAuth2Client
        client_class = Client

    # Return a new session configured to refresh credentials
    return client_class(
        api_key,
        session_class(api_key,
                      client_secret=app_secret,
                      token=token,
                      update_token=oauth_client_update_token,
                      leeway=300),
        token_metadata=metadata_manager, enforce_enums=enforce_enums)


################################################################################
# easy_client


# TODO: Figure out how to properly mock global objects in unittest. This hack 
# ensures that the _get_ipython variable is defined so that we can patch is 
# using module-level patching. This is safe in most contexts, but there are 
# circumstances where it gets weird like starting an ipython notebook after 
# schwab-py is loaded.
try:
    _get_ipython = get_ipython
except NameError:
    _get_ipython = None


def __running_in_notebook():
    # Google Colab
    if os.getenv('COLAB_RELEASE_TAG'):
        return True

    # ipython in notebook mode
    if _get_ipython is not None:
        shell = _get_ipython().__class__.__name__
        if shell == 'ZMQInteractiveShell':
            return True

    return False


def easy_client(api_key, app_secret, callback_url, token_path, asyncio=False, 
                enforce_enums=True, max_token_age=60*60*24*6.5,
                callback_timeout=300.0, interactive=True,
                requested_browser=None):
    '''
    Convenient wrapper around :func:`client_from_login_flow` and
    :func:`client_from_token_file`. If ``token_path`` exists, loads the token
    from it. Otherwise open a login flow to fetch a new token. Returns a client
    configured to refresh the token to ``token_path``.

    *Reminder:* You should never create the token file yourself or modify it in
    any way. If ``token_path`` refers to an existing file, this method will
    assume that file is valid token and will attempt to parse it.

    :param api_key: Your Schwab application's app key.
    :param app_secret: Application secret provided upon :ref:`app approval 
                       <approved_pending>`.
    :param callback_url: Your Schwab application's callback URL. Note this must
                         *exactly* match the value you've entered in your
                         application configuration, otherwise login will fail
                         with a security error. Be sure to check case and 
                         trailing slashes. :ref:`See the above note for
                         important information about setting your callback URL.
                         <callback_url_advisory>`
    :param token_path: Path to which the new token will be written. If the token
                       file already exists, it will be overwritten with a new
                       one. Updated tokens will be written to this path as well.
    :param asyncio: If set to ``True``, this will enable async support allowing
                    the client to be used in an async environment. Defaults to
                    ``False``
    :param enforce_enums: Set it to ``False`` to disable the enum checks on ALL
                          the client methods. Only do it if you know you really
                          need it. For most users, it is advised to use enums
                          to avoid errors.
    :param max_token_age: If the token is loaded from a file but is older than 
                          this age (in seconds), proactively delete it and 
                          create a new one. Assists with 
                          :ref:`token expiration <token_expiration>`. If set to 
                          None, never proactively delete the token.
    :param callback_timeout: See the corresponding parameter to 
                             :func:`client_from_login_flow 
                             <client_from_login_flow>`.
    :param interactive: See the corresponding parameter to 
                        :func:`client_from_login_flow 
                        <client_from_login_flow>`.
    :param requested_browser: See the corresponding parameter to 
                              :func:`client_from_login_flow 
                              <client_from_login_flow>`.
    '''
    if max_token_age is None:
        max_token_age = 0
    if max_token_age < 0:
        raise ValueError('max_token_age must be positive, zero, or None')

    logger = get_logger()

    c = None

    if os.path.isfile(token_path):
        c = client_from_token_file(token_path, api_key, app_secret,
                                   asyncio=asyncio,
                                   enforce_enums=enforce_enums)
        logger.info('Loaded token from file \'%s\'', token_path)

        if max_token_age > 0 and c.token_age() >= max_token_age:
            logger.info('token too old, proactively creating a new one')
            c = None

    # Return early on success
    if c is not None:
        return c

    # Detect whether we're running in a notebook
    if __running_in_notebook():
        c = client_from_manual_flow(api_key, app_secret, callback_url, 
                                    token_path, enforce_enums=enforce_enums)
        logger.info(
            'Returning client fetched using manual flow, writing' +
            'token to \'%s\'', token_path)
    else:
        c = client_from_login_flow(
            api_key, app_secret, callback_url, token_path, asyncio=asyncio,
            enforce_enums=enforce_enums, callback_timeout=callback_timeout,
            requested_browser=requested_browser, interactive=interactive)

        logger.info(
            'Returning client fetched using web browser, writing' +
            'token to \'%s\'', token_path)

    return c
