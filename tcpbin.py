#!/usr/bin/env python

MOTD_FILE='motd.txt'
LOG_DIR='logs'
LOG_VIEWER_PORT=8000
LOG_VIEWER_HTTPS=True
AUTHKEY='admin:password'
CERTFILE='cert.pem'
KEYFILE='privkey.pem'
ANON=False
FQDN='example.com'

import BaseHTTPServer
import SimpleHTTPServer
import base64


class AuthHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_AUTHHEAD(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm=\"Logs\"')
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        if self.server.authkey:
            if self.headers.getheader('Authorization') == None:
                self.do_AUTHHEAD()
                self.wfile.write('Unauthorized')
            elif self.headers.getheader('Authorization') == 'Basic ' + base64.b64encode(self.server.authkey):
                SimpleHTTPServer.SimpleHTTPRequestHandler.do_GET(self)
            else:
                self.do_AUTHHEAD()
                self.wfile.write('Unauthorized')
        else:
            SimpleHTTPServer.SimpleHTTPRequestHandler.do_GET(self)

    def translate_path(self, path):
        path = SimpleHTTPServer.SimpleHTTPRequestHandler.translate_path(self, path)
        relpath = os.path.relpath(path, os.getcwd())
        fullpath = os.path.join(self.server.LOG_DIR, relpath)
        return fullpath

class ViewerServer(BaseHTTPServer.HTTPServer):
    """The main server, you pass in base_path which is the path you want to serve requests from"""
    def __init__(self, server_address, authkey='', LOG_DIR='logs', ssl_settings = None):
        self.LOG_DIR = LOG_DIR
        self.authkey = authkey
        self.ssl_settings = ssl_settings
        BaseHTTPServer.HTTPServer.__init__(self, server_address, AuthHandler)
        if self.ssl_settings:
            self.socket = self.ssl_settings.wrap_socket(self.socket)

    def serve_forever(self,):
        socket_addr = self.socket.getsockname()
        print "Serving " + ('HTTPS' if self.ssl_settings else 'HTTP') + " on", socket_addr[0], "port", socket_addr[1], "..."
        BaseHTTPServer.HTTPServer.serve_forever(self)

    def start(self):
        t = threading.Thread(target=self.serve_forever)
        t.daemon = True
        t.start()


import socket
import threading
import struct, os, time,sys, traceback

class Tube(object):
    def __init__(self, _sock):
        self._sock = _sock
        self.buf = ''

    def readline(self):
        while True:
            i = self.buf.find('\n')
            if i >= 0:
                result, self.buf = self.buf[:i+1], self.buf[i+1:]
                return result
            else:
                result = self.read()
                if not result:
                    print 'EOF on readline'
                    return None
                self.buf += result

    def __getattr__(self,attr):
        return self._sock.__getattribute__(attr)

class SocketTube(Tube):
    def __init__(self, _sock):
        super(SocketTube, self).__init__(_sock)
        self.write = _sock.send

    def read(self):
        return self._sock.recv(1024)


class DumpingServer(object):
    def __init__(self, port, is_ssl, handler, LOG_DIR='logs', ssl_settings=None, anon=False):
        self.port = port
        self.handler = handler
        self.anon = anon
        self.ssl_settings = ssl_settings
        self.is_ssl = is_ssl
        self.LOG_DIR=LOG_DIR

    def serve_on(self):
        bindsocket = socket.socket()
        bindsocket.bind(('', self.port))
        bindsocket.listen(5)
        print 'Serving on port %d ...' % (self.port,)

        i = 0
        try:
            while True:
                newsocket, fromaddr = bindsocket.accept()
                newsocket.settimeout(300.0)
                threading.Thread(target=self.handle_client, args=(newsocket,fromaddr,i)).start()
                i += 1
        except KeyboardInterrupt:
            return

    def start(self):
        t1 = threading.Thread(target=self.serve_on)
        t1.daemon = True
        t1.start()
        return t1

    def handle_client(self, sock,addr,idx):
        from_addr, port = addr
        try:
            hostname = socket.gethostbyaddr(from_addr)[0]
        except:
            hostname = from_addr
        print 'New connection from %s:%s (%s)' % (hostname, port, from_addr)
        if self.anon:
            host = 'anon'
        else:
            host = '%s:%s' % (hostname, port)

        f = open(os.path.join(self.LOG_DIR, '%s_%d_%d_%s.txt' % (time.strftime('%s'), idx, self.port, host)), 'wb')
        try:
            sock.settimeout(600)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
            if self.is_ssl:
                wrapped_sock = Tube(self.ssl_settings.wrap_socket(sock))
            else:
                wrapped_sock = SocketTube(sock)

            self.handler(wrapped_sock, host, f).handle()
            wrapped_sock.close()
        except Exception as e:
            f.write(traceback.format_exc())
        f.flush()
        f.close()

class ConnectionHandler(object):
    def __init__(self, sock, host, f):
        self.sock =sock
        self.host=host
        self.f=f

    def recvline(self):
        l = self.sock.readline()
        if not l:
            return l
        self.f.flush()
        self.f.write(l)
        sys.stdout.write(self.host + ': ' + l)
        return l



import ssl


class SSLSettings(object):
    def __init__(self, CERTFILE, KEYFILE):
        self.CERTFILE = CERTFILE
        self.KEYFILE = KEYFILE

    def wrap_socket(self, sock):
        return ssl.wrap_socket(sock, certfile=self.CERTFILE, keyfile=self.KEYFILE, server_side=True)


SSLSETTINGS = SSLSettings(CERTFILE, KEYFILE)

class HttpHandler(ConnectionHandler):
    def handle(self):
        request = self.sock.read()
        while request:
            print(request)
            self.f.write(request)
            self.f.flush()
            request = self.sock.read()
        self.sock.write("HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

class SmtpHandler(ConnectionHandler):
    def handle(self):
        print self.host + ': RX begin >>>>'

        self.sock.send('220 ' + FQDN + ' ESMTP Postfix\r\n')
        self.recvline()
        self.sock.send('250 ' + FQDN + ', I am glad to meet you\r\n')

        while True:
            l = self.recvline()
            if l.startswith('DATA'):
                self.sock.send('354 End data with <CR><LF>.<CR><LF>\r\n')
                break
            if l.startswith('QUIT'):
                print self.host + ': Successfully RX <<<<'
                return
            self.sock.send('250 Ok\r\n')

        while True:
            l = self.recvline()
            if l == '.\r\n':
                break
        self.sock.send('250 Ok: queued as 12345\r\n')

        while True:
            l = self.recvline()
            if l.startswith('QUIT'):
                break
        print self.host + ': Successfully RX <<<<'

def main():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    if MOTD_FILE and os.path.isfile(MOTD_FILE): # motd
        import shutil
        shutil.copyfile(MOTD_FILE, os.path.join(LOG_DIR, MOTD_FILE))

    ViewerServer(('', LOG_VIEWER_PORT), AUTHKEY, LOG_DIR, SSLSETTINGS if LOG_VIEWER_HTTPS else None).start()
    DumpingServer(80, False, HttpHandler, LOG_DIR, None, ANON).start()
    DumpingServer(443, True, HttpHandler, LOG_DIR, SSLSETTINGS, ANON).start()
    DumpingServer(6969, False, HttpHandler, LOG_DIR, None, True).start()
    DumpingServer(6970, True, HttpHandler, LOG_DIR, SSLSETTINGS, True).start()
    DumpingServer(25, False, SmtpHandler, LOG_DIR, None, ANON).start()

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        sys.exit(0)

if __name__ == '__main__':
    main()

