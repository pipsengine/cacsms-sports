export const workflowStages=[
 ['discover','Discover','fixtures','Fixtures & Competitions'],['acquire','Acquire','browser','Browser & Vision Operator'],
 ['research','Research','research','Deep Match Research'],['analyse','Analyse','match-analysis','Match Analysis'],
 ['predict','Predict','predictions','AI Predictions'],['evaluate','Evaluate','markets','Market Intelligence'],
 ['qualify','Qualify','qualification','AI Qualification'],['allocate','Allocate','programmes/singles','Betting Programmes'],
 ['prepare','Prepare','tickets','Ticket Builder'],['verify','Verify','betslip','Betslip Preparation'],
 ['monitor','Monitor','live-operations','Live Operations'],['reconcile','Reconcile','results','Match Results']
] as const;
export function stageHref(index:number,run?:{id?:string;fixture_id?:string}){
 const q=new URLSearchParams();if(run?.id)q.set('run_id',run.id);if(run?.fixture_id)q.set('fixture_id',run.fixture_id);q.set('stage',workflowStages[index][0]);
 return '/sports/'+workflowStages[index][2]+'?'+q;
}
