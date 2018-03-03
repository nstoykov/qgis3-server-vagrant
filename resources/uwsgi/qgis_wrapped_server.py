# -*- coding: utf-8 -*-
"""
QGIS Server HTTP wrapper

This script launches a QGIS Server listening on port 8081 or on the port
specified on the environment variable QGIS_SERVER_PORT.
QGIS_SERVER_HOST (defaults to 127.0.0.1)

A XYZ map service is also available for multithreading testing:

  ?MAP=/path/to/projects.qgs&SERVICE=XYZ&X=1&Y=0&Z=1&LAYERS=world

Note that multi threading in QGIS server is not officially supported and
it is not supposed to work in any case

Set MULTITHREADING environment variable to 1 to activate.


For testing purposes, HTTP Basic can be enabled by setting the following
environment variables:

  * QGIS_SERVER_HTTP_BASIC_AUTH (default not set, set to anything to enable)
  * QGIS_SERVER_USERNAME (default ="username")
  * QGIS_SERVER_PASSWORD (default ="password")

PKI authentication with HTTPS can be enabled with:

  * QGIS_SERVER_PKI_CERTIFICATE (server certificate)
  * QGIS_SERVER_PKI_KEY (server private key)
  * QGIS_SERVER_PKI_AUTHORITY (root CA)
  * QGIS_SERVER_PKI_USERNAME (valid username)

 Sample run:

QGIS_SERVER_PKI_USERNAME=Gerardus QGIS_SERVER_PORT=47547 QGIS_SERVER_HOST=localhost \
    QGIS_SERVER_PKI_KEY=/home/$USER/dev/QGIS/tests/testdata/auth_system/certs_keys/localhost_ssl_key.pem \
    QGIS_SERVER_PKI_CERTIFICATE=/home/$USER/dev/QGIS/tests/testdata/auth_system/certs_keys/localhost_ssl_cert.pem \
    QGIS_SERVER_PKI_AUTHORITY=/home/$USER/dev/QGIS/tests/testdata/auth_system/certs_keys/chains_subissuer-issuer-root_issuer2-root2.pem \
    python3 /home/$USER/dev/QGIS/tests/src/python/qgis_wrapped_server.py

.. note:: This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.
"""

__author__ = 'Alessandro Pasotti'
__date__ = '05/15/2016'
__copyright__ = 'Copyright 2016, The QGIS Project'
# This will get replaced with a git SHA1 when you do a git archive
__revision__ = '$Format:%H$'


import os

# Needed on Qt 5 so that the serialization of XML is consistent among all executions
os.environ['QT_HASH_SEED'] = '1'

import sys
import signal
import ssl
import math
import urllib.parse
import importlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import threading

from qgis.core import QgsApplication, QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsMessageLog
from qgis.server import QgsServer, QgsServerRequest, QgsBufferServerRequest, QgsBufferServerResponse, QgsServerFilter

QGIS_SERVER_PORT = int(os.environ.get('QGIS_SERVER_PORT', '8081'))
QGIS_SERVER_HOST = os.environ.get('QGIS_SERVER_HOST', '127.0.0.1')
# PKI authentication
QGIS_SERVER_PKI_CERTIFICATE = os.environ.get('QGIS_SERVER_PKI_CERTIFICATE')
QGIS_SERVER_PKI_KEY = os.environ.get('QGIS_SERVER_PKI_KEY')
QGIS_SERVER_PKI_AUTHORITY = os.environ.get('QGIS_SERVER_PKI_AUTHORITY')
QGIS_SERVER_PKI_USERNAME = os.environ.get('QGIS_SERVER_PKI_USERNAME')

# Check if PKI - https is enabled
https = (QGIS_SERVER_PKI_CERTIFICATE is not None and
         os.path.isfile(QGIS_SERVER_PKI_CERTIFICATE) and
         QGIS_SERVER_PKI_KEY is not None and
         os.path.isfile(QGIS_SERVER_PKI_KEY) and
         QGIS_SERVER_PKI_AUTHORITY is not None and
         os.path.isfile(QGIS_SERVER_PKI_AUTHORITY) and
         QGIS_SERVER_PKI_USERNAME)


qgs_app = QgsApplication([], False)
qgs_server = QgsServer()



# Load plugins
if os.environ.get('QGIS_PLUGINPATH', False):
    plugindir = os.environ.get('QGIS_PLUGINPATH')
    sys.path.append(plugindir)
    # Magic mistery: without this, virtual QgsServerFilter instances are not wrapped
    iface = qgs_server.serverInterface()
    try:
        for modulename in [(a, b, c) for a, b, c in os.walk(plugindir)][0][1]:
            try:
                module = importlib.import_module(modulename)
                getattr(module, 'serverClassFactory')(iface)
                QgsMessageLog.logMessage('Python plugin %s loaded!' % modulename)
            except:
                QgsMessageLog.logMessage('Could not load Python plugin %s!' % modulename)
    except:
        QgsMessageLog.logMessage('No plugins found in %s!' % plugindir)



class Handler(BaseHTTPRequestHandler):

    def do_GET(self, post_body=None):
        # CGI vars:
        headers = {}
        for k, v in self.headers.items():
            headers['%s%s' % ('HTTP_' if not k.startswith('HTTP') else '', k.replace(' ', '-').replace('-', '_').replace(' ', '-').upper())] = v
        if not self.path.startswith('http'):
            self.path = "%s://%s:%s%s" % ('https' if https else 'http', QGIS_SERVER_HOST, self.server.server_port, self.path)
        request = QgsBufferServerRequest(self.path, (QgsServerRequest.PostMethod if post_body is not None else QgsServerRequest.GetMethod), headers, post_body)
        response = QgsBufferServerResponse()
        qgs_server.handleRequest(request, response)

        headers_dict = response.headers()
        try:
            self.send_response(int(headers_dict['Status'].split(' ')[0]))
        except:
            self.send_response(200)
        for k, v in headers_dict.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(response.body())
        return

    def do_POST(self):
        content_len = int(self.headers.get('content-length', 0))
        post_body = self.rfile.read(content_len)
        return self.do_GET(post_body)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    pass


if __name__ == '__main__':
    if os.environ.get('MULTITHREADING') == '1':
        server = ThreadedHTTPServer((QGIS_SERVER_HOST, QGIS_SERVER_PORT), Handler)
    else:
        server = HTTPServer((QGIS_SERVER_HOST, QGIS_SERVER_PORT), Handler)
    if https:
        server.socket = ssl.wrap_socket(server.socket,
                                        certfile=QGIS_SERVER_PKI_CERTIFICATE,
                                        keyfile=QGIS_SERVER_PKI_KEY,
                                        ca_certs=QGIS_SERVER_PKI_AUTHORITY,
                                        cert_reqs=ssl.CERT_REQUIRED,
                                        server_side=True,
                                        ssl_version=ssl.PROTOCOL_TLSv1)
    print('Starting server on %s://%s:%s, use <Ctrl-C> to stop' %
          ('https' if https else 'http', QGIS_SERVER_HOST, server.server_port), flush=True)

    def signal_handler(signal, frame):
        global qgs_app
        print("\nExiting QGIS...")
        qgs_app.exitQgis()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    server.serve_forever()
