# -*- coding:utf-8 -*-

import sys, logging

def init_logger(logger=None):
    logger = logger or logging.getLogger('gtftp')
    logger.setLevel(logging.DEBUG)

    # stream handler to stdout
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(
        logging.Formatter(
            "%(asctime)s-%(name)s-%(levelname)s: %(message)s"
        )
    )

    logger.addHandler(ch)

    # log every exception
    sys.excepthook = lambda t, v, tb: logger.error('Uncaught exception:', exc_info=(t, v, tb))

    return logger


def get_logger():
    return logging.getLogger('gtftp')


logger = init_logger()

