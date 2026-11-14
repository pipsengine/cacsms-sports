export const pageCatalog = {
  "live-operations": {
    "heading": "Operations activity",
    "description": "Track active missions, task outcomes, queue state and incidents",
    "resources": [
      "missions",
      "incidents"
    ],
    "metrics": [
      "Active missions",
      "Queued jobs",
      "Failures",
      "Worker heartbeat"
    ]
  },
  "fixtures": {
    "heading": "Fixture discovery",
    "description": "Search upcoming fixtures and inspect source-backed event identity",
    "resources": [
      "fixtures",
      "sources"
    ],
    "metrics": [
      "Upcoming fixtures",
      "Competitions",
      "Sports",
      "Identity conflicts"
    ]
  },
  "research": {
    "heading": "Research dossiers",
    "description": "Inspect pre-match evidence, completeness and missing feature coverage",
    "resources": [
      "research",
      "fixtures"
    ],
    "metrics": [
      "Verified dossiers",
      "Partial dossiers",
      "Missing evidence",
      "Source conflicts"
    ]
  },
  "match-analysis": {
    "heading": "Statistical intelligence",
    "description": "Inspect validated features, form and context before prediction",
    "resources": [
      "research",
      "predictions"
    ],
    "metrics": [
      "Research ready",
      "Feature snapshots",
      "Statistical coverage",
      "Blocked analysis"
    ]
  },
  "predictions": {
    "heading": "Model forecasts",
    "description": "Review model-linked forecasts and their evidence and calibration",
    "resources": [
      "predictions",
      "models"
    ],
    "metrics": [
      "Active models",
      "Forecasts",
      "Uncalibrated",
      "Rejected"
    ]
  },
  "statistics": {
    "heading": "League intelligence",
    "description": "Review competition standings, sport statistics and research coverage",
    "resources": [
      "statistics",
      "fixtures"
    ],
    "metrics": [
      "Tables verified",
      "Form samples",
      "Stat coverage",
      "Outdated tables"
    ]
  },
  "markets": {
    "heading": "Odds & market intelligence",
    "description": "Inspect verified prices and model-to-bookmaker comparisons",
    "resources": [
      "markets/odds",
      "predictions"
    ],
    "metrics": [
      "Odds snapshots",
      "Fresh prices",
      "Market mappings",
      "Stale prices"
    ]
  },
  "qualification": {
    "heading": "Qualification decisions",
    "description": "Trace mandatory gates and explain rejected or qualified opportunities",
    "resources": [
      "qualification/decisions",
      "predictions"
    ],
    "metrics": [
      "Qualified",
      "Rejected",
      "Integrity blocked",
      "Expired"
    ]
  },
  "opportunities": {
    "heading": "Opportunity intelligence",
    "description": "View only opportunities backed by successful validation gates",
    "resources": [
      "opportunities",
      "markets/odds"
    ],
    "metrics": [
      "Qualified opportunities",
      "Eligible markets",
      "Upcoming kickoffs",
      "Revalidations"
    ]
  },
  "tickets": {
    "heading": "Paper ticket workspace",
    "description": "Inspect validated combinations and ticket-level correlation",
    "resources": [
      "tickets",
      "opportunities"
    ],
    "metrics": [
      "Paper drafts",
      "Legs validated",
      "Expired tickets",
      "Correlation checks"
    ]
  },
  "betslip": {
    "heading": "Betslip preparation",
    "description": "Track exact market mappings and pre-booking verification",
    "resources": [
      "betslips",
      "tickets"
    ],
    "metrics": [
      "Prepared",
      "Mapping verified",
      "Blocked",
      "Expired"
    ]
  },
  "booking-codes": {
    "heading": "Verified booking codes",
    "description": "Review authentic codes with screenshot and ticket evidence",
    "resources": [
      "booking-codes",
      "tickets"
    ],
    "metrics": [
      "Verified codes",
      "Pending verification",
      "Expired",
      "Integrity failures"
    ]
  },
  "results": {
    "heading": "Result reconciliation",
    "description": "Track verified official outcomes and correction history",
    "resources": [
      "results",
      "settlements"
    ],
    "metrics": [
      "Verified results",
      "Pending",
      "Conflicts",
      "Corrections"
    ]
  },
  "performance": {
    "heading": "Prospective evaluation",
    "description": "Compare forecasts and outcomes against bookmaker baselines",
    "resources": [
      "settlements",
      "predictions"
    ],
    "metrics": [
      "Settled predictions",
      "Brier score",
      "Log loss",
      "Benchmark gap"
    ]
  },
  "models": {
    "heading": "Model governance",
    "description": "Review challenger models, validation, calibration and deployment",
    "resources": [
      "models",
      "predictions"
    ],
    "metrics": [
      "Approved",
      "Challengers",
      "Rejected",
      "Drift alerts"
    ]
  },
  "sources": {
    "heading": "Source governance",
    "description": "Inspect permitted sources, freshness, permissions and collection health",
    "resources": [
      "sources",
      "fixtures"
    ],
    "metrics": [
      "Permitted sources",
      "Disabled sources",
      "Unverified",
      "Collection failures"
    ]
  },
  "browser": {
    "heading": "Browser & vision operations",
    "description": "Review browser sessions, extraction evidence and source access policy",
    "resources": [
      "browser/sessions",
      "sources"
    ],
    "metrics": [
      "Active sessions",
      "Verified extractions",
      "Failures",
      "Permission blocks"
    ]
  },
  "orchestrator": {
    "heading": "Mission orchestration",
    "description": "Trace durable missions, retries, leases and stage dependencies",
    "resources": [
      "missions",
      "incidents"
    ],
    "metrics": [
      "Running missions",
      "Pending",
      "Retrying",
      "Dead letter"
    ]
  },
  "diagnostics": {
    "heading": "Reliability & incidents",
    "description": "Inspect API health, worker errors, source issues and unresolved incidents",
    "resources": [
      "incidents",
      "sources"
    ],
    "metrics": [
      "Critical incidents",
      "High incidents",
      "Recovering",
      "Unresolved"
    ]
  },
  "audit": {
    "heading": "Immutable audit history",
    "description": "Trace system decisions, actor identities and correlation IDs",
    "resources": [
      "audit/events",
      "missions"
    ],
    "metrics": [
      "Recorded events",
      "Policy denials",
      "Corrections",
      "Trace gaps"
    ]
  },
  "settings": {
    "heading": "System configuration",
    "description": "Read paper-mode controls, research coverage and operational settings",
    "resources": [
      "programmes",
      "sources"
    ],
    "metrics": [
      "Execution mode",
      "Configured sports",
      "Schedules",
      "Retention"
    ]
  },
  "security": {
    "heading": "Security & policies",
    "description": "Review execution policy, source permissions and authorization state",
    "resources": [
      "sources",
      "audit/events"
    ],
    "metrics": [
      "Paper mode",
      "Policy checks",
      "Restricted sources",
      "Security incidents"
    ]
  }
} as const;
