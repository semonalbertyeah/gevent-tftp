# -*- coding:utf-8 -*-

import io
import ipaddress
import struct
import time

from gevent import socket, Timeout

from . import constants
from .netascii import NetasciiReader, NetasciiWriter
from .logger import logger


class Target(object):
    '''
        target file

        In response to RRQ request,
        the target should be readable (implement methods: read, size, close).

        In response to WRQ request,
        the target should be writable(implement methods: write, close).
    '''

    def read(self, size):
        '''
            Read at most n characters, returned as a string.

            If the argument is negative or omitted, read until EOF
            is reached. Return an empty string at EOF.
        '''
        raise NotImplemented()

    def write(self, data):
        '''
            Write string to file.
 
            Returns the number of characters written, which is always equal to
            the length of the string.
        '''
        raise NotImplemented()

    def size(self):
        '''
            return the size of target.
        '''
        raise NotImplemented()

    def close(self):
        '''
            This method has no effect if the file is already closed.
        '''
        raise NotImplemented()


class TftpError(Exception):
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

    # custom error code (out of range of 16-bit uint)
    TIMEOUT = 0x10000       # timeout waiting ACK
    SERVER_ERROR = 0x10001  # internal error

    def __init__(self, code, message=u'', local=True):
        """
            local:
                True -> local error
                False -> received error packet

        """
        self._local = bool(local)
        self._code = code
        if not isinstance(message, unicode):
            message = str(message).decode('utf-8')

        self._message = message

    def __repr__(self):
        return u'<TftpError: code=%d, message="%s">' % (self._code, self._message)

    def __unicode__(self):
        return self._message

    def __str__(self):
        return self.__unicode__().encode('utf-8')

    #########################
    # readonly properties
    #########################
    @property
    def code(self):
        return self._code

    @property
    def message(self):
        return self._message

    @property
    def local(self):
        return self._local




class BaseReadHandler(object):
    def __init__(self, server_addr, peer, path, mode, retries, timeout, options):
        # self._req_info = {
        #     u'peer': peer,
        #     u'path': path,
        #     u'mode': mode
        #     u'retries': retries,
        #     u'timeout': timeout,
        #     u'options': options,
        # }
        self._peer = peer
        self._retries = retries
        self._timeout = timeout
        self._options = options
        self._path = path
        self._mode = mode
        self._blksize = constants.DEFAULT_BLKSIZE

        self._family = socket.AF_INET6
        ip = server_addr[0]
        if not isinstance(ip, unicode):
            ip = str(ip).decode(u'utf-8')
        if isinstance(
            ipaddress.ip_address(ip), ipaddress.IPv4Address
        ):
            self._family = socket.AF_INET
            # peer address format is different in v4 world
            self._peer = (self._peer[0].replace(u'::ffff:', ''), self._peer[1])

        self._ip = ip

        #######################
        # tftp session stats:
        #######################
        self._cur_block_num = 0     # current block number, block number starts from 1.
        self._cur_block = None      # keep track of current data block
        self._retransmits = 0       # number of retranmissions of current data block


        self._listener = None
        self._target = None
        self._should_stop = False   # indicates end of session



    def _before_run(self):
        """
            To instantiate needed objects.
        """
        self._listener = socket.socket(family=self._family, type=socket.SOCK_DGRAM)
        self._listener.settimeout(None) # blocking
        self._listener.bind((self._ip, 0))

        try:
            self._target = self.get_target(self._path)
            if self._mode == u'netascii':
                self._target = NetasciiReader(self._target)
        except Exception as e:
            logger.exception(u'Unexpected error when instantiating target.')
            raise TftpError(TftpError.UNDEFINED, unicode(e))


    def _close(self):
        if self._target is not None:
            self._target.close()
        if self._listener is not None:
            self._listener.close()


    def __call__(self):
        self.run()

    def run(self):
        """
            main loop.
            everything starts here.
        """
        try:
            self._before_run()

            self._handle_rrq()

            while not self._should_stop:
                self.run_once()

            # wait the last ACK
            print 'waiting last ack'
            while not self._wait_ack():
                self._handle_timeout()

        except TftpError as e:
            if e.code <= 0xffff:
                # not custom error
                if e.local:
                    # do not re-send error packet
                    self._transmit_error(e.code, e.message)

        finally:
            self._close()


    def _handle_rrq(self):
        """
            handle RRQ packet
            if options:
                negotiation
            else:
                send first data block.
        """
        self._parse_options()

        if self._options:
            # send OACK
            self._transmit_oack()
        else:
            # no options (or not accepted).
            # send the first block of data
            self._next_block()
            self._transmit_data()


    def run_once(self):
        """
            recv ACK
            send DATA
        """
        # recv ack
        if self._wait_ack():
            self._handle_ack()
        else:
            # timeout waiting 
            # or receiving ACK packet with wrong block number.
            # both are treated as timeout.
            self._handle_timeout()

    def _wait_ack(self):
        """
            ack or timeout
            return:
                True -> current block is acked.
                False -> timeout waiting acknowledgement.
        """
        timer = Timeout.start_new(self._timeout)

        try:
            while self.__wait_one_ack() != self._cur_block_num:
                # timer's ticking.
                pass

            return True
        except Timeout as e:
            return None
        finally:
            timer.cancel()

    def __wait_one_ack(self):
        data, peer = self._listener.recvfrom(constants.DEFAULT_BLKSIZE)

        if peer != self._peer:
            logger.warning(u'Packet received from wrong peer: %r. End the session.' % peer)
            raise TftpError(TftpError.SERVER_ERROR, u'from wrong peer')

        code, block_num = struct.unpack(u'!HH', data[:4])
        if code == constants.OPCODE_ERROR:
            logger.error(u'Error packet, message: %s' % data[4:].decode(u'ascii', u'ignore'))
            raise TftpError(code, data[4:].decode('ascii', 'ignore'), local=False)

        if code != constants.OPCODE_ACK:
            # So it's vunerable to malformed packets.
            logger.error(u'Non-ACK packet received in read handler.')
            raise TftpError(TftpError.ILLEGAL_OPERATION, u'I only do reads, really.')

        return block_num


    def _handle_ack(self):

        self._retransmits = 0

        # send next block
        self._next_block()
        self._transmit_data()



    def _handle_timeout(self):
        if self._retries >= self._retransmits:
            self._transmit_data()
            self._retransmits += 1
            return

        logger.error(u'Timeout after %d retransmits' % self._retransmits)
        raise TftpError(TftpError.TIMEOUT, u'timeout after %d retransmits' % self._retransmits)


    def _parse_options(self):
        """
            parse options:
                self._options
        """

        opts_to_ack = {}

        for k, v in self._options.iteritems():
            if k == u'blksize':
                try:
                    v = int(v)
                except ValueError as e:
                    raise TftpError(
                        TftpError.INVALID_OPTIONS,
                        u'invalid block size %s.' % v
                    )

                if v < 8 or v > 65464:
                    raise TftpError(
                        TftpError.INVALID_OPTIONS,
                        u'block size value (%d) is out of range(8-65464).' % v
                    )

                opts_to_ack[u'blksize'] = unicode(v)
                self._blksize = v

            elif k == u'tsize':
                self._tsize = self._target.size()
                if self._tsize is not None:
                    opts_to_ack[u'tsize'] = unicode(self._tsize)

            elif k == 'timeout':
                try:
                    v = int(v)
                except ValueError as e:
                    raise TftpError(
                        TftpError.INVALID_OPTIONS,
                        u'invalid timeout %s' % v
                    )

                if v < 1 or v > 255:
                    raise TftpError(
                        TftpError.INVALID_OPTIONS,
                        u'timeout value (%d) is out of range(1, 255)' % v
                    )

                self._timeout = v
                opts_to_ack[u'timeout'] = unicode(v)

        self._options = opts_to_ack


    def _next_block(self):
        """
            prepare the next data block.
        """
        self._cur_block_num += 1
        if self._cur_block_num > constants.MAX_BLOCK_NUMBER:
            self._cur_block_num = 0 # re-count

        try:
            data = self._target.read(self._blksize)
            self._cur_block = data
            while (len(self._cur_block) != self._blksize) and (data):
                # if no data -> EOF.
                data = self._target.read(self._blksize - len(self._cur_block))
                self._cur_block += data

        except Exception as e:
            logger.exception(u"Unexpected exception when do target.read")
            raise TftpError(
                TftpError.UNDEFINED,
                u'Error while reading from source'
            )


    def _transmit_data(self):
        assert self._cur_block is not None

        fmt = u'!HH%ds' % len(self._cur_block)
        packet = struct.pack(
            fmt,
            constants.OPCODE_DATA,
            self._cur_block_num,
            self._cur_block
        )
        self._listener.sendto(packet, self._peer)

        if len(self._cur_block) < self._blksize:
            logger.info('last data packet')
            self._should_stop = True


    def _transmit_error(self, code, message):
        if not isinstance(message, str):
            message = message.encode('ascii')

        fmt = u'!HH%dsx' % len(message)
        packet = struct.pack(
            fmt, constants.OPCODE_ERROR,
            code,
            message
        )
        self._listener.sendto(packet, self._peer)

    def _transmit_oack(self):
        """
            sending OACK accoring to self._options
        """
        opts = []
        for k,v in self._options.iteritems():
            fmt = u'%dsx%dsx' % (len(k), len(v))
            opts.append(
                struct.packt(
                    fmt,
                    k.encode(u'ascii'),
                    v.encode(u'ascii')
                )
            )

        packet = struct.pack(u'!H', constants.OPCODE_OACK) + \
                 '\x00'.join(opts) + '\x00'

        self._listener.sendto(packet, self._peer)

    def get_target(self, path):
        """
            override this method.
            return a instance of subclass of Target.
        """
        raise NotImplemented()


# class BaseWriteHandler(object):
#     def __init__(self, server_addr, peer, path, mode, retries, timeout, options):


