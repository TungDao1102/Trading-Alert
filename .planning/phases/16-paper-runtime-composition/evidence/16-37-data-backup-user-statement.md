# 16-37: off-machine copy of the research dataset (user statement)

date recorded: 2026-10-13
source: user's words in the session; the agent did not see the zip, the cloud location or any number.

## Recorded as stated by the user
- The local data/raw (about 1.6 GB, untracked: .gitignore line 18) was zipped and saved to a cloud store.
- The user checked the integrity of the zip earlier and does not remember the numbers. The user decided not to repeat the check.

## Not established
- That the zip, once extracted, has the 61,665 runner-read files with the listing sha256 b9b8426a31a2821d27d07fc49457cabcdc7cd887910b8185269de3bfa5982b34 (evidence/16-37-data-snapshot.md section 1). An archive integrity test (CRC) shows the archive is not corrupted; it does not show which files it holds.
- Cloud location, zip name and size (not recorded; no secret or link was supplied).

## Consequence
- The local data/raw stays the reference for dataset_id (34a1efa2622b04eca14af58365d5d9d539525e8982c1271e1a9d5b006d18d7d2).
- If the local copy is ever lost, restore from the zip and compare the listing hash before use; a mismatch means the copy is not the registered dataset.
- The EC2 comparison is not applicable (evidence/16-37-ec2-volume-listing.md).
