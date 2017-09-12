# -*- coding:utf-8 -*-

import io


class NetasciiReader(object):
    """
        copied from fbtftp.netascii:NetasciiReader

        NetasciiReader encodes (asci) data coming from a reader into NetASCII.

        If the size of the returned data needs to be known in advance this will
        actually have to load the whole content of its underlying reader into
        memory which is suboptimal but also the only way in which we can make
        NetASCII work with the 'tsize' TFTP extension.
    """

    def __init__(self, reader):
        self._reader = reader
        self._buffer = bytearray()
        self._slurp = None
        self._size = None

    def read(self, size):
        if self._slurp is not None:
            return self._slurp.read(size)
        data, buffer_size = bytearray(), 0
        if self._buffer:
            buffer_size = len(self._buffer)
            data.extend(self._buffer)
        for char in self._reader.read(size - buffer_size):
            char = ord(char)
            if char == ord(u'\n'):
                data.extend([ord(u'\r'), ord(u'\n')])
            elif char == ord('\r'):
                data.extend([ord(u'\r'), 0])
            else:
                data.append(char)
        self._buffer = bytearray(data[size:])
        return str(data[:size])

    def close(self):
        self._reader.close()

    def size(self):
        if self._size is not None:
            return self._size
        slurp, size = io.BytesIO(), 0
        while True:
            data = self.read(512)
            if not data:
                break
            size += slurp.write(data)
        self._slurp, self._size = slurp, size
        self._slurp.seek(0)
        return size


class NetasciiWriter(object):
    def __init__(self, writer):
        self._writer = writer

    def write(self, data):
        """
            data - unicode, bytearray, str
        """
        if isinstance(data, unicode):
            data = data.encode('ascii')
        data = bytearray(data)

        idx = 0
        data_len = len(data)
        while idx < data_len:
            char = data[idx]
            if char == ord(u'\r') and data[idx+1] == ord(u'\n'):
                self._writer.write(u'\n'.encode('ascii'))
                idx += 1
            elif char == ord(u'\r') and data[idx+1] == ord(u'\0'):
                self._writer.write(u'\r')
                idx += 1
            else:
                self._writer.write(chr(char))

            idx += 1

    def close(self):
        self._writer.close()





