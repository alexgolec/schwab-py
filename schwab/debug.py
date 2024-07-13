import atexit
import json
import logging
import sys
from collections import defaultdict
import importlib
import httpx
from .version import version as __version__


class LogRedactor:
    '''
    Collects strings that should not be emitted and replaces them with safe
    placeholders.
    '''

    def __init__(self):

        self.redacted_strings = {}
        self.label_counts = defaultdict(int)
        self.whitelisted = set()

    def register(self, string, label, whitelisted=False):
        '''
        Registers a string that should not be emitted and the label with with
        which it should be replaced.
        '''
        string = str(string)
        if whitelisted:
            self.whitelisted.add(string.lower())

        if string.lower() not in self.redacted_strings and string.lower() not in self.whitelisted:
            self.label_counts[label] += 1
            self.redacted_strings[string] = (label, self.label_counts[label])

    def redact(self, msg):
        '''
        Scans the string for secret strings and returns a sanitized version with
        the secrets replaced with placeholders.
        '''
        for string, (label, count) in self.redacted_strings.items():
            if string.lower() not in self.whitelisted:
                label_suffix = f"-{count}" if self.label_counts[label] > 1 else ""
                redacted_text = f"<REDACTED {label}{label_suffix}>"
                msg = msg.replace(string, redacted_text)
        return msg


# Create a global instance
_global_log_redactor = LogRedactor()


def get_log_redactor():
    return _global_log_redactor


def get_logger():
    return logging.getLogger(__name__)


def register_redactions_from_response(resp):
    '''
    Convenience method that calls ``register_redactions`` if resp represents a
    successful response. Note this method assumes that resp has a JSON contents.
    '''
    if resp.status_code == httpx.codes.OK:
        try:
            register_redactions(resp.json())
        except json.decoder.JSONDecodeError:
            pass


def register_redactions(obj, key_path=None,
                        bad_patterns=('auth', 'acl', 'displayname', 'id', 'key', 'token'),
                        whitelisted=frozenset((
                            'requestid', 'token_type', 'legid', 'bidid', 'askid', 'lastid',
                            'bidsizeinlong', 'bidsizeindouble', 'bidpriceindouble'))):
    '''
    Iterates through the leaf elements of ``obj`` and registers
    elements with keys matching a blacklist with the global ``Redactor``.
    '''
    if key_path is None:
        key_path = []

    stack = [(obj, key_path)]

    while stack:
        current_obj, current_path = stack.pop()

        if isinstance(current_obj, dict):
            for key, value in current_obj.items():
                stack.append((value, current_path + [key]))
        elif isinstance(current_obj, list):
            for idx, value in enumerate(current_obj):
                stack.append((value, current_path + [str(idx)]))
        else:
            if current_path:
                last_key = current_path[-1]
                full_path = '-'.join(current_path)

                is_whitelisted = last_key.lower() in whitelisted or full_path.lower() in whitelisted
                should_redact = any(bad.lower() in last_key.lower() for bad in bad_patterns)

                if is_whitelisted:
                    get_log_redactor().register(current_obj, full_path, whitelisted=True)
                elif should_redact:
                    get_log_redactor().register(current_obj, full_path)


def enable_bug_report_logging():
    '''
    Turns on bug report logging. Will collect all logged output, redact out
    anything that should be kept secret, and emit the result at program exit.

    Notes:
     * This method does a best effort redaction. Never share its output
       without verifying that all secret information is properly redacted.
     * Because this function records all logged output, it has a performance
       penalty. It should not be called in production code.
    '''
    _enable_bug_report_logging()


def _enable_bug_report_logging(output=sys.stderr, loggers=None):
    '''
    Module-internal version of :func:`enable_bug_report_logging`, intended for
    use in tests.
    '''

    if loggers is None:
        # Use lazy imports
        def get_logger_lazy(module_path):
            module = importlib.import_module(module_path)
            return module.get_logger()

        loggers = (
            get_logger_lazy('schwab.auth'),
            get_logger_lazy('schwab.client.base'),
            get_logger_lazy('schwab.streaming'),
            get_logger()
        )

    class RecordingHandler(logging.Handler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.messages = []

        def emit(self, record):
            self.messages.append(self.format(record))

    handler = RecordingHandler()
    handler.setFormatter(logging.Formatter(
        '[%(filename)s:%(lineno)s:%(funcName)s] %(message)s'))

    for logger in loggers:
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

    def write_logs():
        print(file=output)
        print(' ### BEGIN REDACTED LOGS ###', file=output)
        print(file=output)

        for msg in handler.messages:
            msg = get_log_redactor().redact(msg)
            print(msg, file=output)
    atexit.register(write_logs)

    get_logger().debug('schwab-api version %s', __version__)

    return write_logs
