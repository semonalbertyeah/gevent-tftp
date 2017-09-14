# -*- coding:utf-8 -*-


class TftpError(Exception):
    pass


class PeerError(TftpError):
    """
        ERROR packet received from peer.
    """
    def __init__(self, code, message=u''):
        self._code = code
        if not isinstance(message, unicode):
            message = str(message).decode(u'utf-8')
        self._msg = message

    @property
    def code(self):
        return self._code

    @property
    def message(self):
        return self._msg


class TransmitTimeout(TftpError):
    """
        Timeout after retransmission.
    """
    def __init__(self, message=u''):
        self._msg = message



class InvalidTftpPacket(TftpError):
    """
        May be raised when parsing a TFTP packet.
    """
    pass

class InvalidRRQ(TftpError):
    pass

class InvalidWRQ(TftpError):
    pass

class InvalidDataPacket(TftpError):
    pass

class InvalidACK(TftpError):
    pass

class InvalidErrorPacket(TftpError):
    pass

class InvalidOACK(TftpError):
    pass


