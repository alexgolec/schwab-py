from .base import BaseClient
from ..debug import register_redactions_from_response
from ..utils import LazyLog

def register_redactions_from_response(x):
    pass

import httpx2
import json


class AsyncClient(BaseClient):

    async def close_async_session(self):
        await self.session.aclose()

    async def revoke(self):
        '''Permanently revoke this client's refresh token at Schwab via the
        OAuth 2.0 token revocation endpoint (:rfc:`7009`).

        On success (HTTP 200), replaces the stored token with a secretless
        revoked marker and returns ``None``. Calling this method again on the
        same client is a local no-op. Attempting to build a client directly
        from the marker raises
        :class:`~schwab.utils.TokenRevokedError`; ``easy_client`` starts a
        full authorization flow instead.

        This operation is irreversible. Use it when retiring or losing a
        credential, not as a way to refresh an access token. Note RFC 7009
        says an authorization server *should* also invalidate access tokens
        issued from the same grant when it supports that operation; whether
        Schwab does so should not be assumed.

        :raises TokenRevocationError: The request could not be sent, Schwab
            returned a status other than 200, the client has no usable
            refresh token or persistent metadata, or the revoked marker
            could not be stored. Inspect ``endpoint_answered``,
            ``status_code``, ``retryable``, and ``server_revoked``; the
            exception deliberately carries no credential-bearing request or
            response.
        '''
        refresh_token = self._token_revocation_refresh_token()
        if refresh_token is None:
            return None
        transport_error = None
        try:
            response = await self.session.revoke_token(
                    self._TOKEN_REVOKE_URL, refresh_token,
                    token_type_hint='refresh_token')
        except httpx2.HTTPError:
            transport_error = self._token_revocation_transport_error()
        if transport_error is not None:
            raise transport_error
        self._persist_token_revocation(response)

    async def _get_request(self, path, params):
        dest = 'https://api.schwabapi.com' + path

        req_num = self._req_num()
        self.logger.debug('Req %s: GET to %s, params=%s',
                req_num, dest, LazyLog(lambda: json.dumps(params, indent=4)))

        resp = await self.session.get(dest, params=params)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp

    async def _post_request(self, path, data):
        dest = 'https://api.schwabapi.com' + path

        req_num = self._req_num()
        self.logger.debug('Req %s: POST to %s, json=%s',
                req_num, dest, LazyLog(lambda: json.dumps(data, indent=4)))

        resp = await self.session.post(dest, json=data)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp

    async def _put_request(self, path, data):
        dest = 'https://api.schwabapi.com' + path

        req_num = self._req_num()
        self.logger.debug('Req %s: PUT to %s, json=%s',
                req_num, dest, LazyLog(lambda: json.dumps(data, indent=4)))

        resp = await self.session.put(dest, json=data)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp

    async def _delete_request(self, path):
        dest = 'https://api.schwabapi.com' + path

        req_num = self._req_num()
        self.logger.debug('Req %s: DELETE to %s', req_num, dest)

        resp = await self.session.delete(dest)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp
