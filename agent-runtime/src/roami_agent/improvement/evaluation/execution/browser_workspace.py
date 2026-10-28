"""A stable, container-local origin for static artifact browser checks."""

WORKSPACE_HTTP_SERVER = r"""import functools,http.server,threading
class WorkspacePreview(http.server.SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
preview=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(WorkspacePreview,directory='/workspace'))
threading.Thread(target=preview.serve_forever,daemon=True).start()
workspace_url='http://127.0.0.1:'+str(preview.server_port)+'/index.html'
"""
