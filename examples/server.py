# -*- coding: utf-8 -*-

import os
import io

from gtftp.server import Server
from gtftp.handler import BaseReadHandler, Target
from gtftp.packet import *


class FileResponseData(Target):
    def __init__(self, path):
        self._size = os.stat(path).st_size
        self._reader = open(path, 'rb')

    def read(self, n):
        return self._reader.read(n)

    def size(self):
        return self._size

    def close(self):
        self._reader.close()


class StringResponseData(Target):
    def __init__(self, path):
        if not isinstance(path, unicode):
            path = str(path).decode('utf-8')

        content = (path + u"\n") * 30
        self._size = len(content)
        self._io = io.StringIO(content)

    def read(self, n):
        return self._io.read(n)

    def size(self):
        return self._size

    def close(self):
        self._io.close()


class StaticHandler(BaseReadHandler):
    def __init__(self, req, server_addr, peer, retries, timeout, root):
        self._root = root

        super(StaticHandler, self).__init__(req, server_addr, peer, retries, timeout)

    def get_target(self, path):
        return FileResponseData(os.path.join(self._root, path))
        # return StringResponseData(os.path.join(self._root, path))


class StaticServer(Server):
    def __init__(self, ip='0.0.0.0', port=69, retries=3, timeout=5, concurrency=None, root='.'):
        self._root = os.path.abspath(root)
        super(StaticServer, self).__init__(ip, port, retries, timeout, concurrency)


    def get_hanlder(self, req, server_addr, peer, retries, timeout):
        if req.opcode == Packet.OPCODE_RRQ:
            return StaticHandler(req, server_addr, peer, retries, timeout, self._root)
        else:
            raise Exception(u"do not handle WRQ")


if __name__ == '__main__':
    server = StaticServer()
    server.serve()

