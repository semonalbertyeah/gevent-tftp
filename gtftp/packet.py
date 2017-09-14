# -*- coding:utf-8 -*-

import struct
import copy

from .exception import *


class Packet(object):
    # opcode
    OPCODE_RRQ = 1
    OPCODE_WRQ = 2
    OPCODE_DATA = 3
    OPCODE_ACK = 4
    OPCODE_ERROR = 5
    OPCODE_OACK = 6

    # tftp mode
    MODE_NETASCII = u'netascii'
    MODE_BINARY = u'octet'

    def raw(self):
        raise NotImplemented()

    def __len__(self):
        return len(self.raw())

    def __eq__(self, other):
        return self.raw() == other.raw()

    def __ne__(self, other):
        return not self.__eq__(other)

    def size(self):
        return len(self.raw())

    def get_packet(self):
        return self.raw()


class Request(Packet):
    """
         2 bytes   string      2 bytes     string       string
        +-------+---~~---+---+---~~---+---+---~~---+---+---~~---+---+-->
        |  opc  |filename| 0 |  mode  | 0 |  opt1  | 0 | value1 | 0 | <
        +-------+---~~---+---+---~~---+---+---~~---+---+---~~---+---+-->

         >-------+---+---~~---+---+
        <  optN  | 0 | valueN | 0 |
         >-------+---+---~~---+---+
    """

    def __init__(self, opcode, path, mode, options=None):
        assert opcode in (self.OPCODE_RRQ, self.OPCODE_WRQ)
        self._opcode = opcode

        if not isinstance(path, unicode):
            # decoding with default codec
            path = str(path).decode(u'utf-8')
        self._path = path

        if not isinstance(mode, unicode):
            mode = str(mode).decode(u'utf-8')
        assert mode in (self.MODE_NETASCII, self.MODE_BINARY)
        self._mode = mode

        self._options = {}
        if options:
            options = dict(options)
            for k, v in options.iteritems():
                if not isinstance(k, unicode):
                    k = str(k).decode(u'utf-8')
                self._options[k] = v

    @property
    def opcode(self):
        return self._opcode

    @property
    def path(self):
        return self._path

    @property
    def mode(self):
        return self._mode

    @property
    def options(self):
        return copy.copy(self._options)

    def raw(self):
        path = self._path.encode(u'ascii')
        mode = self._mode.encode(u'ascii')
        fmt = u'!H%dsx%dsx' % (len(path), len(mode))
        packet = struct.pack(fmt, self._opcode, path, mode)

        if self._options:
            opts = []
            for k, v in self._options.iteritems():
                k = k.encode(u'ascii')
                v = unicode(v).encode(u'ascii')
                opts.append(struct.pack(
                    u'%dsx%ds' % (len(k), len(v)),
                    k, v
                ))

            opts = '\x00'.join(opts) + '\x00'
            packet += opts

        return packet

    @staticmethod
    def parse(raw, safe=True):
        """
            Return an instance of Request if succeed.
            If failed, raise InvalidTftpPacket if safe==False, else return None.
        """

        raw = str(raw)

        try:
            opcode = struct.unpack(u'!H', raw[:2])[0]
            if opcode not in (Request.OPCODE_RRQ, Request.OPCODE_WRQ):
                raise InvalidTftpPacket(u"invalid request opcode: %d" % opcode)

            tokens = filter(
                bool, 
                raw[2:].decode(u'ascii').split(u'\x00')
            )

            if len(tokens) < 2 or len(tokens) % 2 != 0:
                raise InvalidTftpPacket(u'malformed packet, not even number of tokens')

            path = tokens[0]
            mode = tokens[1].lower()

            options = {}
            pos = 2

            while pos < len(tokens):
                options[tokens[pos].lower()] = tokens[pos + 1]
                pos += 2

            return Request(opcode, path, mode, options)
        except InvalidTftpPacket as e:
            if safe:
                return None
            else:
                raise



class RRQ(Request):
    def __init__(self, path, mode, options=None):
        super(RRQ, self).__init__(self.OPCODE_RRQ, path, mode, options)

    @staticmethod
    def parse(raw, safe=True):
        req = Request.parse(raw, safe)
        if not req:
            return None

        try:
            if req.opcode != RRQ.OPCODE_RRQ:
                raise InvalidRRQ(u'Invalid opcode: %d' % req.opcode)
            return RRQ(req.path, req.mode, req.options)
        except InvalidRRQ as e:
            if safe:
                return None
            else:
                raise


class WRQ(Request):
    def __init__(self, path, mode, options=None):
        super(WRQ, self).__init__(self.OPCODE_WRQ, path, mode, options)


    @staticmethod
    def parse(raw, safe=True):
        req = Request.parse(raw, safe)
        if not req:
            return None

        try:
            if req.opcode != WRQ.OPCODE_WRQ:
                raise InvalidWRQ(u'Invalid opcode: %d' % req.opcode)
            return WRQ(req.path, req.mode, req.options)
        except InvalidWRQ as e:
            if safe:
                return None
            else:
                raise


class Data(Packet):
    """
        2 bytes     2 bytes      n bytes
        ----------------------------------
        | Opcode |   Block #  |   Data     |
        ----------------------------------
    """

    MAX_BLOCK_NUMBER = 65535
    DEFAULT_BLKSIZE = 512

    def __init__(self, block_number, data):
        """
            block_number: 1 - 65535
        """
        block_number = int(block_number)
        assert block_number >= 1 and block_number <= 65535
        self._block_num = block_number
        self._data = str(data)

    @property
    def block_number(self):
        return self._block_num

    @property
    def blocksize(self):
        return len(self._data)

    @property
    def data(self):
        return self._data

    def raw(self):
        fmt = u'!HH%ds' % len(self._data)
        packet = struct.pack(
            fmt, 
            self.OPCODE_DATA,
            self._block_num,
            self._data
        )

        return packet

    @staticmethod
    def parse(raw, safe=True):
        raw = str(raw)

        try:
            opcode = struct.unpack(u'!H', raw[:2])[0]
            if opcode != Data.OPCODE_DATA:
                raise InvalidDataPacket(u"invalid data opcode: %d" % opcode)

            block_num = struct.unpack(u'!H', raw[2:4])[0]
            if block_num == 0:
                raise InvalidDataPacket(u"invalid data data block number: %d" % block_num)

            data = raw[4:]

            return Data(block_num, data)
        except InvalidDataPacket as e:
            if safe:
                return None
            else:
                raise


class ACK(Packet):
    """
         2 bytes     2 bytes
         ---------------------
        | Opcode |   Block #  |
         ---------------------
    """
    def __init__(self, block_number):
        block_number = int(block_number)
        assert block_number >= 0 and block_number <= 65535
        self._block_num = block_number

    @property
    def block_number(self):
        return self._block_num

    def raw(self):
        packet = struct.pack(
            u'!HH', self.OPCODE_ACK, self._block_num
        )
        return packet

    @staticmethod
    def parse(raw, safe=True):
        raw = str(raw)
        try:
            if len(raw) != 4:
                raise InvalidACK('ACK packet length is 4.')

            opcode = struct.unpack(u'!H', raw[:2])[0]
            if opcode != ACK.OPCODE_ACK:
                raise InvalidACK(u"invalid ACK opcode: %d" % opcode)

            block_num = struct.unpack(u'!H', raw[2:4])[0]

            return ACK(block_num)

        except InvalidACK as e:
            if safe:
                return None
            else:
                raise


class Error(Packet, TftpError):
    """
       2 bytes     2 bytes      string    1 byte
       -----------------------------------------
      | Opcode |  ErrorCode |   ErrMsg   |   0  |
       -----------------------------------------
    """

    # error code
    UNDEFINED = 0           # Not defined, see error msg (if any) - RFC 1350.
    FILE_NOT_FOUND = 1      # File not found - RFC 1350.
    ACCESS_VIOLATION = 2    # Access violation - RFC 1350.
    DISK_FULL = 3           # Disk full or allocation exceeded - RFC 1350.
    ILLEGAL_OPERATION = 4   # Illegal TFTP operation - RFC 1350.
    UNKNOWN_TRANSFER_ID = 5 # Unknown transfer ID - RFC 1350.
    FILE_EXISTS = 6         # File already exists - RFC 1350.
    NO_SUCH_USER = 7        # No such user - RFC 1350.
    INVALID_OPTIONS = 8     # One or more options are invalid - RFC 2347.

    ERR_CODES = (
        UNDEFINED,
        FILE_NOT_FOUND,
        ACCESS_VIOLATION,
        DISK_FULL,
        ILLEGAL_OPERATION,
        UNKNOWN_TRANSFER_ID,
        FILE_EXISTS,
        NO_SUCH_USER,
        INVALID_OPTIONS
    )

    def __init__(self, code, message=u''):
        assert code in self.ERR_CODES
        self._code = code
        if not isinstance(message, unicode):
            message = str(message).decode(u'utf-8')
        self._msg = message

    def __repr__(self):
        return u'<Error: code=%d, message="%s">' % (self._code, self._msg)

    def __str__(self):
        return self.__repr__().encode(u'utf-8')

    @property
    def code(self):
        return self._code

    @property
    def message(self):
        return self._msg

    def raw(self):
        msg = self._msg.encode(u'ascii')
        packet = struct.pack(
            u'!HH%dsx' % len(msg),
            self.OPCODE_ERROR, self._code, msg
        )

        return packet

    @staticmethod
    def parse(raw, safe=True):
        try:
            opcode = struct.unpack(u'!H', raw[:2])[0]
            if opcode != Error.OPCODE_ERROR:
                raise InvalidErrorPacket(u"invalid ERROR opcode: %d" % opcode)

            err_code = struct.unpack(u'!H', raw[2:4])[0]
            if err_code not in Error.ERR_CODES:
                raise InvalidErrorPacket(u'Invalid error code: %d' % err_code)

            message = raw[4:]
            if message[-1] == '\x00':
                message = message[:-1]

            return Error(err_code, message.decode(u'ascii'))

        except InvalidErrorPacket as e:
            if safe:
                return None
            else:
                raise


class OACK(Packet):
    """
         2 bytes   string      string
        +-------+---~~---+---+---~~---+---+---~~---+---+---~~---+---+
        |  opc  |  opt1  | 0 | value1 | 0 |  optN  | 0 | valueN | 0 |
        +-------+---~~---+---+---~~---+---+---~~---+---+---~~---+---+
    """

    def __init__(self, options):
        options = dict(options)
        assert options, u'empty options'
        self._opts = {}
        for k, v in options.iteritems():
            if not isinstance(k, unicode):
                k = str(k).decode(u'utf-8')
            self._opts[k] = v

    @property
    def options(self):
        return copy.copy(self._opts)

    def raw(self):
        opts = []
        for k, v in self._opts.iteritems():
            k = k.encode(u'ascii')
            v = unicode(v).encode(u'ascii')
            opts.append(struct.pack(
                u'%dsx%ds' % (len(k), len(v)),
                k, v
            ))

        opts = '\x00'.join(opts) + '\x00'
        packet = struct.pack(u'!H', self.OPCODE_OACK) + opts

        return packet


    @staticmethod
    def parse(raw, safe=True):
        try:
            opcode = struct.unpack(u'!H', raw[:2])[0]
            if opcode != OACK.OPCODE_OACK:
                raise InvalidOACK(u"invalid OACK opcode: %d" % opcode)

            tokens = filter(
                bool, 
                raw[2:].decode(u'ascii').split(u'\x00')
            )

            options = {}
            pos = 0
            while pos < len(tokens):
                options[tokens[pos].lower()] = tokens[pos + 1]
                pos += 2

            return OACK(options)

        except InvalidOACK as e:
            if safe:
                return None
            else:
                raise




