""" Blabla """
import sys
import logging
from logging.handlers import WatchedFileHandler
from pathlib import Path


def create_logger(name: str, log_dir: str, level: str):
    """ Blabla """
    logger = logging.getLogger(name)
    if len(logger.handlers) > 0:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)-8s] [%(module)-20s] - %(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    handler = WatchedFileHandler(str(Path(log_dir) / f'{name}.log'))
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
