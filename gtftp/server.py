# -*- coding:utf-8 -*-

import struct
from gevent.server import DatagramServer
from gevent import socket

from .packet import *
from .logger import logger


class UdpServer(DatagramServer):
    """
        Tuned for TFTP server
    """
    def __init__(self, listener, handle=None, spawn='default', blksize=Data.DEFAULT_BLKSIZE):
        """
            extra parameters to DatagramServer:
                blksize -> receive block size
        """
        super(UdpServer, self).__init__(listener, handle=handle, spawn=spawn)
        self._blksize = int(blksize)

    def do_read(self):
        try:
            data, address = self._socket.recvfrom(self._blksize)
        except socket.error as err:
            if err.args[0] == socket.EWOULDBLOCK:
                return
            raise
        return data, address


class Server(object):
    def __init__(self, ip='0.0.0.0', port=69, retries=3, timeout=5, concurrency=None):
        spawner = 'default'
        self._retries = retries
        self._timeout = timeout
        if concurrency:
            # an integer -- a shortcut for ``gevent.pool.Pool(integer)``
            spawner = int(concurrency)

        self._udp_server = UdpServer((ip, port), handle=self.handle_request, spawn=spawner)


    def handle_request(self, data, peer):
        """
            This func is called in a new greenlet.
        """

        req = Request.parse(data)
        if req:
            handler = self.get_hanlder(
                req, (self.host, self.port), peer, 
                self._retries, self._timeout
            )
            handler.run()


    @property
    def host(self):
        return self._udp_server.server_host

    @property
    def port(self):
        return self._udp_server.server_port

    def serve(self):
        self._udp_server.serve_forever()


    def get_hanlder(self, req, server_addr, peer, retries, timeout):
        """
            override this method to offer a handler.
            input:
                req -> instance of gtftp.packet.Request
                servre_addr -> (host, port)
                peer -> (host, port)
                retries -> times of retranmission when timeout.
                timeout -> timeout of receiving packets.
        """
        raise NotImplemented()

