# CACSMS SPORTS v3.7 — naming and approved-model inference

## New
- Repository and web package renamed to **cacsms-sports**.
- Engine driver now invokes the prospective prediction service after verified research and features.
- Inference is limited to ACTIVE, explicitly approved, out-of-sample and independently calibrated model artifacts.
- Binary `1X2/HOME` is the only mapped inference market; other markets require separate validated adapters.
- Feature schema, sport, fixture, temporal cutoff and dossier identity are checked before persistence.
- Idempotent forecast creation and auditable evidence identifiers.
- No invented forecasts, booking codes or odds; PAPER mode remains mandatory.

## Still required
A real PostgreSQL migration, Docker and frontend build, licensed source feeds, actual independently approved model artifacts, market outcome mapping tests, booking-code provider integration and full live end-to-end execution. This release does **not** demonstrate production operation.
