# Version 2.6 — Paper Strategy Allocation

Implemented: five programme configurations; deterministic optimizer; qualified-only database reads; distinct fixture constraints; draw-leg restrictions; singles and rollover limits; jackpot target as an eligibility filter (never invented); probability bounds instead of false independence; duplicate-signature protection; audited, idempotent paper strategy runs; migration 0003; strategy API.

Endpoints: GET /api/v1/sports/programmes, GET /api/v1/sports/programmes/{key}/runs, POST /api/v1/sports/admin/programmes/{key}/run (admin token).

Known limitations: no real bookmaker connector, no real-money placement, no verified betslip or booking code, no trained sports-specific validated models, no measured pairwise correlations, no deployed end-to-end proof. Strategy proposals are NOT bookmaker-verified tickets. The optimizer is bounded to 30 candidates and deliberately may not find the global optimum.
