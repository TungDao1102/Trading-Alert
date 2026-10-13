# 16-DEC-GAP-REASON: structured terminal declaration for known gaps (plan 16-54, checkpoints KG-1 to KG-4)

All four decisions below were made by the user on 2026-10-13. The user's reply, verbatim:

> Đồng ý cả 4 như khuyến nghị, KG-2.2 none, KG-4.1 host-list

"Khuyến nghị" refers to the assistant's recommendation of the same day, which followed the reviewer's proposal and added two sub-answers. That recommendation is quoted in the section "What the user agreed to" so the words can be audited.

KG1 option: sufficiency-words
KG1 row-policy: required
KG1 decided by: user
KG1 date: 2026-10-13
KG1 words: Đồng ý cả 4 như khuyến nghị, KG-2.2 none, KG-4.1 host-list
KG1 values:
DELISTED_CAPPED: the contract was delivered or delisted; the symbol's data is covered up to its delivery (the word of src/data/sufficiency.py:9)
KG1 note: the user's choice is narrower than the option `sufficiency-words` of the plan. Exactly ONE value is allowed, DELISTED_CAPPED. No TERMINAL, DATA_LOSS or ONBOARD enum is created. The reason is required on every terminal declaration; there is no optional reason. A gap not explained by a valid terminal declaration is refused.

KG2 option: wrapper
KG2 emission: n/a
KG2 version-key: none
KG2 decided by: user
KG2 date: 2026-10-13
KG2 words: Đồng ý cả 4 như khuyến nghị, KG-2.2 none, KG-4.1 host-list
KG2 note: a declaration is a separate manifest-level entry type. GapRange is not changed (six fields, equality, hash, sufficiency report, cutover and case input stay as they are). The declaration is distinct from a real GapRange; it is evidence that a symbol's data ends, not a general licence to skip missing data. Emission is n/a because the reason is required.

KG3 option: declaration-and-geometry
KG3 decided by: user
KG3 date: 2026-10-13
KG3 words: Đồng ý cả 4 như khuyến nghị, KG-2.2 none, KG-4.1 host-list
KG3 rule: one declaration per symbol (REEFUSDT: 1, not 30). In every one of the six builder calls and for every detected gap, the gap is accepted only when ALL of these hold: the symbol matches; the declaration matches; the gap is trailing and runs to exactly the end of the current window; its start is on the series cadence at or after terminal_at_utc; there is no data after the gap start inside the window; the number of missing bars equals the count computed from the data geometry; and no interior gap is accepted. A check of only `terminal_at_utc <= gap.start_utc` is not enough. The gap start is NOT forced to be the same instant across series (for REEFUSDT the 4h and funding series can start missing at 12:00Z). Data-loss and reason-less entries keep the exact six-field match.

KG4 option: inline
KG4 source-validation: host-list
KG4 hosts: www.binance.com
KG4 decided by: user
KG4 date: 2026-10-13
KG4 words: Đồng ý cả 4 như khuyến nghị, KG-2.2 none, KG-4.1 host-list
KG4 rule: terminal_at_utc, the exact source URL and the cause are fields of the declaration inside the manifest, so all of them are covered by the manifest hash. They are not recorded only in a decision file. Source validation is shape (https, non-empty host, no user information, no whitespace) plus the host must be `www.binance.com`; nothing is fetched. A URL or terminal time that cannot be verified against the saved evidence leaves the checkpoint open.

## What the user agreed to (recommendation of 2026-10-13, for audit)
KG-1 reuse DELISTED_CAPPED, required. KG-2 wrapper; KG-2.2 version key none (no manifest or hash is committed yet). KG-3 one declaration per symbol with the reviewer's geometry conditions. KG-4 inline in the manifest; KG-4.1 host-list with www.binance.com only.

## Still open (not decided here)
- The REEFUSDT values themselves: terminal_at_utc (expected 2025-01-22T09:00:00Z) and the exact URL (evidence/16-37-constraint-history.md line 67). The page content reached us as a fetch-tool summary, not a verbatim copy; the local data is consistent with 09:00 but does not prove it. The user was asked to open the URL and confirm; until then plan 16-37 Task 3 must not write these values into a manifest. They are the user's O-03b answer.
- Cross-family multiplicity, the protocol amendment for the constraint assumption, the local/EC2 data comparison, O-03 authorization. This record grants no research execution.
