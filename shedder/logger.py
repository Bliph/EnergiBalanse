import sys
import logging
from logging.handlers import WatchedFileHandler
from pathlib import Path

def create_logger(name, level, log_dir):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)-8s] [%(module)-20s] - %(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    handler = WatchedFileHandler(str(Path(log_dir) / '{}.log'.format(name)))
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger