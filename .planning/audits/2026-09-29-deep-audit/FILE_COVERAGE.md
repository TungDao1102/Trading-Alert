# FILE COVERAGE — aggregated by tmp/merge.py from each lane's Coverage table

Level = strongest level any lane recorded (DEEP_READ > NORMAL_READ > METADATA_ONLY > EXCLUDED). Files no lane listed are counted EXCLUDED (not relied upon).

| Level | Files |
|---|---|
| DEEP_READ | 120 |
| NORMAL_READ | 218 |
| METADATA_ONLY | 254 |
| EXCLUDED | 47 |

| Category | DEEP_READ | NORMAL_READ | METADATA_ONLY | EXCLUDED |
|---|---|---|---|---|
| ci | 3 | 0 | 0 | 0 |
| config | 3 | 2 | 0 | 1 |
| config-params | 10 | 0 | 0 | 0 |
| doc | 24 | 5 | 2 | 2 |
| infra | 2 | 0 | 0 | 0 |
| migration | 4 | 0 | 2 | 0 |
| planning | 32 | 103 | 43 | 44 |
| script | 3 | 3 | 7 | 0 |
| source | 36 | 27 | 37 | 0 |
| test | 2 | 25 | 66 | 0 |
| test-fixture | 1 | 53 | 97 | 0 |

| File | Category | Level | Lanes |
|---|---|---|---|
| `.env.example` | config | DEEP_READ | data_database_concurrency, requirements_docs_plan, security_reliability  |
| `.gitattributes` | config | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.github/workflows/paper_freeze_check.yml` | ci | DEEP_READ | requirements_docs_plan, testing_verification  |
| `.github/workflows/registry-gate.yml` | ci | DEEP_READ | requirements_docs_plan, testing_verification  |
| `.github/workflows/research-gate.yml` | ci | DEEP_READ | requirements_docs_plan, testing_verification  |
| `.gitignore` | config | DEEP_READ | security_reliability  |
| `.planning/PROJECT.md` | planning | DEEP_READ | requirements_docs_plan  |
| `.planning/REQUIREMENTS.md` | planning | DEEP_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/ROADMAP.md` | planning | DEEP_READ | business_invariants, docs_trading_soundness, historical_regression, planning_decisions_01_06, planning_decisions_07_17, requirements_docs_plan  |
| `.planning/STATE.md` | planning | NORMAL_READ | historical_regression, requirements_docs_plan  |
| `.planning/config.json` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/intel/API-SURFACE.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/milestone.lock` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/01-research-formalization/01-01-PLAN.md` | planning | METADATA_ONLY | planning_decisions_01_06  |
| `.planning/phases/01-research-formalization/01-01-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/01-research-formalization/01-02-PLAN.md` | planning | METADATA_ONLY | planning_decisions_01_06  |
| `.planning/phases/01-research-formalization/01-02-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/01-research-formalization/01-03-PLAN.md` | planning | METADATA_ONLY | planning_decisions_01_06  |
| `.planning/phases/01-research-formalization/01-03-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/01-research-formalization/01-04-PLAN.md` | planning | METADATA_ONLY | planning_decisions_01_06  |
| `.planning/phases/01-research-formalization/01-04-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/01-research-formalization/01-04-negative-test-GREEN.txt` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/01-research-formalization/01-04-negative-test-RED.txt` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/01-research-formalization/01-CONTEXT.md` | planning | DEEP_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/01-research-formalization/01-DISCUSSION-LOG.md` | planning | DEEP_READ | planning_decisions_01_06  |
| `.planning/phases/01-research-formalization/01-PATTERNS.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/01-research-formalization/01-RESEARCH.md` | planning | DEEP_READ | planning_decisions_01_06  |
| `.planning/phases/01-research-formalization/01-VALIDATION.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/01-research-formalization/01-VERIFICATION.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/01-research-formalization/COVERAGE.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/02-data-foundation/02-01-PLAN.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-01-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/02-data-foundation/02-02-PLAN.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-02-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/02-data-foundation/02-03-PLAN.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-03-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/02-data-foundation/02-04-PLAN.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-04-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/02-data-foundation/02-05-PLAN.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-05-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/02-data-foundation/02-CONTEXT.md` | planning | DEEP_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/02-data-foundation/02-DISCUSSION-LOG.md` | planning | DEEP_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-PATTERNS.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/02-data-foundation/02-RESEARCH.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-REVIEW-FIX.iter2.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-REVIEW-FIX.iter3.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-REVIEW-FIX.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-REVIEW.iter2.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-REVIEW.iter3.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-REVIEW.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/02-data-foundation/02-VALIDATION.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/02-data-foundation/02-VERIFICATION.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/02-data-foundation/COVERAGE.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/03-domain-registry-fixtures/03-01-PLAN.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/03-domain-registry-fixtures/03-01-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/03-domain-registry-fixtures/03-02-PLAN.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/03-domain-registry-fixtures/03-02-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/03-domain-registry-fixtures/03-03-PLAN.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/03-domain-registry-fixtures/03-03-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/03-domain-registry-fixtures/03-04-PLAN.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/03-domain-registry-fixtures/03-04-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/03-domain-registry-fixtures/03-05-PLAN.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/03-domain-registry-fixtures/03-05-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/03-domain-registry-fixtures/03-CONTEXT.md` | planning | DEEP_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/03-domain-registry-fixtures/03-DISCUSSION-LOG.md` | planning | DEEP_READ | planning_decisions_01_06  |
| `.planning/phases/03-domain-registry-fixtures/03-PATTERNS.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/03-domain-registry-fixtures/03-RESEARCH.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/03-domain-registry-fixtures/03-REVIEW-FIX.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/03-domain-registry-fixtures/03-REVIEW.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/03-domain-registry-fixtures/03-UAT.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/03-domain-registry-fixtures/03-VALIDATION.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/03-domain-registry-fixtures/03-VERIFICATION.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-01-PLAN.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-01-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-02-PLAN.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-02-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-03-PLAN.md` | planning | NORMAL_READ | historical_regression, planning_decisions_01_06  |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-03-SUMMARY.md` | planning | NORMAL_READ | historical_regression, planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-04-PLAN.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-04-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-CONTEXT.md` | planning | DEEP_READ | planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-DISCUSSION-LOG.md` | planning | DEEP_READ | planning_decisions_01_06  |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-PATTERNS.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-RESEARCH.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-REVIEW-FIX.md` | planning | NORMAL_READ | historical_regression, planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-REVIEW.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-VALIDATION.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/04-pure-core-feature-strategy-planner/04-VERIFICATION.md` | planning | NORMAL_READ | historical_regression, requirements_docs_plan  |
| `.planning/phases/05-risk-engine/05-01-PLAN.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/05-risk-engine/05-01-SUMMARY.md` | planning | NORMAL_READ | historical_regression, requirements_docs_plan  |
| `.planning/phases/05-risk-engine/05-02-PLAN.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/05-risk-engine/05-02-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/05-risk-engine/05-CONTEXT.md` | planning | DEEP_READ | historical_regression, planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/05-risk-engine/05-DISCUSSION-LOG.md` | planning | DEEP_READ | planning_decisions_01_06  |
| `.planning/phases/05-risk-engine/05-PATTERNS.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/05-risk-engine/05-RESEARCH.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/05-risk-engine/05-REVIEW-FIX.md` | planning | NORMAL_READ | historical_regression, planning_decisions_01_06  |
| `.planning/phases/05-risk-engine/05-REVIEW.md` | planning | NORMAL_READ | historical_regression, planning_decisions_01_06  |
| `.planning/phases/05-risk-engine/05-VALIDATION.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/05-risk-engine/05-VERIFICATION.md` | planning | NORMAL_READ | historical_regression, requirements_docs_plan  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-01-PLAN.md` | planning | DEEP_READ | historical_regression, planning_decisions_01_06  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-01-SUMMARY.md` | planning | DEEP_READ | historical_regression, requirements_docs_plan  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-02-PLAN.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-02-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-03-PLAN.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-03-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-CONTEXT.md` | planning | DEEP_READ | historical_regression, planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-DISCUSSION-LOG.md` | planning | NORMAL_READ | planning_decisions_01_06  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-PATTERNS.md` | planning | DEEP_READ | historical_regression  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-RESEARCH.md` | planning | DEEP_READ | historical_regression, planning_decisions_01_06  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-REVIEW-FIX.md` | planning | DEEP_READ | historical_regression, planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-REVIEW.md` | planning | DEEP_READ | historical_regression, planning_decisions_01_06  |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-VALIDATION.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/06-backtest-simulator-experiment-registry/06-VERIFICATION.md` | planning | DEEP_READ | historical_regression, planning_decisions_01_06, requirements_docs_plan  |
| `.planning/phases/06-backtest-simulator-experiment-registry/COVERAGE.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/07-paper-forward-observation/07-01-PLAN.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/07-paper-forward-observation/07-01-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/07-paper-forward-observation/07-02-PLAN.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/07-paper-forward-observation/07-02-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/07-paper-forward-observation/07-03-PLAN.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/07-paper-forward-observation/07-03-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/07-paper-forward-observation/07-04-PLAN.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/07-paper-forward-observation/07-04-SUMMARY.md` | planning | NORMAL_READ | requirements_docs_plan  |
| `.planning/phases/07-paper-forward-observation/07-CONTEXT.md` | planning | DEEP_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/07-paper-forward-observation/07-DISCUSSION-LOG.md` | planning | DEEP_READ | planning_decisions_07_17  |
| `.planning/phases/07-paper-forward-observation/07-PATTERNS.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/07-paper-forward-observation/07-RESEARCH.md` | planning | NORMAL_READ | planning_decisions_07_17  |
| `.planning/phases/07-paper-forward-observation/07-REVIEW-FIX.md` | planning | NORMAL_READ | planning_decisions_07_17  |
| `.planning/phases/07-paper-forward-observation/07-REVIEW.md` | planning | NORMAL_READ | planning_decisions_07_17  |
| `.planning/phases/07-paper-forward-observation/07-USER-SETUP.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/07-paper-forward-observation/07-VALIDATION.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/07-paper-forward-observation/COVERAGE.md` | planning | NORMAL_READ | planning_decisions_07_17  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-01-PLAN.md` | planning | NORMAL_READ | historical_regression, planning_decisions_07_17  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-01-SUMMARY.md` | planning | NORMAL_READ | historical_regression, planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-02-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-02-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-CONTEXT.md` | planning | DEEP_READ | planning_decisions_07_17  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-DISCUSSION-LOG.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-PATTERNS.md` | planning | NORMAL_READ | planning_decisions_07_17  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-RESEARCH.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-REVIEW-FIX.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-REVIEW.md` | planning | NORMAL_READ | historical_regression, planning_decisions_07_17  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-VALIDATION.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/07.1-VERIFICATION.md` | planning | NORMAL_READ | historical_regression, planning_decisions_07_17  |
| `.planning/phases/07.1-close-gap-b1-registry-cost-to-backtest-identity-binding/COVERAGE.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/08-approval-reconciliation-hardening/08-01-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/08-approval-reconciliation-hardening/08-01-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/08-approval-reconciliation-hardening/08-02-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/08-approval-reconciliation-hardening/08-02-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/08-approval-reconciliation-hardening/08-03-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/08-approval-reconciliation-hardening/08-03-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/08-approval-reconciliation-hardening/08-04-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/08-approval-reconciliation-hardening/08-04-SUMMARY.md` | planning | NORMAL_READ | integrations_external_apis, planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/08-approval-reconciliation-hardening/08-05-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/08-approval-reconciliation-hardening/08-05-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/08-approval-reconciliation-hardening/08-CONTEXT.md` | planning | DEEP_READ | planning_decisions_07_17, requirements_docs_plan, security_reliability  |
| `.planning/phases/08-approval-reconciliation-hardening/08-DISCUSSION-LOG.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/08-approval-reconciliation-hardening/08-PATTERNS.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/08-approval-reconciliation-hardening/08-RESEARCH.md` | planning | NORMAL_READ | planning_decisions_07_17  |
| `.planning/phases/08-approval-reconciliation-hardening/08-REVIEW-FIX.md` | planning | NORMAL_READ | historical_regression, planning_decisions_07_17  |
| `.planning/phases/08-approval-reconciliation-hardening/08-REVIEW.md` | planning | NORMAL_READ | historical_regression, integrations_external_apis, planning_decisions_07_17, security_reliability  |
| `.planning/phases/08-approval-reconciliation-hardening/08-VALIDATION.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/08-approval-reconciliation-hardening/COVERAGE.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/09-live-execution-rollout/09-01-PLAN.md` | planning | NORMAL_READ | planning_decisions_07_17  |
| `.planning/phases/09-live-execution-rollout/09-01-SUMMARY.md` | planning | NORMAL_READ | historical_regression, planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/09-live-execution-rollout/09-02-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/09-live-execution-rollout/09-02-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/09-live-execution-rollout/09-03-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/09-live-execution-rollout/09-03-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/09-live-execution-rollout/09-04-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/09-live-execution-rollout/09-04-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/09-live-execution-rollout/09-CONTEXT.md` | planning | DEEP_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/09-live-execution-rollout/09-DISCUSSION-LOG.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/09-live-execution-rollout/09-PATTERNS.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/09-live-execution-rollout/09-RESEARCH.md` | planning | NORMAL_READ | planning_decisions_07_17  |
| `.planning/phases/09-live-execution-rollout/09-REVIEW-DISPOSITION.md` | planning | DEEP_READ | historical_regression, planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/09-live-execution-rollout/09-REVIEW-FIX.md` | planning | NORMAL_READ | historical_regression, integrations_external_apis, planning_decisions_07_17, requirements_docs_plan, security_reliability  |
| `.planning/phases/09-live-execution-rollout/09-REVIEW.md` | planning | NORMAL_READ | historical_regression, integrations_external_apis, planning_decisions_07_17, security_reliability  |
| `.planning/phases/09-live-execution-rollout/09-VALIDATION.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/09-live-execution-rollout/COVERAGE.md` | planning | NORMAL_READ | planning_decisions_07_17  |
| `.planning/phases/09-live-execution-rollout/deferred-items.md` | planning | DEEP_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-01-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-01-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-02-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-02-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-03-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-03-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-04-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-04-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-05-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-05-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-06-PLAN.md` | planning | NORMAL_READ | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-06-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-07-PLAN.md` | planning | NORMAL_READ | historical_regression, planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-07-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-08-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-08-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-09-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-09-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-10-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-10-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-11-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-11-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-12-PLAN.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-12-SUMMARY.md` | planning | NORMAL_READ | planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-CONTEXT.md` | planning | DEEP_READ | historical_regression, planning_decisions_07_17, requirements_docs_plan  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-DISCUSSION-LOG.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-PATTERNS.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-RESEARCH.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-REVIEW-DISPOSITION.md` | planning | DEEP_READ | planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-REVIEW-FIX.md` | planning | NORMAL_READ | historical_regression, planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-REVIEW.md` | planning | NORMAL_READ | historical_regression, planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-UI-SPEC.md` | planning | NORMAL_READ | historical_regression, planning_decisions_07_17  |
| `.planning/phases/10-journal-depth-kill-gate-operations/10-VALIDATION.md` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/11-fee-units-and-real-commission/.gitkeep` | planning | METADATA_ONLY | planning_decisions_07_17  |
| `.planning/phases/12-account-equity-from-binance/.gitkeep` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/13-leverage-margin-liquidation-guard/.gitkeep` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/14-available-margin-check/.gitkeep` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/15-pre-placement-price-check/.gitkeep` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/16-notification-money-amounts/.gitkeep` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/phases/17-configurable-quote-asset/.gitkeep` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/research/ARCHITECTURE.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/research/FEATURES.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/research/PITFALLS.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/research/STACK.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/research/SUMMARY.md` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/state.json` | planning | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `.planning/v0.3-MILESTONE-AUDIT.md` | planning | DEEP_READ | historical_regression, integrations_external_apis, planning_decisions_01_06, planning_decisions_07_17, requirements_docs_plan, testing_verification  |
| `AGENTS.md` | doc | DEEP_READ | docs_exchange_facts, requirements_docs_plan  |
| `Dockerfile` | infra | DEEP_READ | architecture_code, requirements_docs_plan, security_reliability  |
| `alembic.ini` | config | NORMAL_READ | data_database_concurrency  |
| `docker-compose.yml` | infra | DEEP_READ | architecture_code, requirements_docs_plan, security_reliability  |
| `docs/00_PRODUCT_SCOPE.md` | doc | DEEP_READ | docs_trading_soundness, requirements_docs_plan  |
| `docs/01_ENGINEERING_PRINCIPLES.md` | doc | DEEP_READ | docs_trading_soundness  |
| `docs/DECISIONS.md` | doc | DEEP_READ | docs_trading_soundness, planning_decisions_07_17, requirements_docs_plan  |
| `docs/DOC_STATUS.md` | doc | DEEP_READ | requirements_docs_plan  |
| `docs/GLOSSARY.md` | doc | DEEP_READ | docs_trading_soundness, requirements_docs_plan  |
| `docs/README.md` | doc | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `docs/SOURCES.md` | doc | DEEP_READ | docs_exchange_facts  |
| `docs/TECHNOLOGY_STACK.md` | doc | DEEP_READ | docs_exchange_facts, requirements_docs_plan  |
| `docs/architecture/ARCHITECTURE.md` | doc | METADATA_ONLY | requirements_docs_plan  |
| `docs/architecture/DATA_PIPELINE.md` | doc | NORMAL_READ | docs_trading_soundness, requirements_docs_plan  |
| `docs/backtest/BACKTEST_SPEC.md` | doc | DEEP_READ | docs_trading_soundness, requirements_docs_plan  |
| `docs/backtest/METRICS.md` | doc | DEEP_READ | docs_trading_soundness  |
| `docs/configuration/CONFIGURATION.md` | doc | DEEP_READ | docs_trading_soundness, historical_regression, requirements_docs_plan  |
| `docs/data/DATA_MODEL.md` | doc | DEEP_READ | data_database_concurrency, docs_trading_soundness, requirements_docs_plan  |
| `docs/implementation/AGENT_INSTRUCTIONS.md` | doc | EXCLUDED |  no lane recorded it (see category defaults in report §3) |
| `docs/implementation/IMPLEMENTATION_PLAN.md` | doc | DEEP_READ | docs_trading_soundness, requirements_docs_plan  |
| `docs/integration/BINANCE.md` | doc | DEEP_READ | docs_exchange_facts, docs_trading_soundness, integrations_external_apis  |
| `docs/integration/TELEGRAM.md` | doc | DEEP_READ | business_invariants, docs_exchange_facts, docs_trading_soundness, integrations_external_apis, requirements_docs_plan, security_reliability  |
| `docs/integration/TRADINGVIEW.md` | doc | DEEP_READ | docs_exchange_facts, docs_trading_soundness, integrations_external_apis  |
| `docs/operations/RUNBOOK.md` | doc | DEEP_READ | docs_trading_soundness, requirements_docs_plan, security_reliability  |
| `docs/operations/SECURITY_AND_OPERATIONS.md` | doc | DEEP_READ | docs_trading_soundness, requirements_docs_plan, security_reliability  |
| `docs/research/RESEARCH_PROTOCOL.md` | doc | DEEP_READ | docs_trading_soundness, planning_decisions_01_06, requirements_docs_plan  |
| `docs/research/TRADING_STRATEGY_RESEARCH.md` | doc | NORMAL_READ | docs_trading_soundness  |
| `docs/research/families/breakout-retest.md` | doc | NORMAL_READ | docs_trading_soundness, requirements_docs_plan  |
| `docs/research/families/range-mr.md` | doc | NORMAL_READ | docs_trading_soundness, requirements_docs_plan  |
| `docs/research/families/trend-pullback.md` | doc | DEEP_READ | business_invariants, docs_trading_soundness, planning_decisions_01_06, requirements_docs_plan  |
| `docs/research/kill_gate_decisions.json` | doc | METADATA_ONLY | docs_trading_soundness  |
| `docs/strategy/TRADING_STRATEGY_SPEC.md` | doc | DEEP_READ | docs_trading_soundness  |
| `docs/testing/TESTING_STRATEGY.md` | doc | NORMAL_READ | requirements_docs_plan  |
| `docs/trading/EXECUTION_SPEC.md` | doc | DEEP_READ | docs_exchange_facts, docs_trading_soundness, requirements_docs_plan  |
| `docs/trading/RISK_MANAGEMENT.md` | doc | DEEP_READ | docs_exchange_facts, docs_trading_soundness, planning_decisions_01_06, requirements_docs_plan  |
| `docs/trading/SIGNAL_AND_ALERTS.md` | doc | DEEP_READ | docs_trading_soundness, requirements_docs_plan  |
| `params/breakout-retest/baseline-v1.toml` | config-params | DEEP_READ | business_invariants, docs_exchange_facts, docs_trading_soundness, historical_regression, planning_decisions_07_17, requirements_docs_plan  |
| `params/breakout-retest/baseline-v2.toml` | config-params | DEEP_READ | business_invariants, docs_exchange_facts, docs_trading_soundness, planning_decisions_07_17, requirements_docs_plan  |
| `params/breakout-retest/baseline-v3.toml` | config-params | DEEP_READ | business_invariants, docs_exchange_facts, docs_trading_soundness, historical_regression, planning_decisions_07_17, requirements_docs_plan  |
| `params/range-mr/baseline-v1.toml` | config-params | DEEP_READ | business_invariants, docs_exchange_facts, docs_trading_soundness, historical_regression, planning_decisions_07_17, requirements_docs_plan  |
| `params/range-mr/baseline-v2.toml` | config-params | DEEP_READ | business_invariants, docs_exchange_facts, docs_trading_soundness, planning_decisions_07_17, requirements_docs_plan  |
| `params/trend-pullback/baseline-no-trade-v1.toml` | config-params | DEEP_READ | business_invariants, docs_exchange_facts, docs_trading_soundness, planning_decisions_07_17, requirements_docs_plan  |
| `params/trend-pullback/baseline-simple-trend-v1.toml` | config-params | DEEP_READ | business_invariants, docs_exchange_facts, docs_trading_soundness, planning_decisions_07_17, requirements_docs_plan  |
| `params/trend-pullback/baseline-v1.toml` | config-params | DEEP_READ | business_invariants, docs_exchange_facts, docs_trading_soundness, historical_regression, planning_decisions_01_06, planning_decisions_07_17, requirements_docs_plan  |
| `params/trend-pullback/baseline-v2.toml` | config-params | DEEP_READ | business_invariants, docs_exchange_facts, docs_trading_soundness, planning_decisions_07_17, requirements_docs_plan  |
| `params/trend-pullback/baseline-v3.toml` | config-params | DEEP_READ | business_invariants, docs_exchange_facts, docs_trading_soundness, historical_regression, planning_decisions_01_06, planning_decisions_07_17, requirements_docs_plan  |
| `pyproject.toml` | config | DEEP_READ | architecture_code, docs_exchange_facts, requirements_docs_plan, security_reliability, testing_verification  |
| `scripts/_compute_phase4_fixtures.py` | script | METADATA_ONLY | architecture_code  |
| `scripts/_extend_phase4_candles.py` | script | METADATA_ONLY | architecture_code  |
| `scripts/_regen_phase4_expectations.py` | script | NORMAL_READ | architecture_code, historical_regression, testing_verification  |
| `scripts/backup-drill.ps1` | script | DEEP_READ | architecture_code, security_reliability  |
| `scripts/check_migration_parity.py` | script | DEEP_READ | architecture_code, data_database_concurrency, testing_verification  |
| `scripts/dev/README.md` | script | METADATA_ONLY | architecture_code  |
| `scripts/dev/_common.ps1` | script | METADATA_ONLY | architecture_code  |
| `scripts/dev/clean.ps1` | script | METADATA_ONLY | architecture_code  |
| `scripts/dev/journal-report.ps1` | script | NORMAL_READ | architecture_code, historical_regression  |
| `scripts/dev/migrate.ps1` | script | NORMAL_READ | architecture_code, data_database_concurrency  |
| `scripts/dev/pytest_timing.py` | script | METADATA_ONLY | architecture_code  |
| `scripts/dev/test.ps1` | script | METADATA_ONLY | architecture_code  |
| `scripts/gen_phase6_fixtures.py` | script | DEEP_READ | architecture_code, testing_verification  |
| `src/__init__.py` | source | METADATA_ONLY | architecture_code  |
| `src/adapters/analytics_files.py` | source | METADATA_ONLY | architecture_code  |
| `src/adapters/analytics_store.py` | source | DEEP_READ | architecture_code, data_database_concurrency  |
| `src/adapters/binance_usdm.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, docs_exchange_facts, integrations_external_apis, planning_decisions_07_17, requirements_docs_plan, security_reliability  |
| `src/adapters/paper_ws.py` | source | DEEP_READ | architecture_code, data_database_concurrency, docs_exchange_facts, integrations_external_apis, planning_decisions_07_17, testing_verification  |
| `src/adapters/telegram_callbacks.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, integrations_external_apis, security_reliability  |
| `src/adapters/telegram_notify.py` | source | DEEP_READ | architecture_code, business_invariants, integrations_external_apis, requirements_docs_plan, security_reliability, testing_verification  |
| `src/analytics/__init__.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/approval_delay.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/cli.py` | source | NORMAL_READ | architecture_code, historical_regression  |
| `src/analytics/clock.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/core_metrics.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/excursion.py` | source | NORMAL_READ | architecture_code, business_invariants, historical_regression  |
| `src/analytics/family.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/gates.py` | source | NORMAL_READ | architecture_code, business_invariants, planning_decisions_07_17  |
| `src/analytics/inputs.py` | source | NORMAL_READ | architecture_code, historical_regression  |
| `src/analytics/killgate.py` | source | METADATA_ONLY | architecture_code, business_invariants  |
| `src/analytics/latency.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/lifecycle.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/live_outcomes.py` | source | NORMAL_READ | architecture_code, business_invariants  |
| `src/analytics/no_trade.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/provenance.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/render.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/render_common.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/render_killgate.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/render_metrics.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/render_sidecar.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/report.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/slices.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/stats.py` | source | METADATA_ONLY | architecture_code, business_invariants  |
| `src/analytics/types.py` | source | METADATA_ONLY | architecture_code  |
| `src/analytics/universe.py` | source | METADATA_ONLY | architecture_code  |
| `src/approval/__init__.py` | source | METADATA_ONLY | architecture_code  |
| `src/approval/binding.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, planning_decisions_07_17, security_reliability  |
| `src/approval/mapping.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, security_reliability  |
| `src/approval/replay.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, security_reliability, testing_verification  |
| `src/approval/tokens.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, security_reliability  |
| `src/backtest/__init__.py` | source | METADATA_ONLY | architecture_code  |
| `src/backtest/binding.py` | source | METADATA_ONLY | architecture_code  |
| `src/backtest/costs.py` | source | DEEP_READ | architecture_code, business_invariants, historical_regression, testing_verification  |
| `src/backtest/experiment.py` | source | NORMAL_READ | architecture_code, business_invariants, requirements_docs_plan  |
| `src/backtest/report.py` | source | NORMAL_READ | architecture_code, requirements_docs_plan  |
| `src/backtest/simulator.py` | source | DEEP_READ | architecture_code, business_invariants, historical_regression, planning_decisions_01_06, planning_decisions_07_17, requirements_docs_plan  |
| `src/core/__init__.py` | source | METADATA_ONLY | architecture_code  |
| `src/core/_decimal.py` | source | NORMAL_READ | architecture_code, business_invariants, data_database_concurrency  |
| `src/core/features.py` | source | NORMAL_READ | architecture_code, business_invariants, planning_decisions_01_06  |
| `src/core/planner.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, historical_regression, planning_decisions_01_06, requirements_docs_plan  |
| `src/core/strategy.py` | source | NORMAL_READ | architecture_code, business_invariants  |
| `src/core/types.py` | source | NORMAL_READ | architecture_code, business_invariants  |
| `src/data/backfill.py` | source | DEEP_READ | architecture_code, data_database_concurrency, integrations_external_apis, planning_decisions_01_06  |
| `src/data/collector.py` | source | DEEP_READ | architecture_code, data_database_concurrency, integrations_external_apis, planning_decisions_01_06, security_reliability  |
| `src/data/coverage.py` | source | METADATA_ONLY | architecture_code, data_database_concurrency  |
| `src/data/metadata.py` | source | DEEP_READ | architecture_code, data_database_concurrency  |
| `src/data/quality.py` | source | NORMAL_READ | architecture_code, data_database_concurrency  |
| `src/data/store.py` | source | DEEP_READ | architecture_code, data_database_concurrency  |
| `src/db/__init__.py` | source | METADATA_ONLY | architecture_code  |
| `src/db/alembic/__init__.py` | migration | METADATA_ONLY | architecture_code  |
| `src/db/alembic/env.py` | migration | DEEP_READ | architecture_code, data_database_concurrency, security_reliability  |
| `src/db/alembic/versions/0001_baseline.py` | migration | DEEP_READ | architecture_code, data_database_concurrency  |
| `src/db/alembic/versions/0002_domain_registry.py` | migration | DEEP_READ | architecture_code, data_database_concurrency  |
| `src/db/alembic/versions/0003_callback_mapping.py` | migration | DEEP_READ | architecture_code, data_database_concurrency  |
| `src/db/alembic/versions/__init__.py` | migration | METADATA_ONLY | architecture_code  |
| `src/db/mappers.py` | source | NORMAL_READ | architecture_code, data_database_concurrency  |
| `src/db/models.py` | source | DEEP_READ | architecture_code, data_database_concurrency, requirements_docs_plan, security_reliability  |
| `src/domain/__init__.py` | source | METADATA_ONLY | architecture_code  |
| `src/domain/approval.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency  |
| `src/domain/canonical.py` | source | NORMAL_READ | architecture_code, data_database_concurrency  |
| `src/domain/enums.py` | source | NORMAL_READ | architecture_code, business_invariants, data_database_concurrency, requirements_docs_plan  |
| `src/domain/fill.py` | source | METADATA_ONLY | architecture_code  |
| `src/domain/ids.py` | source | NORMAL_READ | architecture_code, requirements_docs_plan  |
| `src/domain/journal.py` | source | NORMAL_READ | architecture_code, data_database_concurrency  |
| `src/domain/order.py` | source | METADATA_ONLY | architecture_code  |
| `src/domain/position.py` | source | METADATA_ONLY | architecture_code  |
| `src/domain/registry.py` | source | NORMAL_READ | architecture_code, historical_regression  |
| `src/domain/signal.py` | source | NORMAL_READ | architecture_code, requirements_docs_plan  |
| `src/domain/trade_plan.py` | source | DEEP_READ | architecture_code, business_invariants  |
| `src/execution/__init__.py` | source | METADATA_ONLY | architecture_code  |
| `src/execution/enablement.py` | source | DEEP_READ | architecture_code, business_invariants, historical_regression, planning_decisions_07_17, requirements_docs_plan, security_reliability, testing_verification  |
| `src/execution/fill_monitor.py` | source | NORMAL_READ | architecture_code, business_invariants, data_database_concurrency, integrations_external_apis, requirements_docs_plan  |
| `src/execution/gates.py` | source | DEEP_READ | architecture_code, business_invariants, docs_exchange_facts, integrations_external_apis, security_reliability  |
| `src/execution/manager.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, docs_exchange_facts, historical_regression, integrations_external_apis, planning_decisions_01_06, planning_decisions_07_17, requirements_docs_plan, security_reliability  |
| `src/execution/order_ids.py` | source | NORMAL_READ | architecture_code, business_invariants, security_reliability  |
| `src/execution/placement.py` | source | DEEP_READ | architecture_code, business_invariants, docs_exchange_facts, integrations_external_apis, planning_decisions_01_06, planning_decisions_07_17, requirements_docs_plan  |
| `src/ops/__init__.py` | source | METADATA_ONLY | architecture_code  |
| `src/ops/backup.py` | source | DEEP_READ | architecture_code, planning_decisions_01_06, requirements_docs_plan, security_reliability  |
| `src/ops/drills.py` | source | NORMAL_READ | architecture_code, business_invariants, data_database_concurrency, security_reliability, testing_verification  |
| `src/ops/health.py` | source | NORMAL_READ | architecture_code, integrations_external_apis, planning_decisions_07_17, requirements_docs_plan, security_reliability  |
| `src/paper/__init__.py` | source | METADATA_ONLY | architecture_code  |
| `src/paper/attribution.py` | source | NORMAL_READ | architecture_code, planning_decisions_07_17  |
| `src/paper/freeze.py` | source | METADATA_ONLY | architecture_code  |
| `src/paper/journal.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency  |
| `src/paper/loop.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, integrations_external_apis, security_reliability  |
| `src/paper/notify.py` | source | NORMAL_READ | architecture_code, business_invariants, integrations_external_apis, requirements_docs_plan, security_reliability  |
| `src/paper/resync.py` | source | NORMAL_READ | architecture_code, business_invariants, data_database_concurrency, testing_verification  |
| `src/paper/supervisor.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, integrations_external_apis, security_reliability, testing_verification  |
| `src/reconcile/__init__.py` | source | METADATA_ONLY | architecture_code  |
| `src/reconcile/compare.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, security_reliability, testing_verification  |
| `src/reconcile/safe_mode.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, integrations_external_apis, requirements_docs_plan, security_reliability  |
| `src/reconcile/sweeper.py` | source | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, integrations_external_apis, security_reliability  |
| `src/risk/__init__.py` | source | NORMAL_READ | architecture_code, business_invariants  |
| `src/risk/gating.py` | source | DEEP_READ | architecture_code, business_invariants  |
| `src/risk/portfolio.py` | source | DEEP_READ | architecture_code, business_invariants, planning_decisions_01_06, requirements_docs_plan, testing_verification  |
| `src/risk/quantization.py` | source | DEEP_READ | architecture_code, business_invariants, requirements_docs_plan  |
| `src/risk/sizing.py` | source | DEEP_READ | architecture_code, business_invariants, historical_regression, requirements_docs_plan, testing_verification  |
| `src/risk/types.py` | source | DEEP_READ | architecture_code, business_invariants  |
| `src/sql/coverage_v1.sql` | source | DEEP_READ | architecture_code, data_database_concurrency  |
| `tests/__init__.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/conftest.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/fixtures/exchange_info_sample.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, docs_exchange_facts, docs_trading_soundness, integrations_external_apis, requirements_docs_plan  |
| `tests/fixtures/kline_page_sample.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/approval_delay_three_reports/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/approval_delay_three_reports/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/clock_start_provenance/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/clock_start_provenance/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/complete_trade/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/complete_trade/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/digest_regeneration/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/digest_regeneration/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/empty_live5_slice/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/empty_live5_slice/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/idempotent_replay/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/idempotent_replay/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/incomplete_no_1m/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/incomplete_no_1m/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/incomplete_no_fill/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/incomplete_no_fill/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/kill_clock_boundary/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/kill_clock_boundary/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/kill_insufficient_edge/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/kill_insufficient_edge/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/kill_passing_candidate/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/kill_passing_candidate/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/kill_sticky_reset/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/kill_sticky_reset/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/kill_within_budget/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/kill_within_budget/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/live_lifecycle/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/live_lifecycle/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/live_net_r/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/live_net_r/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/loaders/decisions_sample.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/loaders/evidence_sample.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/loaders/universe_sample.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/low_n_slices/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/low_n_slices/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/no_trade_categories/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/no_trade_categories/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/opportunity_skipped_expired/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/opportunity_skipped_expired/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/paper_lifecycle/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/paper_lifecycle/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/render_golden/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/render_golden/expected.md` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/render_golden/expected_sections_0_2.md` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/report_composite/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/report_composite/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/short_trade/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/short_trade/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/zero_risk_excluded/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase10/zero_risk_excluded/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase3/candles.csv` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase3/expected_plans.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase3/expected_signals.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase3/parameters.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase4/candles.csv` | test-fixture | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan  |
| `tests/fixtures/phase4/expected_features.json` | test-fixture | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan  |
| `tests/fixtures/phase4/expected_plans.json` | test-fixture | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan  |
| `tests/fixtures/phase4/expected_signals.json` | test-fixture | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan  |
| `tests/fixtures/phase4/parameters.json` | test-fixture | DEEP_READ | data_database_concurrency, historical_regression, requirements_docs_plan  |
| `tests/fixtures/phase5/aggregate_cap_reject/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase5/aggregate_cap_reject/input.json` | test-fixture | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase5/cluster_cap_reject/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase5/cluster_cap_reject/input.json` | test-fixture | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase5/daily_stop_block/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase5/daily_stop_block/input.json` | test-fixture | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase5/happy_path_long/expected.json` | test-fixture | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase5/happy_path_long/input.json` | test-fixture | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase5/happy_path_short/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase5/happy_path_short/input.json` | test-fixture | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase5/max_positions_reject/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase5/max_positions_reject/input.json` | test-fixture | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase5/min_qty_reject/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase5/min_qty_reject/input.json` | test-fixture | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase5/notional_reject/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase5/notional_reject/input.json` | test-fixture | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase5/stale_constraints/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase5/stale_constraints/input.json` | test-fixture | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase5/uncertain_account_state/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase5/uncertain_account_state/input.json` | test-fixture | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase5/utilization_reject_edge/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase5/utilization_reject_edge/input.json` | test-fixture | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/baselines/no_trade/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/baselines/no_trade/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/baselines/simple_trend/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/baselines/simple_trend/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/intrabar_both_touched/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/intrabar_both_touched_short/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/intrabar_missing_fallback/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/invalidation_cancels_entry/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/limit_expiry/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/limit_partial_fill/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/limit_touch_no_fill/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/registry_identity/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/registry_identity/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/report_slices/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase6/report_slices/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/fixtures/phase7.1/match/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7.1/precision_drift/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7.1/wrong_fee/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7.1/wrong_funding/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/attribution_split/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/attribution_split/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/clean_run/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/clean_run/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/epoch_rollover/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/epoch_rollover/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/feed_stale_no_trade/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/feed_stale_no_trade/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/opportunity_retained/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/opportunity_retained/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/parity_overlapping_history/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/parity_overlapping_history/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/pinned_epoch_clean/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/pinned_epoch_clean/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/reconnect_resync/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/reconnect_resync/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/unrecoverable_gap/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/unrecoverable_gap/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/warmup_invalid_no_trade/expected.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase7/warmup_invalid_no_trade/input.json` | test-fixture | NORMAL_READ | business_invariants, data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase8/drill_log/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase8/order_ids/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase8/order_ids/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase8/orphan_divergence/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase8/orphan_divergence/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase8/replay_5x/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase8/replay_5x/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/attach/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/attach/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/enablement/disabled/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/enablement/disabled/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/enablement/emergency/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/enablement/emergency/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/enablement/enabled/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/enablement/enabled/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/gates/daily_stop_block/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/gates/daily_stop_block/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/gates/headroom_reject/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/gates/headroom_reject/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/gates/stale_constraints/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/gates/stale_constraints/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/mode_branches/hedge/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/mode_branches/hedge/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/mode_branches/one_way/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/mode_branches/one_way/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/partial_fills/expected.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/partial_fills/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/fixtures/phase9/placement_sequences/expected.json` | test-fixture | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan  |
| `tests/fixtures/phase9/placement_sequences/input.json` | test-fixture | METADATA_ONLY | data_database_concurrency, requirements_docs_plan  |
| `tests/phase10_helpers.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_adapter_strictness.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_approval_delay.py` | test | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_cli.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_digest.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_dual_universe.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_edge_guards.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_excursion.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_files.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_incomplete.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_latency.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_lifecycle.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_live_outcomes.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_no_trade.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_provenance.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_purity.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_render.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_report.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_sidecar.py` | test | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_slices.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_store.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_analytics_typing.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_approval_message.py` | test | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/test_approval_replay.py` | test | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/test_backfill.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_backtest_binding.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_backtest_experiment.py` | test | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/test_backtest_report.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_backtest_simulator.py` | test | DEEP_READ | data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/test_backup.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_candle_close_timing.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_collector.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_core_features.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_core_planner.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_core_strategy_breakout_retest.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_core_strategy_range_mr.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_core_tracer.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_coverage.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_domain_boundary.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_domain_entities.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_domain_enums.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_domain_ids.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_domain_mappers.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_domain_mappers_pg.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_domain_no_float.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_drills.py` | test | NORMAL_READ | data_database_concurrency, integrations_external_apis, requirements_docs_plan, testing_verification  |
| `tests/test_execution_adapter_contract.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_execution_attach.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_execution_emergency.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_execution_enablement.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_execution_gates.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_execution_health.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_execution_manager.py` | test | DEEP_READ | architecture_code, business_invariants, data_database_concurrency, integrations_external_apis, requirements_docs_plan, security_reliability, testing_verification  |
| `tests/test_execution_modes.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_execution_partials.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_execution_price_ticks.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_execution_secret_posture.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_fixture_harness.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_kill_gate_clock.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_kill_gate_docs.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_kill_gate_event.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_kill_gate_families.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_kill_gate_gates.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_kill_gate_registration.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_kill_gate_state.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_kill_gate_sticky.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_metadata.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_no_lookahead.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_order_ids.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_paper_attribution.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_paper_closed_candle.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_paper_feed_gates.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_paper_freeze.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_paper_notify.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_paper_parity.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_paper_resync.py` | test | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/test_paper_reviewfix_pins.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_paper_supervisor_backfill.py` | test | NORMAL_READ | data_database_concurrency, historical_regression, requirements_docs_plan, testing_verification  |
| `tests/test_paper_ws_connect.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_phase8_audit_reviewfix.py` | test | NORMAL_READ | data_database_concurrency, integrations_external_apis, requirements_docs_plan, testing_verification  |
| `tests/test_prefix_invariance.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_quality_gates.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_reconcile.py` | test | NORMAL_READ | data_database_concurrency, integrations_external_apis, requirements_docs_plan, testing_verification  |
| `tests/test_registry.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_registry_gate.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_risk_parity.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_risk_portfolio.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_risk_quantization.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_risk_sizing.py` | test | NORMAL_READ | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_tracer_slice.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `tests/test_wave0_sanity.py` | test | METADATA_ONLY | data_database_concurrency, requirements_docs_plan, testing_verification  |
| `uv.lock` | config | NORMAL_READ | docs_exchange_facts, security_reliability  |
