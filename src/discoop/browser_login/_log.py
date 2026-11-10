"""The package logger (ADR 0018): short `key=value` events only, never a token, header, URL or profile path."""

import logging

logger = logging.getLogger("discoop.browser_login")
logger.addHandler(logging.NullHandler())  # no handler of ours: do not let `lastResort` print it to stderr
