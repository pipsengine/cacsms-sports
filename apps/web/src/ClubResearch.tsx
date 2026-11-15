import React from 'react';
import {useResearchScope,useResearchRemote} from './ResearchCatalogue';
type Leader={club:string;computed_rank:number;played:number;points:number;wins:number;draws:number;losses:number;goal_difference:number;last_matches_form:string};
type Report={status:string;verified_matches:number;top_two:Leader[];limitations:string[];head_to_head:{fixture_id:string;home_id:string;away_id:string;home_score:number;away_score:number;result_version:number}[]};
export function ClubResearch(){
 const{selection:s,revision}=useResearchScope();
 const query=new URLSearchParams();
 if(s.season)query.set('season_id',s.season);
 if(s.asOf){const cutoff=new Date(s.asOf);if(!Number.isNaN(cutoff.getTime()))query.set('as_of',cutoff.toISOString())}
 const url=s.league&&s.sport.toLowerCase()==='football'?'/api/v1/sports/competitions/'+encodeURIComponent(s.league)+'/top-two/research?'+query:null;
 const{data:report,error,loading}=useResearchRemote<Report>(url,revision);
 return <section className="panel research-workspace"><div className="panel-head"><div><h3>Top-two football club research</h3><p>Computed form and recent meetings for the shared competition and season.</p></div></div>
 {loading?<div className="empty">Computing club research...</div>:error?<p className="error">{error}</p>:report?<><p className="research-caption">{report.status.replaceAll('_',' ')} | {report.verified_matches} verified matches</p><div className="table-scroll"><table><thead><tr>{['Rank','Club','Played','Points','W/D/L','Goal difference','Recent form'].map(t=><th key={t}>{t}</th>)}</tr></thead><tbody>{report.top_two.map(r=><tr key={r.club}><td><span className="research-rank leader">{r.computed_rank}</span></td><td>{r.club}</td><td>{r.played}</td><td>{r.points}</td><td>{r.wins}/{r.draws}/{r.losses}</td><td>{r.goal_difference}</td><td>{r.last_matches_form}</td></tr>)}</tbody></table></div><h4>Recent head-to-head</h4>{report.head_to_head.length?report.head_to_head.map(g=><p key={g.fixture_id} className="research-caption">{g.home_id} {g.home_score} - {g.away_score} {g.away_id} | Result version {g.result_version}</p>):<p className="research-caption">No verified meetings in this window.</p>}<div className="research-warning">{report.limitations.join('. ')}</div></>:<p className="research-caption">Select a football competition to inspect top-two form and head-to-head evidence.</p>}
 </section>;
}
