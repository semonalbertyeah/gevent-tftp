# -*- coding:utf-8 -*-

import struct
from gevent.server import DatagramServer
from gevent import socket

from . import constants
from .logger import logger


class UdpServer(DatagramServer):
    """
        Tuned for TFTP server
    """
    def __init__(self, listener, handle=None, spawn='default', blksize=constants.DEFAULT_BLKSIZE):
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

        req_info = self.parse_request(data)
        if req_info:
            code, path, mode, options = req_info
            handler = self.get_hanlder(
                (self.host, self.port),
                peer, code, path, mode, 
                self._retries, self._timeout, 
                options
            )
            handler.run()


    @staticmethod
    def parse_request(data):
        '''
            parse WRQ/RRQ request.
            return:
                (code, path, mode, options)
                or
                None if no valid request
        '''
        code = struct.unpack('!H', data[:2])[0]
        if code not in (constants.OPCODE_RRQ, constants.OPCODE_WRQ):
            logger.warning(u"invalid request opcode: %d" % code)
            return None

        tokens = filter(
            bool, 
            data[2:].decode('latin-1').split(u'\x00')
        )

        if len(tokens) < 2 or len(tokens) % 2 != 0:
            logger.warning('malformed packet, not even number of tokens')
            return None

        path = tokens[0]
        mode = tokens[1].lower()

        options = {}
        pos = 2

        while pos < len(tokens):
            options[tokens[pos].lower()] = tokens[pos + 1]
            pos += 2

        return (code, path, mode, options)

    @property
    def host(self):
        return self._udp_server.server_host

    @property
    def port(self):
        return self._udp_server.server_port

    def serve(self):
        self._udp_server.serve_forever()


    def get_hanlder(self, server_addr, peer, code, path, mode, retries, timeout, options):
        """
            override this method to offer a handler.
            code: RRQ or WRQ
        """
        raise NotImplemented()

