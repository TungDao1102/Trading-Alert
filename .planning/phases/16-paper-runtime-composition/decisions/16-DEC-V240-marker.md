# 16-DEC-V240-marker: the one-field holdout marker edit (block 12 of the v2.4.0 amendment), user decision

block-12-execution: authorized
decided by: user
date: 2026-10-15
words:
authorized

marker_sha256_before: 8360af4184c22397847aa1568ce03a56e78fe38bf4c098ccdb0e6d89131414de

context (recorded for audit): the word above is the user's whole reply (2026-10-15) to the assistant's question whether to allow the one-field `protocol_version` edit of `docs/research/holdout_consumed.json` (quick 261014-nnl plan 09 Task 1, a blocking-human checkpoint). `marker_sha256_before` is the sha256 of `git show HEAD:docs/research/holdout_consumed.json` (HEAD b67a100), computed before the edit.

## Scope of the authorization

Only the value of `protocol_version` in `docs/research/holdout_consumed.json` changes, from `v2.3.0` to `v2.4.0` (one line out, one line in). `schema` (`holdout-consumed/2`) and the empty `entries` array stay as they are. No Holdout data is read. The edit is not committed by this record; the landing commit (plan 09 Task 3) carries it together with the header bump. The user asked for the landing to stay uncommitted until the D071 MOVED list has been shown and approved a second time.

## Not authorized by this record

Any other edit of the marker, manifest freeze, O-03 or 16-46, any Holdout read, any ExperimentRecord, git push.
