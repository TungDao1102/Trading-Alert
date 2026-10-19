# 16-DEC-RERUN-PARALLEL: the three 2.3.0 families run at the same time

decided by: user
date: 2026-10-19

words:
> chạy song song đi, tôi sẽ rời đi bây giờ, bạn hãy xem cần tôi cung cấp gì không trước khi tôi rời đi, hãy monitor giúp tôi, nếu có vấn đề gì cần quyết định mà không quá quan trọng thì bạn hãy tự xử lý giúp tôi. mong muốn của tôi là sáng mai sẽ xong để làm việc khác

Context shown to the owner before this line (2026-10-19): on 2026-10-15 the owner asked for three processes at once and run 1 ran that way without an error (one process per grid file, about 15 to 35 minutes per point in parallel, free RAM fell from about 8.5 GiB to 4.6 GiB); the reviewer text adopted on 2026-10-16 says "sequential" and plan 16-63 Task 6 repeated it. The owner now chooses parallel.

This replaces, for the 2.3.0 rerun only, the sequential rule of `decisions/16-DEC-FIXPLANS-reviewer-text.md` ("### Sequential or parallel runs") and the sentences of 16-63 Task 6 that say "one family at a time". It changes nothing else: the same 3 families, 48 parameter sets and 5 windows; the same owner-signed authorization files; no Holdout; no parameter, grid, manifest or `strategy_version` change.

Orchestrator choices under "decide minor matters for me" (recorded, not owner words):
- Start order trend-pullback, breakout-retest, range-mr, one process per grid file, each with its own checkpoint directory outside the repository.
- No other heavy process (full suite, another plan, a second agent running tests) runs while the three families run.
- Free memory is watched; if it falls under about 1.5 GiB the orchestrator stops the family that started last, keeps its checkpoint, and restarts it after another family ends (the checkpoint makes the resume safe); no record is edited.
- If a family exits non-zero, the other two keep running; nothing is changed to make it pass; the rerun is not labelled complete; a technical report follows.
- The machine is kept awake while the runs are going (no change to power settings, only a keep-awake request from a helper process).
- Intermediate performance sections are not read.
