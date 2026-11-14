/** Navigation order follows the user journey; existing route slugs are preserved. */
export const navigation = {
  'Control Centre': [['Dashboard','dashboard'],['Command Centre','command-centre'],['Live Operations','live-operations']],
  'Sports Intelligence': [['Fixtures & Competitions','fixtures'],['League Tables & Statistics','statistics'],['Deep Match Research','research'],['Match Analysis','match-analysis'],['AI Predictions','predictions']],
  'Market Intelligence': [['Market Intelligence','markets'],['AI Qualification','qualification'],['Qualified Opportunities','opportunities']],
  'Betting Programmes': [['Accumulator Engine','programmes/accumulator'],['Automatic Singles','programmes/singles'],['Jackpot Engine','programmes/jackpot'],['Weekly Draw Centre','programmes/draws'],['Daily Rollover Centre','programmes/rollover']],
  'Ticket & Booking': [['Ticket Builder','tickets'],['Betslip Preparation','betslip'],['Booking Codes','booking-codes']],
  'Results & Learning': [['Match Results','results'],['Performance Analytics','performance'],['Model Intelligence','models']],
  'Engine Operations': [['Engine Orchestrator','orchestrator'],['Source Intelligence','sources'],['Browser & Vision Operator','browser'],['Diagnostics & Incidents','diagnostics']],
  'Administration': [['Configuration','settings'],['Security & Policies','security'],['Audit Trail','audit']]
} as const;
export const groupIcons: Record<keyof typeof navigation,string> = {
  'Control Centre':'control','Sports Intelligence':'intelligence','Market Intelligence':'markets','Betting Programmes':'programmes',
  'Ticket & Booking':'booking','Results & Learning':'results','Engine Operations':'operations','Administration':'admin'
};
export const pageDescriptions:Record<string,string>={
  dashboard:'Executive summary of evidence-backed activity, readiness and incidents',
  'command-centre':'Mission control, authorized actions and current mission progress',
  'live-operations':'Live acquisition, workers and operational events',
  fixtures:'Upcoming fixtures, competition coverage and source provenance',
  statistics:'Verified league positions and sport-specific statistics',
  research:'Fixture research dossiers, evidence and review status',
  'match-analysis':'Statistical feature comparisons and fixture analysis',
  predictions:'Approved model predictions and calibration evidence',
  markets:'Verified market prices, timestamps and source comparisons',
  qualification:'Mandatory probability, evidence, freshness and risk gates',
  opportunities:'Only eligible opportunities available for allocation',
  tickets:'Constructed paper tickets and selection validation',
  betslip:'Prepared paper betslips and provider readiness',
  'booking-codes':'Genuine verified codes only; missing integrations remain unavailable',
  results:'Official results and fixture-level reconciliation',
  performance:'Settlement, programme results and performance metrics',
  models:'Model approval, governance, calibration and drift',
  sources:'Configured authorized sources and acquisition health',
  browser:'Browser captures, screenshot evidence and vision readiness',
  orchestrator:'Full twelve-stage evidence ledger, dependencies and retries',
  diagnostics:'Incidents, errors, recovery and service diagnostics',
  settings:'Operational configuration and policy settings',
  security:'Security controls and access policies',
  audit:'Recorded audit events and change history'
};
