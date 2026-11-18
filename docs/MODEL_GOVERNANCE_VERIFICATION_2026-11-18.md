# Model governance verification — 18 November 2026

## Reviewed evidence

Model `9be34728-fb94-450c-838a-c86d964396ac`, version `20261116.121328`,
was already registered ACTIVE and already had all four required approval flags.
Its original `model.promoted` audit event and validation artifact retain the
promotion actor `autonomous-model-governance` and promotion time
`2026-11-16T12:13:28.090943+00:00`.

Re-running the current server-side promotion assessment against the persisted
artifact passed with no blocking reasons:

| Measurement | Persisted evidence |
|---|---|
| Chronological holdout sample | 378 |
| Model Brier | 0.221951 |
| Baseline Brier | 0.248350 |
| Model log loss | 0.633225 |
| Baseline log loss | 0.689852 |
| Calibration error | 0.04843306878306877 |
| Maximum calibration error | 0.08 |

The assessment also checked the artifact/feature contract, coefficients and
chronological separation. The original audit holdout evidence matches the artifact.

## Reviewed correction

Only the contradictory legacy artifact labels are eligible for correction:
`status: CHALLENGER`, `activation_allowed: false`, and the old approval-required
note. The registry status, approval flags, model version, promotion evidence and
deployment record are not changed. Original labels must be preserved in a new
`model.legacy_labels_reconciled` audit event referring to this review.

`scripts/reconcile_model_labels.py` defaults to review-only. Its explicit apply
mode requires a named reviewer and review reference, rechecks approval and the
current validation gate under a model row lock, requires matching original
promotion audit evidence and is idempotent. It cannot promote a challenger.

Automated tests cover successful reviewed correction, preservation of original
labels, idempotence and refusal to activate an unapproved registered model.

## Limits

This is verification of the recorded promotion evidence, not a new independent
dataset evaluation or proof of future profitability. Actual deployment status is
still unverified where no deployment receipt exists. Historical holdout metrics
must not be substituted for prospective monitoring outcomes.

The application keeps PAPER mode. Current-version monitoring still depends on
real settlements, and no model receives approval simply because its registry
status is ACTIVE.

## Applied outcome

The reviewed cosmetic correction was applied by `post-audit-remediation-review`. Audit event `35d4dbeb-c5ba-4e5c-9f50-ea8ec365032f` preserves all three original labels and the validation evidence. The registry status and approval flags were unchanged; no model was activated.
