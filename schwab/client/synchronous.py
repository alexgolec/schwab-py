from .base import BaseClient
from ..utils import LazyLog
from ..debug import register_redactions_from_response

def register_redactions_from_response(x):
    pass

import httpx
import json


class Client(BaseClient):
    def revoke(self):
        '''Revoke this client's refresh token server-side via Schwab's OAuth
        revocation endpoint (RFC 7009). Revoking the refresh token invalidates
        any access tokens issued from it, killing the credential everywhere
        rather than merely forgetting it locally.

        On a successful (2xx) response, the token metadata is marked as revoked
        and persisted via the same write function used for token refreshes.
        Subsequent attempts to load the token via :func:`easy_client` or
        :func:`client_from_token_file` will surface the revoked state.

        Returns the raw ``httpx`` response.
        '''
        from ..auth import REVOKE_URL

        refresh_token = self.token_metadata.token.get('refresh_token')
        if not refresh_token:
            raise ValueError(
                    'No refresh_token present on this client; nothing to '
                    'revoke.')

        resp = httpx.post(
                REVOKE_URL,
                data={'token': refresh_token,
                      'token_type_hint': 'refresh_token'},
                auth=(self.session.client_id, self.session.client_secret),
                timeout=30.0)

        if 200 <= resp.status_code < 300:
            self.token_metadata.mark_revoked()

        return resp

    def _get_request(self, path, params):
        dest = 'https://api.schwabapi.com' + path

        req_num = self._req_num()
        self.logger.debug('Req %s: GET to %s, params=%s',
                req_num, dest, LazyLog(lambda: json.dumps(params, indent=4)))

        resp = self.session.get(dest, params=params)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp

    def _post_request(self, path, data):
        dest = 'https://api.schwabapi.com' + path

        req_num = self._req_num()
        self.logger.debug('Req %s: POST to %s, json=%s',
            req_num, dest, LazyLog(lambda: json.dumps(data, indent=4)))

        resp = self.session.post(dest, json=data)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp

    def _put_request(self, path, data):
        dest = 'https://api.schwabapi.com' + path

        req_num = self._req_num()
        self.logger.debug('Req %s: PUT to %s, json=%s',
            req_num, dest, LazyLog(lambda: json.dumps(data, indent=4)))

        resp = self.session.put(dest, json=data)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp

    def _delete_request(self, path):
        dest = 'https://api.schwabapi.com' + path

        req_num = self._req_num()
        self.logger.debug('Req %s: DELETE to %s'.format(req_num, dest))

        resp = self.session.delete(dest)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp
