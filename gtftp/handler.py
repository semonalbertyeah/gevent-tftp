# -*- coding:utf-8 -*-

import io
import ipaddress
import struct
import time

from gevent import socket, Timeout

from .packet import *
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



class BaseReadHandler(object):
    def __init__(self, req, server_addr, peer, retries, timeout):
        assert isinstance(req, Request)
        assert req.opcode == Packet.OPCODE_RRQ
        self._req = req
        self._peer = peer
        self._retries = int(retries)

        self._options = None    # applied options
        self._blksize = Data.DEFAULT_BLKSIZE
        self._timeout = timeout

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

        self._cur_packet = None     # last sent packet, kept for retransmission
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

        self._target = self.get_target(self._req.path)
        if self._req.mode == Request.MODE_NETASCII:
            self._target = NetasciiReader(self._target)



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
            logger.info('waiting last ack')
            while not self._wait_ack():
                self._handle_timeout()

            logger.info(u'Session ends, peer: (%s, %d)' % (self._peer[0], self._peer[1]))

        except Error as e:
            logger.error(
                u"End session is ended by server, code: %d, message: %s" % \
                (e.code, e.message)
            )
            self._transmit(e)

        except PeerError as e:
            logger.error(
                u'Session is ended by peer, code: %d, message: %s' % \
                (e.code, e.message)
            )

        except TransmitTimeout as e:
            logger.error(u'Timeout after %d times of retransmission' % self._retries)

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
        self._apply_options()

        if self._options:
            # send OACK
            self._cur_packet = OACK(self._options)
            self._transmit(self._cur_packet)
        else:
            # no options (or not accepted).
            # send the first block of data
            self._cur_packet = self._next_block()
            self._transmit(self._cur_packet)
            if self._cur_packet.blocksize < self._blksize:
                self._should_stop = True

    def _apply_options(self):
        """
            parse options:
                self._options
        """

        opts_to_ack = {}

        for k, v in self._req.options.iteritems():
            if k == u'blksize':
                try:
                    v = int(v)
                except ValueError as e:
                    raise Error(
                        Error.INVALID_OPTIONS,
                        u'invalid block size %s.' % v
                    )

                if v < 8 or v > 65464:
                    raise Error(
                        Error.INVALID_OPTIONS,
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
                    raise Error(
                        Error.INVALID_OPTIONS,
                        u'invalid timeout %s' % v
                    )

                if v < 1 or v > 255:
                    raise Error(
                        Error.INVALID_OPTIONS,
                        u'timeout value (%d) is out of range(1, 255)' % v
                    )

                self._timeout = v
                opts_to_ack[u'timeout'] = unicode(v)

        self._options = opts_to_ack

    @property
    def _expected_block_num(self):
        """
            Expected block number in ACK.
        """
        if self._cur_packet is None or isinstance(self._cur_packet, OACK):
            return 0
        else:
            return self._cur_packet.block_number

    def run_once(self):
        """
            recv ACK
            send DATA
        """
        # recv ack
        if self._wait_ack():
            self._retransmits = 0
            self._cur_packet = self._next_block()
            self._transmit(self._cur_packet)
            if self._cur_packet.blocksize < self._blksize:
                self._should_stop = True
        else:
            # timeout waiting for the expected ACK.
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
            while self.__wait_one_ack() != self._expected_block_num:
                # timer's ticking.
                pass

            return True
        except Timeout as e:
            return None
        finally:
            timer.cancel()

    def __wait_one_ack(self):
        data, peer = self._listener.recvfrom(Data.DEFAULT_BLKSIZE)

        if peer != self._peer:
            logger.warning(u'Packet received from wrong peer: %r. End the session.' % peer)
            raise Error(Error.UNDEFINED, u'from wrong peer')

        err = Error.parse(data)
        if err:
            raise err

        ack = ACK.parse(data)
        if ack:
            return ack.block_number
        else:
            raise Error(Error.ILLEGAL_OPERATION, u'Expecting an ACK.')

        return block_num


    def _handle_timeout(self):
        if self._retransmits < self._retries:
            assert self._cur_packet
            print 'retransmit:', self._cur_packet
            self._transmit(self._cur_packet)
            self._retransmits += 1

        else:
            raise TransmitTimeout()


    def _next_block(self):
        """
            prepare the next data block.
        """
        if self._cur_packet is None or isinstance(self._cur_packet, OACK):
            block_num = 1
        else:
            block_num = self._cur_packet.block_number + 1
            if block_num > 65535:
                block_num = 1

        data = self._target.read(self._blksize)
        block = data
        while (len(block) < self._blksize) and (data):
            # if no data -> EOF.
            data = self._target.read(self._blksize - len(block))
            block += data

        return Data(block_num, block)

    def _transmit(self, packet):
        if isinstance(packet, Packet):
            packet = packet.raw()

        self._listener.sendto(packet, self._peer)

    def get_target(self, path):
        """
            override this method.
            return a instance of subclass of Target.
        """
        raise NotImplemented()


class BaseWriteHandler(object):
    def __init__(self, req, server_addr, peer, retries, timeout):
        assert isinstance(req, Request)
        assert req.opcode == Packet.OPCODE_WRQ
        self._req = req
        self._peer = peer
        self._retries = retries

        self._options = None  # applied options
        self._blksize = Data.DEFAULT_BLKSIZE
        self._timeout = timeout
        self._tsize = None

        self._family = socket.AF_INET6
        ip = server_addr[0]
        if not isinstance(ip, unicode):
            ip = str(ip).decode('utf-8')
        if isinstance(
            ipaddress.ip_address(ip), ipaddress.IPv4Address
        ):
            self._family = socket.AF_INET
            # peer address format is different in v4 world
            self._peer = (self._peer[0].replace(u'::ffff:', ''), self._peer[1])
        self._ip = ip

        self._cur_packet = None     # last sent packet
        self._retransmits = 0
        self._received_size = 0

        self._listener = None
        self._target = None
        self._should_stop = False


    def _before_run(self):
        """
            To instantiate needed objects.
        """
        self._listener = socket.socket(family=self._family, type=socket.SOCK_DGRAM)
        self._listener.settimeout(None) # blocking
        self._listener.bind((self._ip, 0))

        self._target = self.get_target(self._req.path)
        if self._req.mode == Request.MODE_NETASCII:
            self._target = NetasciiWriter(self._target)


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

            self._handle_wrq()

            while not self._should_stop:
                self.run_once()

            logger.info(u'Session ends, peer: (%s, %d)' % (self._peer[0], self._peer[1]))

        except Error as e:
            logger.error(
                u"End session is ended by server, code: %d, message: %s" % \
                (e.code, e.message)
            )
            self._transmit(e)

        except PeerError as e:
            logger.error(
                u'Session is ended by peer, code: %d, message: %s' % \
                (e.code, e.message)
            )

        except TransmitTimeout as e:
            logger.error(u'Timeout after %d times of retransmission' % self._retries)

        finally:
            self._close()

    def _handle_wrq(self):
        """
            if options:
                OACK
            else:
                ACK(0)
        """
        self._apply_options()

        if self._options:
            # send OACK
            self._cur_packet = OACK(self._options)
            self._transmit(self._cur_packet)
        else:
            # no options (or not accepted).
            # Acknowledgement block num: 0
            self._cur_packet = ACK(0)
            self._transmit(self._cur_packet)


    def _apply_options(self):
        """
            parse options:
                self._options
        """

        opts_to_ack = {}

        for k, v in self._req.options.iteritems():
            if k == u'blksize':
                try:
                    v = int(v)
                except ValueError as e:
                    raise Error(
                        Error.INVALID_OPTIONS,
                        u'invalid block size %s.' % v
                    )

                if v < 8 or v > 65464:
                    raise Error(
                        Error.INVALID_OPTIONS,
                        u'block size value (%d) is out of range(8-65464).' % v
                    )

                opts_to_ack[u'blksize'] = unicode(v)
                self._blksize = v

            elif k == u'tsize':
                try:
                    v = int(v)
                except ValueError as e:
                    raise Error(
                        Error.INVALID_OPTIONS,
                        u'invalid tsize %s' % v
                    )
                if v < 0:
                    raise Error(
                        Error.INVALID_OPTIONS,
                        u'tsize value %d is less than 0.' % v
                    )
                self._tsize = v
                opts_to_ack[u'tsize'] = unicode(self._tsize)

            elif k == 'timeout':
                try:
                    v = int(v)
                except ValueError as e:
                    raise Error(
                        Error.INVALID_OPTIONS,
                        u'invalid timeout %s' % v
                    )

                if v < 1 or v > 255:
                    raise Error(
                        Error.INVALID_OPTIONS,
                        u'timeout value (%d) is out of range(1, 255)' % v
                    )

                self._timeout = v
                opts_to_ack[u'timeout'] = unicode(v)

        self._options = opts_to_ack


    def run_once(self):
        data = self._wait_data()
        if data:
            self._retransmits = 0
            print 'write data, block: %d, size: %d' % (data.block_number, data.blocksize)
            self._target.write(data.data)
            self._received_size += data.blocksize

            self._cur_packet = ACK(data.block_number)
            self._transmit(self._cur_packet)

            if data.blocksize < self._blksize:
                self._should_stop = True
        else:
            self._handle_timeout()

    @property
    def _expected_block_num(self):
        if self._cur_packet is None:
            # transfer is not started
            return None
        elif isinstance(self._cur_packet, OACK):
            return 1
        else:
            assert isinstance(self._cur_packet, ACK)
            return self._cur_packet.block_number + 1

    def _wait_data(self):
        """
            wait a data or timeout
        """
        timer = Timeout.start_new(self._timeout)

        try:
            while True:
                data = self._wait_one_block()
                if isinstance(data, Data) and data.block_number == self._expected_block_num:
                    break

            return data
        except Timeout as e:
            return None
        finally:
            timer.cancel()


    def _wait_one_block(self):
        """
            wait DATA
            if expected DATA block (acked_block_num + 1):
                store data
                # received_size += len(data)
                send ack
            else:
                send error
                end session
        """
        block, peer = self._listener.recvfrom(self._blksize + 4)

        if peer != self._peer:
            raise Error(Error.UNDEFINED, u'from wrong peer')

        err = Error.parse(block)
        if err:
            raise err

        data = Data.parse(block)

        if not data:
            # malformed packet, end the session.
            raise Error(Error.ILLEGAL_OPERATION, u'Expecting a data block.')

        return data


    def _transmit(self, packet):
        if isinstance(packet, Packet):
            packet = packet.raw()

        self._listener.sendto(packet, self._peer)


    def get_target(self):
        raise NotImplemented()



