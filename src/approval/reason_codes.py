"""Plain-string reason codes of the Telegram approval edge (Phase 23).

These are NOT `RejectionReason` members: the enum stays at 21 members and GLOSSARY section 9.1
equals it (gate GL-03). The codes below are plain strings, listed in GLOSSARY section 9.3 (plan
23-13), the pattern of `src/execution/pre_placement.py` and `src/approval/binding.py`.
`DispatchResult.reason_code` accepts `RejectionReason | str | None` for this reason.
"""

from __future__ import annotations

from typing import Final

# The press carries no usable Telegram user id (no `from_user`, or a non-integer id). Same text as
# `src.paper.shadow_confirm.REASON_USER_ID_UNAVAILABLE`.
USER_ID_UNAVAILABLE: Final = "USER_ID_UNAVAILABLE"
# The press came from a chat whose type is not exactly "private" (group, supergroup, channel,
# unknown).
CHAT_NOT_PRIVATE: Final = "CHAT_NOT_PRIVATE"
# The pressing user id is not on the required allow-list.
USER_NOT_AUTHORIZED: Final = "USER_NOT_AUTHORIZED"
# A store or connection failure inside the dispatch (was reported as INVALIDATED before Phase 23).
APPROVAL_STORE_FAILURE: Final = "APPROVAL_STORE_FAILURE"
# The approval was already decided (used by plans 23-07 and 23-11).
ALREADY_DECIDED: Final = "ALREADY_DECIDED"
# The callback handler raised an unexpected error (used by plan 23-07).
CALLBACK_HANDLER_ERROR: Final = "CALLBACK_HANDLER_ERROR"

PHASE23_EDGE_CODES: Final[tuple[str, ...]] = (
    USER_ID_UNAVAILABLE,
    CHAT_NOT_PRIVATE,
    USER_NOT_AUTHORIZED,
    APPROVAL_STORE_FAILURE,
    ALREADY_DECIDED,
    CALLBACK_HANDLER_ERROR,
)

__all__ = [
    "ALREADY_DECIDED",
    "APPROVAL_STORE_FAILURE",
    "CALLBACK_HANDLER_ERROR",
    "CHAT_NOT_PRIVATE",
    "PHASE23_EDGE_CODES",
    "USER_ID_UNAVAILABLE",
    "USER_NOT_AUTHORIZED",
]
