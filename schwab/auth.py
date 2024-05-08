##########################################################################
# Authentication Wrappers

from authlib.integrations.httpx_client import AsyncOAuth2Client, OAuth2Client
from prompt_toolkit import prompt

import json
import logging
import os
import sys
import time
import warnings

from schwab.client import AsyncClient, Client
from schwab.debug import register_redactions


TOKEN_ENDPOINT = 'https://api.schwabapi.com/v1/oauth/token'


def get_logger():
    return logging.getLogger(__name__)


def __update_token(token_path):
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
    def __init__(self, token, unwrapped_token_write_func):
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
        return TokenMetadata(token, unwrapped_token_write_func)

    def wrapped_token_write_func(self):
        '''
        Returns a version of the unwrapped write function which wraps the token 
        in metadata and updates our view on the most recent token.
        '''
        def wrapped_token_write_func(token, *args, **kwargs):
            # If the write function is going to raise an exception, let it do so 
            # here before we update our reference to the current token.
            ret = self.unwrapped_token_write_func(token, *args, **kwargs)

            self.token = token

            return ret

        return wrapped_token_write_func


def __fetch_and_register_token_from_redirect(
        oauth, redirected_url, api_key, app_secret, token_path,
        token_write_func, asyncio, enforce_enums=True):
    token = oauth.fetch_token(
        TOKEN_ENDPOINT,
        authorization_response=redirected_url,
        client_id=api_key, auth=(api_key, app_secret))

    # Don't emit token details in debug logs
    register_redactions(token)

    # Set up token writing and perform the initial token write
    update_token = (
        __update_token(token_path) if token_write_func is None
        else token_write_func)
    metadata_manager = TokenMetadata(token, update_token)
    update_token = metadata_manager.wrapped_token_write_func()
    update_token(token)

    # The synchronous and asynchronous versions of the OAuth2Client are similar
    # enough that can mostly be used interchangeably. The one currently known
    # exception is the token update function: the synchronous version expects a
    # synchronous one, the asynchronous requires an async one. The
    # oauth_client_update_token variable will contain the appropriate one.
    if asyncio:
        async def oauth_client_update_token(t, *args, **kwargs):
            update_token(t, *args, **kwargs)  # pragma: no cover
        session_class = AsyncOAuth2Client
        client_class = AsyncClient
    else:
        oauth_client_update_token = update_token
        session_class = OAuth2Client
        client_class = Client

    # Return a new session configured to refresh credentials
    return client_class(
        api_key,
        session_class(api_key,
                      client_secret=app_secret,
                      token=token,
                      update_token=oauth_client_update_token),
        token_metadata=metadata_manager, enforce_enums=enforce_enums)


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
        api_key, app_secret, load, __update_token(token_path), asyncio=asyncio,
        enforce_enums=enforce_enums)


def client_from_manual_flow(api_key, app_secret, callback_url, token_path,
                            asyncio=False, token_write_func=None,
                            enforce_enums=True):
    '''
    Walks the user through performing an OAuth login flow by manually
    copy-pasting URLs, and returns a client wrapped around the resulting token.
    The client will be configured to refresh the token as necessary, writing
    each updated version to ``token_path``.

    Note this method is more complicated and error prone, and should be avoided
    in favor of :func:`client_from_login_flow` wherever possible.

    :param api_key: Your Schwab application's app key.
    :param callback_url: Your Schwab application's callback URL. Note this must
                         *exactly* match the value you've entered in your
                         application configuration, otherwise login will fail
                         with a security error.
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

    oauth = OAuth2Client(api_key, redirect_uri=callback_url)
    authorization_url, state = oauth.create_authorization_url(
        'https://api.schwabapi.com/v1/oauth/authorize')

    print('\n**************************************************************\n')
    print('This is the manual login and token creation flow for schwab-py.')
    print('Please follow these instructions exactly:')
    print()
    print(' 1. Open the following link by copy-pasting it into the browser')
    print('    of your choice:')
    print()
    print('        ' + authorization_url)
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
               'Please go to your app\'s configuration with TDAmeritrade ' +
               'and update your callback URL to begin with \'https\' ' +
               'to stop seeing this message.').format(callback_url))

    redirected_url = prompt('Redirect URL> ').strip()

    return __fetch_and_register_token_from_redirect(
        oauth, redirected_url, api_key, app_secret, token_path, token_write_func,
        asyncio, enforce_enums=enforce_enums)


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
                      update_token=oauth_client_update_token),
        token_metadata=metadata,
        enforce_enums=enforce_enums)
