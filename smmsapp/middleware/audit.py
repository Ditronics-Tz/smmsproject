import threading

_thread_local = threading.local()

def get_current_request():
    return getattr(_thread_local, 'request', None)

class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_local.request = request
        response = self.get_response(request)
        # cleanup
        if hasattr(_thread_local, 'request'):
            delattr(_thread_local, 'request')
        return response
