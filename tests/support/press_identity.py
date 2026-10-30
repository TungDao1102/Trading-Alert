"""The identity of an allow-listed private press, for tests that call a dispatcher directly.

Review WR-01: `dispatch_callback` (and the `dispatch` wrappers of the desk and the shadow book)
require `from_user_id`, `chat_type` and `authorized_user_ids`; there is no way to skip the user
gate. Tests that drive a dispatcher directly spread `OWNER_PRESS` into the call.
"""

from __future__ import annotations

from typing import Any

OWNER_USER_ID = 4242  # equals the shadow fakes CHAT_ID: a private chat id is the user id

OWNER_PRESS: dict[str, Any] = {
    "from_user_id": OWNER_USER_ID,
    "chat_type": "private",
    "authorized_user_ids": frozenset({OWNER_USER_ID}),
}
