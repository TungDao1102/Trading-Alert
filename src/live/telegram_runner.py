"""The live Telegram runner: APPROVE -> CONFIRM through `on_callback` only (plan 24-17, D-17, D041).

Phase 24 composes the Telegram half of CONFIRM -> `execute_approved_plan` here. Three rules:

  1. ONE callback handler, and it is `on_callback` (P23-R1, T-24-47). The handler is
     `functools.partial(on_callback, **flow.callback_kwargs(...))`, with the mandatory, non-empty
     `authorized_user_ids`. `dispatch_callback` is never called from `src/live`: it skips the user
     gate when the allow-list is omitted, `on_callback` cannot. The runner takes an application
     FACTORY and never builds one (`build_application`'s docstring forbids it in a unit test; the
     composition root binds the token and `ApplicationBuilder`).
  2. The manual PTB lifecycle of `ShadowRuntime.start/stop` (initialize, start, polling with the
     error callback, an application error handler; stopped in reverse order). Pending updates are
     NOT dropped: a press replayed after a restart is answered from the stored decision, which is
     the safety property (P-5, T-24-48). Exactly one getUpdates consumer may use a bot token, so
     the live process has its own bot (owner answer Q6) and the rule is logged at start.
  3. The store work of a press leaves the loop (R-2, P-1, D-25): the flow is built with
     `run_sync=executor.write`, so `ConfirmBook.handle_confirm` and `ApprovalDesk.dispatch` run on
     the store writer thread; `ExecutionService.on_confirmed` then only schedules the placement
     on the loop with `call_soon_threadsafe`. The CONFIRM recheck is fed by the injected
     `prefetch` coroutine (bound by plan 24-27 to the shared pre-placement read builder).

No order is placed here, no clock is read (the clock is injected) and the stores and the executor
are owned by the caller (the runner never closes the executor).
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Final

import structlog

from src.adapters.telegram_callbacks import (
    JournalReceipt,
    _validate_authorized_user_ids,
    make_application_error_handler,
    on_callback,
)
from src.adapters.telegram_notify import TelegramTextBot
from src.approval.confirm_core import ConfirmProfile, ConfirmStores, MarkPriceFn, RecheckFn
from src.execution.approval_desk import ApprovalDesk
from src.execution.confirm_flow import (
    ConfirmFlow,
    PrefetchFn,
    SleepFn,
    ValidityRule,
    make_confirm_flow,
)
from src.live.execution_service import ExecutionService
from src.ops.store_executor import StoreExecutor

log = structlog.get_logger(__name__)

# The same rule as `src.paper.shadow_runtime.BOT_TOKEN_RULE` (16-DEC-Q-L, RUNBOOK 20.3), restated
# here for the live bot: SHADOW and the live process are two bots (owner answer Q6).
BOT_TOKEN_RULE: Final = (
    "separate-bot: exactly one getUpdates consumer per bot token (16-DEC-Q-L, RUNBOOK 20.3)"
)

#: The runner polls callback queries (the one on_callback handler) and messages (the operator
#: commands of plan 24-23; without "message" a command never reaches the bot, 24-23 hand-off).
ALLOWED_UPDATES: Final = ["callback_query", "message"]

ApplicationFactory = Callable[[], Any]


class LiveTelegramRunner:
    """The live bot: one `on_callback` handler, manual PTB lifecycle, store work off the loop."""

    def __init__(
        self,
        *,
        application_factory: ApplicationFactory,
        desk: ApprovalDesk,
        stores: ConfirmStores,
        profile: ConfirmProfile,
        clock: Callable[[], datetime],
        bot: TelegramTextBot,
        sleep: SleepFn,
        service: ExecutionService,
        executor: StoreExecutor,
        authorized_chat_id: int,
        authorized_user_ids: frozenset[int],
        error_journal: JournalReceipt | None,
        mark_price: MarkPriceFn | None,
        validity_rule: ValidityRule,
        recheck: RecheckFn,
        prefetch: PrefetchFn | None,
        command_handlers: Mapping[str, Callable[..., Awaitable[Any]]] | None = None,
    ) -> None:
        # Fails at construction, not at the first press: an empty allow-list is never allow-all.
        _validate_authorized_user_ids(authorized_user_ids)
        self._application_factory = application_factory
        self._bot = bot
        self._authorized_chat_id = authorized_chat_id
        self._authorized_user_ids = authorized_user_ids
        self._service = service
        self._flow: ConfirmFlow = make_confirm_flow(
            desk=desk,
            profile=profile,
            stores=stores,
            clock=clock,
            bot=bot,
            sleep=sleep,
            mark_price=mark_price,
            validity_rule=validity_rule,
            recheck=recheck,
            on_confirmed=service.on_confirmed,
            prefetch=prefetch,
            run_sync=executor.write,
        )
        self._callback_kwargs: dict[str, Any] = self._flow.callback_kwargs(
            authorized_chat_id=authorized_chat_id,
            authorized_user_ids=authorized_user_ids,
            error_journal=error_journal,
        )
        # The operator commands (plan 24-23 `OperatorCommands.handlers()`): name -> async handler.
        self._command_handlers: dict[str, Callable[..., Awaitable[Any]]] = dict(
            command_handlers or {}
        )
        self._application: Any | None = None
        self._log_application_error = make_application_error_handler()
        self._telegram_errors: dict[str, int] = {}
        self._conflict_logged = False

    # ---- read side ----------------------------------------------------------------------- #

    @property
    def flow(self) -> ConfirmFlow:
        """The confirm flow the handler drives (its book is the live confirm book)."""
        return self._flow

    @property
    def service(self) -> ExecutionService:
        """The execution service whose `on_confirmed` the flow calls (the D-05 gate reads it)."""
        return self._service

    @property
    def handler(self) -> Callable[..., Any]:
        """The one callback handler: `functools.partial(on_callback, **callback_kwargs)`."""
        return functools.partial(on_callback, **self._callback_kwargs)

    @property
    def callback_kwargs(self) -> dict[str, Any]:
        """A copy of the keyword set of the one `on_callback` handler (includes `run_sync`)."""
        return dict(self._callback_kwargs)

    @property
    def telegram_error_counts(self) -> dict[str, int]:
        """Errors that escaped a handler or the polling loop, by exception class name."""
        return dict(self._telegram_errors)

    @property
    def running(self) -> bool:
        return self._application is not None

    # ---- startup hooks -------------------------------------------------------------------- #

    def expire_on_restart(self, now: datetime) -> list[str]:
        """Journal RUNTIME_RESTART for every confirm the previous process left outstanding (D-09).

        Call once at startup, before `start()` (nothing is delivered until polling begins).
        Returns the expired approval ids; a second call returns none. Synchronous: it runs before
        the loop serves any press, so no press is held up by it.
        """
        return self._flow.expire_on_restart(now)

    async def finalize_expired_once(self, now: datetime) -> list[str]:
        """One TTL sweep: expire each confirm past its TTL and edit its card to the final text.

        The body of the scheduler task (plan 24-27 gives it a cadence). Returns the short ids
        whose card was edited; a second call edits nothing.
        """
        return await self._flow.finalize_expired(now)

    # ---- the Telegram application --------------------------------------------------------- #

    async def start(self) -> None:
        """Build the application, register the one handler and start polling in this loop.

        No webhook is configured (getUpdates and a webhook are exclusive) and pending updates are
        kept (`drop_pending_updates=False`): a replay after a restart is answered from the stored
        decision and never places again (T-24-48).
        """
        if self._application is not None:
            raise RuntimeError("the live Telegram runner is already started")
        log.info("live.telegram.bot_token_rule", rule=BOT_TOKEN_RULE)
        application = self._application_factory()
        self._bind_bot(application)
        # PTB is imported here, not at module import: `src.live` stays importable without it.
        from telegram.ext import CallbackQueryHandler

        application.add_handler(CallbackQueryHandler(self.handler))
        if self._command_handlers:
            from telegram.ext import CommandHandler

            for name, command in self._command_handlers.items():
                application.add_handler(CommandHandler(name, command))  # type: ignore[arg-type]
        application.add_error_handler(self._on_application_error)
        await application.initialize()
        try:
            await application.start()
            await application.updater.start_polling(
                allowed_updates=list(ALLOWED_UPDATES),
                drop_pending_updates=False,
                error_callback=self._on_polling_error,
            )
        except BaseException:
            await application.shutdown()
            raise
        self._application = application

    async def stop(self) -> None:
        """Stop the application in the reverse order of `start` (idempotent).

        The store executor is NOT closed here: the composition root owns it and closes it after
        the placement tasks have drained.
        """
        application, self._application = self._application, None
        if application is None:
            return
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

    def _bind_bot(self, application: Any) -> None:
        """Bind a late-bound bot proxy to the application's bot (duck-typed: `is_bound`, `bind`)."""
        application_bot = getattr(application, "bot", None)
        if application_bot is None:
            return
        if getattr(self._bot, "is_bound", True) is False:
            self._bot.bind(application_bot)  # type: ignore[attr-defined]

    # ---- error handling -------------------------------------------------------------------- #

    async def _on_application_error(self, update: object, context: Any) -> None:
        """The application error handler: log the class and the press, count it, change nothing."""
        await self._log_application_error(update, context)
        self._record_telegram_error(getattr(context, "error", None))

    def _on_polling_error(self, error: BaseException) -> None:
        """The synchronous error callback of the updater's getUpdates loop."""
        self._record_telegram_error(error)

    def _record_telegram_error(self, error: BaseException | None) -> None:
        if error is None:
            return
        name = type(error).__name__
        self._telegram_errors[name] = self._telegram_errors.get(name, 0) + 1
        log.warning("live.telegram.error", error_class=name)
        is_conflict = any(cls.__name__ == "Conflict" for cls in type(error).__mro__)
        if is_conflict and not self._conflict_logged:
            self._conflict_logged = True
            log.error("live.telegram.bot_token_conflict", rule=BOT_TOKEN_RULE)


__all__ = [
    "ALLOWED_UPDATES",
    "BOT_TOKEN_RULE",
    "ApplicationFactory",
    "LiveTelegramRunner",
]
