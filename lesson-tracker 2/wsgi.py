"""Production WSGI entry point; run behind a managed HTTPS reverse proxy."""
import io
import json
from email.message import Message
from http import HTTPStatus
from server import Handler, initialize

initialize()

class WSGIHandler(Handler):
    def __init__(self, environ):
        self.path = environ.get('PATH_INFO', '/')
        if environ.get('QUERY_STRING'):
            self.path += '?' + environ['QUERY_STRING']
        self.command = environ.get('REQUEST_METHOD', 'GET')
        self.headers = Message()
        for key, value in environ.items():
            if key.startswith('HTTP_'):
                self.headers[key[5:].replace('_', '-')] = str(value)
        for key in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            if environ.get(key):
                self.headers[key.replace('_', '-')] = str(environ[key])
        self.rfile = environ['wsgi.input']
        self.wfile = io.BytesIO()
        self.client_address = (environ.get('REMOTE_ADDR', 'unknown'), 0)
        self.status_code = 500
        self.result_headers = []

    def send_response(self, code, message=None):
        self.status_code = code

    def send_header(self, keyword, value):
        self.result_headers.append((keyword, value))

    def end_headers(self):
        pass

def application(environ, start_response):
    handler = WSGIHandler(environ)
    try:
        if handler.command in ('GET', 'HEAD'):
            handler.do_GET()
        elif handler.command == 'POST':
            handler.do_POST()
        else:
            handler.response(405, {'error': '不支持此请求方式。'})
    except Exception:
        payload = json.dumps({'error': '暂时无法连接，请稍后重试。'}, ensure_ascii=False).encode()
        start_response('500 Internal Server Error', [('Content-Type','application/json; charset=utf-8'),('Content-Length',str(len(payload))),('Cache-Control','no-store')])
        return [payload]
    start_response(f'{handler.status_code} {HTTPStatus(handler.status_code).phrase}', handler.result_headers)
    return [b'' if handler.command == 'HEAD' else handler.wfile.getvalue()]
