option: runtime-records-replay-inputs
decided by: user
date: 2026-10-10
words: chọn hướng 1
scope: the parity criterion of the trial evaluator (plan 16-25, tolerance zero ratified in D061) is evaluated by replaying recorded inputs. The runtime records, per processed bar, the replay inputs the bundle lacks today (constraint snapshot, account state, open positions, daily loss), and the exporter (plan 16-30) writes them into the bundle.
note: the user chose this after being told it changes the PAPER_BAR_PROCESSED payload and the paper tick or pipeline, which may move pinned digests. That work is a separate gap-closure plan with a digest review; it is not done by this record. Option 2 (a narrower parity definition) was not chosen. Until the plan lands, parity on a real bundle stays NOT EVALUATED and the overall result FAIL (16-25 Known Limitations).
