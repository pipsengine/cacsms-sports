# Accumulator Engine (accumulator integration patch, integrated)

Source: `CACSMS_Accumulator_Autonomous_Integrated` (v3.7-based snapshot). Only the accumulator feature was taken.

| Patch | Integrated as |
|---|---|
| Separate `accumulator_worker.py` process | `accumulator` step of the existing autonomy cycle; one recorded run per 15-minute bucket (idempotency key `auto:<bucket>`) |
| Own `POLICY` and size-limited combination search | existing `optimizer.PROGRAMMES['accumulator']` (2-12 legs, max odds 1,000, daily cap 5) and `optimizer.select_tickets` - one policy for every path; joint probability recorded as **bounds**, never as a product |
| Gate check "no boolean False in gates" | named gates must be PASS: research, model, calibration, odds freshness, market mapping, value, plus lower-bound value and market risk when recorded |
| Overview / candidates / validation / health endpoints | `/api/v1/sports/programmes/accumulator/{overview,configuration,candidates,run-history,validation,analytics}` |

Runs are paper composition decisions in `strategies.runs` (COMPLETED with legs, or BLOCKED with reasons such as
`INSUFFICIENT_FRESH_QUALIFIED_OPPORTUNITIES`, `DAILY_CAP_REACHED`). Paper hit rate / ROI only count runs whose every leg has a
verified result. Page: `/sports/programmes/accumulator` (other programmes keep `ProgrammeWorkspace`).

Note: the pre-existing admin route `POST /admin/programmes/{key}/run` rejects any decision whose gates dict holds non-PASS
values; decisions also store `reason_codes`/`metrics`, so that route cannot accept current decisions. The new engine checks the
named gates instead.

Tests: `apps/api/tests/test_accumulator_engine.py`.
