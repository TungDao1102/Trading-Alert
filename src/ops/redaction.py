"""Secret redaction for logs, tracebacks and stderr prints (Phase 13.1, D-09, F-708).

One ``Redactor`` is shared by every output path a secret could take inside the
containerised processes:

  - structlog events        -> ``redact_processor`` (after ``format_exc_info``)
  - stdlib ``logging``      -> ``RedactingFilter`` on every root handler
  - uncaught exceptions     -> wrapped ``sys.excepthook`` / ``threading.excepthook``
  - explicit stderr prints  -> module-level ``scrub()``
  - httpx / httpcore INFO   -> raised to WARNING (Telegram URLs embed the bot token)

Two layers decide what is a secret:

  1. Values: the value of every environment variable whose NAME looks secret
     (``PASSWORD``, ``SECRET``, ``TOKEN``, ``API_KEY``, ``ACCESS_KEY``, ``CRYPT``,
     ``PRIVATE``) and the password part of any URL-shaped variable, plus
     percent-encoded and JSON-escaped variants.
  2. Shapes (no environment needed): URL userinfo passwords, Telegram bot tokens,
     ``signature=<64 hex>``, ``X-MBX-APIKEY`` header values, AWS-style access key
     ids and PEM private key blocks.

Structlog keys named like ``password`` / ``secret`` / ``token`` / ``api_key`` /
``authorization`` / ``signature`` are masked whatever their value.

The module imports only the standard library and structlog. It never applies
application-level encryption (D045(b)); it only removes text from output.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import traceback
from collections.abc import Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any, TextIO
from urllib.parse import quote, unquote, urlsplit

import structlog
from structlog.typing import EventDict, WrappedLogger

REDACTED = "[REDACTED]"

# Upper-cased environment variable NAME fragments that mark a value as secret.
SECRET_ENV_NAME_PARTS: tuple[str, ...] = (
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "API_KEY",
    "ACCESS_KEY",
    "CRYPT",
    "PRIVATE",
)

# Lower-cased structlog key fragments whose value is masked regardless of content.
SECRET_KEY_NAME_PARTS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "signature",
)

# Values shorter than this are never collected from the environment (flags such as
# "1" or "true" must not turn into redaction rules).
MIN_SECRET_LENGTH = 8

# --------------------------------------------------------------------------- #
# Shape rules (independent of the environment). Each entry is (pattern, replacement).
# --------------------------------------------------------------------------- #

_PEM_BEGIN = "-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
_PEM_END = "-----END [A-Z0-9 ]*PRIVATE KEY-----"

SHAPE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # PEM private key blocks (also a truncated block with no END line).
    (re.compile(rf"{_PEM_BEGIN}.*?(?:{_PEM_END}|\Z)", re.DOTALL), REDACTED),
    # URL userinfo password: scheme://user:PASSWORD@host
    (re.compile(r"(://[^\s/:@\"']*:)[^\s/@\"']+(@)"), rf"\1{REDACTED}\2"),
    # Telegram bot token: <8-10 digits>:<35 url-safe chars>
    (re.compile(r"(?<![0-9])\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"), REDACTED),
    # Binance signed-request signature query parameter.
    (re.compile(r"(?i)(signature=)[0-9a-f]{64}"), rf"\1{REDACTED}"),
    # X-MBX-APIKEY header value (plain text or dict/JSON repr).
    (
        re.compile(r"(?i)(x-mbx-apikey[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9]{16,}"),
        rf"\1{REDACTED}",
    ),
    # AWS-style access key id.
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), REDACTED),
)


def _url_password(value: str) -> str | None:
    """Return the userinfo password of a URL-shaped value, else None."""
    if "://" not in value:
        return None
    try:
        return urlsplit(value).password
    except ValueError:
        return None


def _variants(value: str) -> set[str]:
    """The value plus its percent-encoded, percent-decoded and JSON-escaped forms."""
    forms = {value, quote(value, safe=""), unquote(value), json.dumps(value)[1:-1]}
    return {form for form in forms if len(form) >= MIN_SECRET_LENGTH}


@dataclass(frozen=True)
class Redactor:
    """Masks secret values (from the environment) and secret shapes in text."""

    _value_pattern: re.Pattern[str] | None

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> Redactor:
        """Collect secret values from ``environ`` and compile one alternation."""
        values: set[str] = set()
        for name, value in environ.items():
            if not value:
                continue
            upper = name.upper()
            if any(part in upper for part in SECRET_ENV_NAME_PARTS):
                values |= _variants(value)
            password = _url_password(value)
            if password:
                values |= _variants(password)
        if not values:
            return cls(None)
        ordered = sorted(values, key=lambda v: (-len(v), v))
        return cls(re.compile("|".join(re.escape(v) for v in ordered)))

    def scrub(self, text: str) -> str:
        """Return ``text`` with secret values and secret shapes replaced."""
        if self._value_pattern is not None:
            text = self._value_pattern.sub(REDACTED, text)
        for pattern, replacement in SHAPE_RULES:
            text = pattern.sub(replacement, text)
        return text


# --------------------------------------------------------------------------- #
# Process-wide active redactor.
# --------------------------------------------------------------------------- #

_active: Redactor | None = None


def _current() -> Redactor:
    """The configured redactor, else one built fresh from the live environment."""
    if _active is not None:
        return _active
    return Redactor.from_environ(os.environ)


def scrub(text: str) -> str:
    """Scrub ``text`` with the configured Redactor (or one built from ``os.environ``)."""
    return _current().scrub(text)


# --------------------------------------------------------------------------- #
# structlog processor.
# --------------------------------------------------------------------------- #

_PRIMITIVES = (int, float, bool, type(None))


def _key_is_secret(key: object) -> bool:
    lowered = str(key).lower().replace("-", "_")
    return any(part in lowered for part in SECRET_KEY_NAME_PARTS)


def _redact_value(redactor: Redactor, value: Any) -> Any:
    if isinstance(value, str):
        return redactor.scrub(value)
    if isinstance(value, _PRIMITIVES):
        return value
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _key_is_secret(key) else _redact_value(redactor, item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(redactor, item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(redactor, item) for item in value)
    if isinstance(value, (set, frozenset)):
        return [_redact_value(redactor, item) for item in sorted(value, key=repr)]
    if isinstance(value, bytes):
        return redactor.scrub(value.decode("utf-8", errors="replace"))
    # Any other object is rendered through repr by the JSON renderer's fallback; keep
    # the object when its repr is clean, otherwise hand back the scrubbed text.
    try:
        rendered = repr(value)
    except Exception:
        return REDACTED
    cleaned = redactor.scrub(rendered)
    return value if cleaned == rendered else cleaned


def redact_processor(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """structlog processor: mask secrets in every value, and by key name.

    Must run AFTER ``structlog.processors.format_exc_info`` (so traceback text is a
    plain string by now) and BEFORE the renderer.
    """
    redactor = _current()
    return {
        key: REDACTED if _key_is_secret(key) else _redact_value(redactor, value)
        for key, value in event_dict.items()
    }


# --------------------------------------------------------------------------- #
# stdlib logging filter.
# --------------------------------------------------------------------------- #


class RedactingFilter(logging.Filter):
    """Scrub the formatted message, arguments and traceback of every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        redactor = _current()
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = redactor.scrub(message)
        record.args = ()
        if record.exc_info and not record.exc_text:
            try:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            except Exception:
                record.exc_text = "(traceback suppressed: formatting failed)"
        if record.exc_text:
            record.exc_text = redactor.scrub(record.exc_text)
        if record.stack_info:
            record.stack_info = redactor.scrub(record.stack_info)
        return True


# --------------------------------------------------------------------------- #
# Global hooks: uncaught exceptions, httpx levels.
# --------------------------------------------------------------------------- #

_HOOK_MARKER = "_gsd_redacting"
_HOOK_ORIGINAL = "_gsd_original"
_NOISY_HTTP_LOGGERS: tuple[str, ...] = ("httpx", "httpcore")


def _write_stderr(text: str) -> None:
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(text)
        stream.flush()
    except Exception:  # pragma: no cover - a broken stderr must not mask the crash
        return


def _format_scrubbed(
    exc_type: type[BaseException],
    exc_value: BaseException | None,
    exc_tb: TracebackType | None,
) -> str:
    try:
        return scrub("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    except Exception:
        # Fail closed: never fall back to unscrubbed output.
        return "uncaught exception (traceback suppressed: redaction failed)\n"


def _make_sys_hook(original: Any) -> Any:
    def hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        _write_stderr(_format_scrubbed(exc_type, exc_value, exc_tb))

    setattr(hook, _HOOK_MARKER, True)
    setattr(hook, _HOOK_ORIGINAL, original)
    return hook


def _make_thread_hook(original: Any) -> Any:
    def hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread is not None else "<unknown>"
        header = scrub(f"Exception in thread {name}:\n")
        _write_stderr(header + _format_scrubbed(args.exc_type, args.exc_value, args.exc_traceback))

    setattr(hook, _HOOK_MARKER, True)
    setattr(hook, _HOOK_ORIGINAL, original)
    return hook


def install_global_hooks(redactor: Redactor | None = None) -> None:
    """Scrub uncaught exceptions (main + worker threads) and quiet httpx URL logging.

    Idempotent: hooks are wrapped once; a later call only swaps the active redactor.
    """
    global _active
    if redactor is not None:
        _active = redactor
    if not getattr(sys.excepthook, _HOOK_MARKER, False):
        sys.excepthook = _make_sys_hook(sys.excepthook)
    if not getattr(threading.excepthook, _HOOK_MARKER, False):
        threading.excepthook = _make_thread_hook(threading.excepthook)
    for name in _NOISY_HTTP_LOGGERS:
        logger = logging.getLogger(name)
        if logger.level == logging.NOTSET or logger.level < logging.WARNING:
            logger.setLevel(logging.WARNING)


def uninstall_global_hooks() -> None:
    """Restore the hooks that were current before ``install_global_hooks`` (tests)."""
    global _active
    if getattr(sys.excepthook, _HOOK_MARKER, False):
        sys.excepthook = getattr(sys.excepthook, _HOOK_ORIGINAL)
    if getattr(threading.excepthook, _HOOK_MARKER, False):
        threading.excepthook = getattr(threading.excepthook, _HOOK_ORIGINAL)
    _active = None


# --------------------------------------------------------------------------- #
# configure_logging.
# --------------------------------------------------------------------------- #

_ROOT_HANDLER_MARKER = "_gsd_redacting_handler"
_ROOT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _attach_filter(handler: logging.Handler) -> None:
    if not any(isinstance(f, RedactingFilter) for f in handler.filters):
        handler.addFilter(RedactingFilter())


def configure_logging(
    environ: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
) -> Redactor:
    """Configure structlog (JSON, redacted) and the stdlib root logger. Idempotent.

    Call first thing in every ``main()`` that runs with secrets in its environment.
    ``stream`` redirects both structlog output and the stdlib root handler (tests);
    by default structlog prints to stdout and stdlib logging writes to stderr.
    Returns the active Redactor.
    """
    redactor = Redactor.from_environ(os.environ if environ is None else environ)
    install_global_hooks(redactor)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=(
            structlog.PrintLoggerFactory(file=stream)
            if stream is not None
            else structlog.PrintLoggerFactory()
        ),
        cache_logger_on_first_use=False,
    )

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _ROOT_HANDLER_MARKER, False):
            root.removeHandler(handler)
    own = logging.StreamHandler(stream if stream is not None else sys.stderr)
    own.setFormatter(logging.Formatter(_ROOT_FORMAT))
    setattr(own, _ROOT_HANDLER_MARKER, True)
    root.addHandler(own)
    for handler in root.handlers:
        _attach_filter(handler)
    return redactor
