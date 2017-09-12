import os

from gtftp.server import Server
from gtftp.handler import BaseReadHandler, Target
from gtftp import constants


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

class StaticHandler(BaseReadHandler):
    def __init__(self, server_addr, peer, path, mode, retries, timeout, options, root):
        self._root = root

        super(StaticHandler, self).__init__(server_addr, peer, path, mode, retries, timeout, options)

    def get_target(self, path):
        return FileResponseData(os.path.join(self._root, path))


class StaticServer(Server):
    def __init__(self, ip='0.0.0.0', port=69, retries=3, timeout=5, concurrency=None, root='.'):
        self._root = os.path.abspath(root)
        super(StaticServer, self).__init__(ip, port, retries, timeout, concurrency)


    def get_hanlder(self, server_addr, peer, code, path, mode, retries, timeout, options):
        if code == constants.OPCODE_RRQ:
            return StaticHandler(server_addr, peer, path, mode, retries, timeout, options, self._root)
        else:
            print "do not handle WRQ"


if __name__ == '__main__':
    server = StaticServer()
    server.serve()

