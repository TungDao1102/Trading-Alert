# 16-37: EC2 volume trading_rawdata listing (user-run, read-only)

date recorded: 2026-10-13
run by: user on the EC2 host (/opt/trading), output pasted into the session; the agent did not run it.

## What was run
`docker run --rm --network none -v trading_rawdata:/data/raw:ro --entrypoint sh trading-alert-ops:dev -c 'ls -la /data/raw | head -30; echo ---; find /data/raw -maxdepth 3 -type d | head -40; echo ---; find /data/raw -type f | wc -l'`
Volume name `trading_rawdata` and images `trading-alert-ops:dev|rollback`, `trading-alert:dev|rollback` exist (as the user's output shows).

## What the output shows (as pasted)
- `/data/raw` holds only two top-level directories: `data_class=funding` and `data_class=oi`, both created Oct 3 03:26.
- The visible funding partitions (the first 40 directory lines, head-limited) are for dates 2026-10-03 to 2026-10-13; symbols seen include NEARUSDT, BNBUSDT, XRPUSDT, WIFUSDT (more symbols exist, 20 entries per class, output was cut by head).
- There is no `interval=1m`, `interval=1h`, `interval=4h` or `dataset=mark_klines` directory.
- Total files in the volume: 27,970.

## Consequence
- The EC2 volume is the collector's live store since 2026-10-03: funding and open interest only. It holds no trade or mark klines and nothing before 2026-10-03.
- It therefore cannot be compared with the local research dataset (61,665 listed files, 2024-10-03..2026-10-02). The first sha256 command found no directory to list; the output file it wrote is empty or partial and is not evidence.
- The local `data/raw` is the only copy of the research dataset. Its listing (sha256 b9b8426a31a2821d27d07fc49457cabcdc7cd887910b8185269de3bfa5982b34, 61,665 lines) and the derived dataset_id (34a1efa2622b04eca14af58365d5d9d539525e8982c1271e1a9d5b006d18d7d2) in evidence/16-37-data-snapshot.md stay the reference.
- Not established: whether the local dataset has an independent copy anywhere (backup, second machine). No decision on this is recorded here.
