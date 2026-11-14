# CACSMS SPORTS v4.2 — Programme and Administration Workspaces

Retains the complete v4.1 tree and adds two dedicated React workspaces.

- All five programme routes now show server-sourced policy, run history, status counts, search, and evidence modal. No client-side generation or live staking.
- Configuration, Security, and Audit routes now have distinct evidence-oriented views. The security screen is a read-only incident/audit view, not a user-management console.
- Ticket records without explicit status display UNVERIFIED rather than incorrectly defaulting to VERIFIED.
- All server requests expose loading, empty and failure states. No fabricated programme results.

## Known limitations

The dedicated workspaces are read-only and do not replace server-side authorization. Configuration writes and authenticated admin actions require separate audited API integration. Live PostgreSQL, Docker and browser E2E tests are not proven by this package. External sports-data and booking-code providers are still required.
