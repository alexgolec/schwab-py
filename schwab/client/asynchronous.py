from .base import BaseClient
from ..debug import register_redactions_from_response
from ..utils import LazyLog

def register_redactions_from_response(x):
    pass

import httpx2
import inspect
import json


class AsyncClient(BaseClient):

    async def close_async_session(self):
        await self.session.aclose()

    async def _revoke_token_request(self, refresh_token):
        transport_error = None
        try:
            response = await self.session.revoke_token(
                    self.base_url + '/v1/oauth/revoke', refresh_token,
                    token_type_hint='refresh_token')
        except httpx2.HTTPError:
            transport_error = self._token_revocation_transport_error()
        if transport_error is not None:
            raise transport_error
        ret = self._persist_token_revocation(response)
        if inspect.isawaitable(ret):
            # The token write function returned an awaitable; the async
            # client awaits it, mapping failures onto the same
            # persistence error as the synchronous path.
            persistence_error = None
            try:
                await ret
            except Exception:
                persistence_error = \
                        self._token_revocation_persistence_error()
            if persistence_error is not None:
                raise persistence_error

    async def _get_request(self, path, params):
        dest = self.base_url + path

        req_num = self._req_num()
        self.logger.debug('Req %s: GET to %s, params=%s',
                req_num, dest, LazyLog(lambda: json.dumps(params, indent=4)))

        resp = await self.session.get(dest, params=params)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp

    async def _post_request(self, path, data):
        dest = self.base_url + path

        req_num = self._req_num()
        self.logger.debug('Req %s: POST to %s, json=%s',
                req_num, dest, LazyLog(lambda: json.dumps(data, indent=4)))

        resp = await self.session.post(dest, json=data)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp

    async def _put_request(self, path, data):
        dest = self.base_url + path

        req_num = self._req_num()
        self.logger.debug('Req %s: PUT to %s, json=%s',
                req_num, dest, LazyLog(lambda: json.dumps(data, indent=4)))

        resp = await self.session.put(dest, json=data)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp

    async def _delete_request(self, path):
        dest = self.base_url + path

        req_num = self._req_num()
        self.logger.debug('Req %s: DELETE to %s', req_num, dest)

        resp = await self.session.delete(dest)
        self._log_response(resp, req_num)
        register_redactions_from_response(resp)
        return resp
