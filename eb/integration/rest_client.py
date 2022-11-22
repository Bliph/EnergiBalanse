import json
import time
import requests
import random

# ########################################################################
# General REST Client
# Parameters:
#
class RESTClient():
    def __init__(self, host, port, protocol, logger, timeouts):
        self.host = host
        self.port = port
        self.protocol = protocol
        self.logger = logger
        self.timeout_get = timeouts.get('get')
        self.timeout_put = timeouts.get('put')
        self.timeout_post = timeouts.get('post')
        self.timeout_delete = timeouts.get('delete')

    def client_url(self, path = ''):
        return '{}://{}:{}{}'.format(self.protocol, self.host, self.port, path)

    def handover(self, message):
        path = message.get('path')
        headers = message.get('headers')
        method = message.get('method')
        payload = message.get('payload')
        parameters = message.get('parameters')

        return self._rest_json(path=path, headers=headers, httptype=method, message=payload, parameters=parameters)

    # ########################################################################
    # General REST GET
    # Parameters:
    #       path:       GET path
    #       element:    JSON element to extract from response JSON.
    #                   None returns the complete JSON as dict
    #
    def rest_get_json(self, path, headers, parameters=None, element=None):
        return self._rest_json(path, headers, httptype='GET', message=None, parameters=parameters, element=element)

    # ########################################################################
    # General REST PUT
    # Parameters:
    #       path:       PUT path
    #       message:    JSON data to put
    #       element:    JSON element to extract from response JSON.
    #                   None returns the complete JSON as dict
    #
    def rest_put_json(self, path, headers, message, parameters=None, element=None):
        return self._rest_json(path, headers, httptype='PUT', message=message, parameters=parameters, element=element)

    # ########################################################################
    # General REST POST
    # Parameters:
    #       path:       POST path
    #       message:    JSON data to post
    #       element:    JSON element to extract from response JSON.
    #                   None returns the complete JSON as dict
    #
    def rest_post_json(self, path, headers, message, parameters=None, element=None):
        return self._rest_json(path, headers, httptype='POST', message=message, parameters=parameters, element=element)

    # ########################################################################
    # General REST DELETE
    # Parameters:
    #       path:       DELETE path
    #       element:    JSON element to extract from response JSON.
    #                   None returns the complete JSON as dict
    #
    def rest_delete_json(self, path, headers, parameters=None, element=None):
        return self._rest_json(path, headers, httptype='DELETE', message=None, parameters=parameters, element=element)

    # ########################################################################
    # General REST
    # Parameters:
    #       path:       path
    #       httptype:   'GET', 'POST', 'DELETE'
    #       message:    JSON data to post
    #       element:    JSON element to extract from response JSON.
    #                   None returns the complete JSON as dict
    #
    def _rest_json(self, path, headers, httptype, message, parameters=None, element=None):

        res = None
        url = '{}://{}:{}{}'.format(self.protocol, self.host, self.port, path)
        unique_id = int(1000*random.random())
        ts_start = time.time()
        self.logger.debug('---> Outgoing REST ({}): {}'.format(unique_id, url))
        self.logger.debug('_rest_json(),url={},type={},message={},parameters={},jsonelement={}'.format(url, httptype, message, parameters, element)[:100]+'...')

        try:
            if httptype == 'GET':
                r = requests.get(url, params=parameters, headers=headers, timeout=self.timeout_get)
            elif httptype == 'PUT':
                r = requests.put(url, params=parameters, headers=headers, json=message, timeout=self.timeout_put)
            elif httptype == 'POST':
                r = requests.post(url, params=parameters, headers=headers, json=message, timeout=self.timeout_post)
            elif httptype == 'DELETE':
                r = requests.delete(url, params=parameters, headers=headers, timeout=self.timeout_delete)
            else:
                m = 'Unsupported REST call to client'
                self.logger.error(m)

            content_type = r.headers.get('content-type', 'text/plain')
            is_json = 'application/json' in content_type
            is_text = 'text/plain' in content_type or 'text/html' in content_type

            if r.ok:
                if element is None:
                    if is_json:
                        if len(r.text) > 0:
                            res = json.loads(r.text)
                        else:
                            res = {}
                    elif is_text:
                        res = r.text

                else:
                    res = json.loads(r.text).get(element)
            else:
                if is_json:
                    if len(r.text) > 0:
                        sub_message = json.loads(r.text)
                    else:
                        sub_message = r.text
                elif is_text:
                    sub_message = r.text
                else:
                    sub_message = '???'

                m = 'Unexpected response, status_code {}, message: {}'.format(r.status_code, sub_message)
                self.logger.error(m)

        except Exception as e:
            self.logger.error('Exception: {}'.format(e))

        self.logger.debug('<--- {} ms Outgoing REST ({}): {}'.format(int(1000*(time.time()-ts_start)), unique_id, url))

        return res
