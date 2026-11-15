import React from 'react';
import {useResearchScope,useResearchRemote} from './ResearchCatalogue';
type Coverage={views:Record<string,{status:string;as_of:string|null;pending_count:number;verified_count:number}>};
type History={snapshot_id:string;as_of:string;verified_at:string;source:string;reviewed_by:string|null;official:boolean};
export function StandingsGovernance({scope}:{scope:string}){
 const{selection:s,revision}=useResearchScope();
 const q=new URLSearchParams({league_id:s.league,season_id:s.season});
 let before='';if(s.asOf){const date=new Date(s.asOf);if(!Number.isNaN(date.getTime()))before=date.toISOString()}
 const enabled=!!s.league&&!!s.season;
 const coverage=useResearchRemote<Coverage>(enabled?'/api/v1/sports/research/catalog/coverage?'+q+(before?'&as_of='+encodeURIComponent(before):''):null,revision);
 const history=useResearchRemote<History[]>(enabled?'/api/v1/sports/research/catalog/standings/history?'+q+'&scope='+scope+(before?'&before='+encodeURIComponent(before):''):null,revision);
 if(!enabled)return <p className="research-caption">Select a season to inspect source-table coverage and approved snapshot history.</p>;
 return <div className="standings-governance"><h4>Source snapshot coverage</h4><p className="research-caption">Pending imports are counted but their rankings stay hidden until reviewed. Computed fixture tables are separate from source coverage.</p>
 {coverage.loading?<p className="research-caption">Checking coverage...</p>:coverage.error?<p className="error" role="alert">{coverage.error}</p>:coverage.data&&<div className="standings-coverage">{Object.entries(coverage.data.views).map(([view,value])=><div key={view} className="standings-coverage-card"><strong>{view[0].toUpperCase()+view.slice(1)}</strong><span className={'evidence-state '+(value.status==='VERIFIED'?'good':value.status==='PENDING_REVIEW'?'warn':'neutral')}>{value.status.replaceAll('_',' ')}</span><small>{value.verified_count} verified / {value.pending_count} pending</small></div>)}</div>}
 <h4>Approved {scope} snapshot history</h4>{history.loading?<p className="research-caption">Loading history...</p>:history.error?<p className="error" role="alert">{history.error}</p>:history.data?.length?<div className="table-scroll"><table><thead><tr><th>Snapshot date</th><th>Verified</th><th>Source</th><th>Reviewer</th><th>Classification</th></tr></thead><tbody>{history.data.map(row=><tr key={row.snapshot_id}><td>{new Date(row.as_of).toLocaleString()}</td><td>{new Date(row.verified_at).toLocaleString()}</td><td>{row.source}</td><td>{row.reviewed_by||'Administrator intake'}</td><td>{row.official?'Official source':'Research / provisional'}</td></tr>)}</tbody></table></div>:<p className="research-caption">No approved snapshots available for this scope and historical cutoff.</p>}
 </div>;
}
