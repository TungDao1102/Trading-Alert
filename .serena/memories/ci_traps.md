# CI / repo traps (non-obvious)

- Never commit files named `experiment*.json` or `backtest*.json`; never serialize a `"parameters"`/`"parameters_json"` key next to `parameter_set_id` (registry gate).
- `tests/test_domain_no_float.py` uses an explicit module list: every new money-touching module must be added.
- Tests monkeypatch `src.backtest.simulator.evaluate_risk`; keep the risk call inside `simulator.py`.
- `RejectionReason` enum is pinned at 20 members.
- RESEARCH_PROTOCOL version is pinned in many places (`scripts/decision_alignment/protocol.py`, bookkeeping DC-03, `tests/test_kill_gate_docs.py`, `tests/test_decision_alignment_protocol.py`, `docs/research/holdout_consumed.json`, `docs/DOC_STATUS.md`); a bump changes all in one commit, and its DECISIONS row text is checked.
- Next free DECISIONS id as of 2026-10-04: D052.
- `ruff format` can break frozen single-line hash witnesses; keep them on one line.
- Serena: `.serena/project.yml` and `.serena/.gitignore` are tracked; cache and `project.local.yml` are ignored.
