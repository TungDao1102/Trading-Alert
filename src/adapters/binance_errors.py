"""SDK exception to `ErrorFacts`: the only SDK-touching file of the error taxonomy.

`error_facts_from_exception` maps an exception raised by the installed Binance
SDK to the triple input of `src.domain.exchange_errors.classify` by
`isinstance` against the `binance_common.errors` classes (research F4, P10).
It exposes the class, the int Binance body code and the Retry-After seconds
only: exception message text is never read, copied or returned, because it may
embed a signed URL or request material (threat T-18-14) and must not be able
to steer a decision (D-10, threat T-18-13).
"""

from __future__ import annotations

from binance_common.errors import (
    BadRequestError,
    ClientError,
    ForbiddenError,
    NetworkError,
    NotFoundError,
    RateLimitBanError,
    ServerError,
    TooManyRequestsError,
    UnauthorizedError,
)
from src.domain.exchange_errors import ErrorFacts, HttpClass

# Classes whose `status_code` is the Binance body code (or None for a non-JSON body).
_BODY_CODE_CLASSES: tuple[tuple[type[BaseException], HttpClass], ...] = (
    (BadRequestError, HttpClass.BAD_REQUEST),
    (UnauthorizedError, HttpClass.UNAUTHORIZED),
    (ForbiddenError, HttpClass.FORBIDDEN),
    (NotFoundError, HttpClass.NOT_FOUND),
    (RateLimitBanError, HttpClass.BANNED_418),
    (TooManyRequestsError, HttpClass.TOO_MANY_429),
)

# Classes that carry no Binance code: `ServerError.status_code` is the HTTP
# status (the 5xx body is discarded by the SDK), `ClientError` (any other 4xx,
# for example 408) is built with no code, `NetworkError` has no attribute.
_NO_CODE_CLASSES: tuple[tuple[type[BaseException], HttpClass], ...] = (
    (ServerError, HttpClass.SERVER_5XX),
    (ClientError, HttpClass.CLIENT_OTHER),
    (NetworkError, HttpClass.NETWORK),
)

_RETRY_AFTER_CLASSES: tuple[type[BaseException], ...] = (RateLimitBanError, TooManyRequestsError)


def _strict_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _retry_after_seconds(exc: BaseException) -> int | None:
    if not isinstance(exc, _RETRY_AFTER_CLASSES):
        return None
    value = _strict_int(getattr(exc, "retry_after", None))
    if value is None or value < 0:
        return None
    return value


def error_facts_from_exception(exc: BaseException) -> ErrorFacts:
    """The (class, int code, retry_after) facts of `exc`; anything else is NON_SDK."""
    for cls, http_class in _BODY_CODE_CLASSES:
        if isinstance(exc, cls):
            return ErrorFacts(
                http_class=http_class,
                code=_strict_int(getattr(exc, "status_code", None)),
                retry_after_seconds=_retry_after_seconds(exc),
            )
    for cls, http_class in _NO_CODE_CLASSES:
        if isinstance(exc, cls):
            return ErrorFacts(http_class=http_class, code=None, retry_after_seconds=None)
    return ErrorFacts(http_class=HttpClass.NON_SDK, code=None, retry_after_seconds=None)


__all__ = ["error_facts_from_exception"]
