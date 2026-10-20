# 16-DEC-LIVENESS-FIRST-FRAME: the paper liveness stamp belongs to one process and records no frame before the first one (plan 16-65), implementation fix

kind: implementation fix of an existing owner decision; NOT a new owner decision
implements: decisions/16-DEC-HUNG-RUNTIME.md (16-55 Q2 = B, correction 2 of 16-DEC-FIXPLANS.md)
related: decisions/16-DEC-WS-WATCHDOG.md (the 120 s bound), decisions/16-DEC-RESTART-POLICY.md (`restart: unless-stopped`)
recorded by: the executor of plan 16-65
date: 2026-10-20
owner values changed: none (health.feed_silence_timeout_seconds stays 120; the heartbeat values 60 / 60 / 120 and the restart policy are unchanged; config/paper/paper-runtime-v2.toml is byte-unchanged)

## Finding (independent review of c654524..6f73e5b, MAJOR)

`_LiveLoop._watch_feed` (src/paper/runtime.py) wrote the liveness stamp at its start with `last_frame_utc` equal to "now", before any market frame had arrived, and nothing removed the stamp when the process ended. Under `restart: unless-stopped`, a runtime that fails deterministically shortly after its start (restore, warm-up, seam check, then a crash, in less than 120 s per cycle) is restarted within about 100 ms and stamps again, so `python -m src.paper.runtime --liveness` always found a fresh stamp and `deploy/heartbeat.sh --target paper` kept sending success pings. The external monitor would never alert. 16-DEC-HUNG-RUNTIME requires the opposite: "The heartbeat must be emitted only while the paper runtime is genuinely healthy."

## Fix (src/paper/liveness.py, src/paper/runtime.py)

1. A stamp of an earlier process never counts for the current one. `main` removes this container's stamp at process start, before any other start step (a removal that fails is exit 7, fail closed), and again in its `finally` on every exit after the instance lease, fail-closed exits included (best effort, a failure is logged). Nothing before the lease writes a stamp. The `--liveness` and `--healthcheck` probes and the one-shot `--pin-epoch` never touch the stamp.
2. The stamp never claims a frame before one arrived. Schema `paper-liveness/2`: `last_frame_utc` is null until the supervisor has seen the first message of this process; the probe then reports "no market message since this process started" (exit 1). A `paper-liveness/1` file is refused as unreadable and never counted. The watchdog's own silence bound is unchanged: it is still measured from the watch start before the first frame.
3. Unchanged: the loop-alive time and the last-frame time keep their meaning once a frame arrived; `--liveness` still exits 0 only when live and 1 otherwise; the held marker still wins over any stamp.

## Residual (accepted, documented)

A process killed without a chance to run its `finally` (kill -9, OOM kill, power loss) leaves its stamp behind. That stamp is no longer refreshed: the probe fails once its loop-alive time is older than the bound, so within at most 120 s, and the next start of the container removes it at once. During that window the heartbeat may still send success pings; with the monitor's period of 60 s and grace of 120 s the alert is delayed by at most the bound, not suppressed.

## Evidence

tests/test_paper_runtime_liveness.py (plan 16-65 section): removal at start (before the loop and during a held refusal) and at exit (fail closed and clean stop); a restart loop of two short-lived runtimes that each reach the watchdog's start stamp and then fail closed never yields a passing probe, neither while running nor after the exit (before the fix the probe passed in all four checks); live after a real frame; not live before the first frame; the old schema is refused.

## Follow-up: only the lease holder owns the stamp (2026-10-20, commit 9b27da5)

Orchestrator decision, owner informed. In 5c866c4 `main` removed the stamp at process start, before the instance lease. A second non-probe start in the same container, refused by the lease with exit 8, therefore deleted the stamp of the running holder until that holder's next watchdog wake (at most half the bound later): a false "not live", never a false "live", but still a stamp touched by a process that does not own it.

Now the removal happens right after the lease is taken (inside the `try` whose `finally` removes the stamp again at the exit); a start refused before the lease or by the lease touches no stamp. Everything else above is unchanged: removal on every exit of the lease holder, no last-frame time before the first frame, the probes and the one-shot pin never touch the stamp, a failed removal at the start is exit 7.

Consequence for a refused start before the lease: a stamp left by an earlier process stays while the refused process holds. It cannot pass the probe during the hold (the held marker of this container wins), and it is only fresh if the earlier process was killed without cleanup, which is the residual above (ages out within the bound, or goes when the next start takes the lease).

Evidence: tests/test_paper_runtime_liveness.py `test_a_start_refused_by_the_lease_leaves_the_holders_stamp_untouched` (with and without the hold; the holder's stamp stays byte-identical and the holder stays live) and `test_a_held_refusal_before_the_lease_touches_no_stamp_and_is_not_live`; both failed before the change.
