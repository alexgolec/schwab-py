from .base import BaseClient
from ..utils import LazyLog
from ..debug import register_redactions_from_response

def register_redactions_from_response(x):
    pass

import httpx2
import inspect
import json


class Client(BaseClient):
    def _revoke_token_request(self, refresh_token):
        transport_error = None
        try:
            response = self.session.revoke_token(
                    self.base_url + '/v1/oauth/revoke', refresh_token,
                    token_type_hint='refresh_token')
        except httpx2.HTTPError:
            transport_error = self._token_revocation_transport_error()
        if transport_error is not None:
            raise transport_error
        ret = self._persist_token_revocation(response)
        if inspect.isawaitable(ret):
            # A coroutine write function slipped past construction-time
            # checks; a synchronous client cannot await the tombstone
            # write, so fail loudly rather than silently dropping it.
            if inspect.iscoroutine(ret):
                ret.close()
            raise TypeError(
                    'token_write_func must be a function accepting a '
                    'token object, not an awaitable function.')

    def _get_request(self, path, params):
        dest = self.base_url + path

        req_num = self._req_num()
        self.logger.debug('Req %s: GET to %s, params=%s',
                req_num, dest, LazyLog(lambda: json.dumps(params, indent=4)))

        resp = self.session.get(dest, params=params)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp

    def _post_request(self, path, data):
        dest = self.base_url + path

        req_num = self._req_num()
        self.logger.debug('Req %s: POST to %s, json=%s',
            req_num, dest, LazyLog(lambda: json.dumps(data, indent=4)))

        resp = self.session.post(dest, json=data)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp

    def _put_request(self, path, data):
        dest = self.base_url + path

        req_num = self._req_num()
        self.logger.debug('Req %s: PUT to %s, json=%s',
            req_num, dest, LazyLog(lambda: json.dumps(data, indent=4)))

        resp = self.session.put(dest, json=data)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp

    def _delete_request(self, path):
        dest = self.base_url + path

        req_num = self._req_num()
        self.logger.debug('Req %s: DELETE to %s'.format(req_num, dest))

        resp = self.session.delete(dest)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp
