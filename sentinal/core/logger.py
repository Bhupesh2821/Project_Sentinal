"""Rotating diagnostic logging without footage or detection payloads."""
from logging.handlers import RotatingFileHandler
import logging
from sentinal.config import ROOT


def configure_logging():
    folder = ROOT / 'logs'
    folder.mkdir(exist_ok=True)
    handler = RotatingFileHandler(folder / 'sentinal.log', maxBytes=2000000, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.captureWarnings(True)
