import os

bind = '0.0.0.0:' + os.environ.get('PORT', '10000')
workers = 1
worker_class = 'gthread'
threads = 4
timeout = 30
graceful_timeout = 30
limit_request_line = 4094
limit_request_fields = 50
limit_request_field_size = 4096
accesslog = None  # Avoid logging query strings or account identifiers.
errorlog = '-'
