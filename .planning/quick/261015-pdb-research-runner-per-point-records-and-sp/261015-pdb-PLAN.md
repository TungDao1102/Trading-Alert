# 261015-pdb: runner per-point records and window checkpoints (resume)

User words: "ok theo khuyến nghị, thêm bước ghi kết quả từng điểm".

Scope: `src/research/run.py` (new option `--checkpoint-dir`), `tests/test_research_checkpoint.py`.
Default (no option) = unchanged behaviour. No change to manifest, grid, authorization, no real run, no Holdout.

Design: each simulated window saved (canonical JSON, header with manifest/grid hash, code_version, point, window, body hash); a point's records written right after its five windows (exclusive create via temp file + hard link, existing file must be byte-equal); rerun reuses valid checkpoints; checkpoint dir must not equal or nest with the output dir; checkpoint mode refuses uncommitted changes under src/ and params/ (so saved windows cannot mix code versions).
