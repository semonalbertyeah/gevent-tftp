# Usage example

```python
import os
import io

from gtftp.server import Server
from gtftp.handler import BaseReadHandler, BaseWriteHandler, Target
from gtftp.packet import *


class LocalFileTarget(Target):
    def __init__(self, path, mode=u'rb'):
        self._target = open(path, mode)
        self._size = os.stat(path).st_size

    def read(self, n):
        return self._target.read(n)

    def write(self, data):
        self._target.write(data)

    def size(self):
        return self._size

    def close(self):
        self._target.close()


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


class StaticReadHandler(BaseReadHandler):
    def __init__(self, req, server_addr, peer, retries, timeout, root):
        self._root = root

        super(StaticReadHandler, self).__init__(req, server_addr, peer, retries, timeout)

    def get_target(self, path):
        return LocalFileTarget(os.path.join(self._root, path), u'rb')


class StaticWriteHandler(BaseWriteHandler):
    def __init__(self, req, server_addr, peer, retries, timeout, root):
        self._root = root

        super(StaticWriteHandler, self).__init__(req, server_addr, peer, retries, timeout)

    def get_target(self, path):
        return LocalFileTarget(os.path.join(self._root, path), u'wb+')


class StaticServer(Server):
    def __init__(self, ip='0.0.0.0', port=69, retries=3, timeout=5, concurrency=None, root='.'):
        self._root = os.path.abspath(root)
        super(StaticServer, self).__init__(ip, port, retries, timeout, concurrency)


    def get_hanlder(self, req, server_addr, peer, retries, timeout):
        if req.opcode == Packet.OPCODE_RRQ:
            return StaticReadHandler(req, server_addr, peer, retries, timeout, self._root)
        elif req.opcode == Packet.OPCODE_WRQ:
            return StaticWriteHandler(req, server_addr, peer, retries, timeout, self._root)
        else:
            raise Exception(u"do not handle WRQ")


if __name__ == '__main__':
    server = StaticServer()
    server.serve()


```