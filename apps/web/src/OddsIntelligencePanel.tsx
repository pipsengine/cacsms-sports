import {useState} from 'react';
import {useResearchRemote} from './ResearchCatalogue';

type Observation={odds_id:string;classification:string;provider:string|null;bookmaker:string;market_key:string;outcome_key:string;decimal_odds:number;age_seconds:number;observed_at:string;rejection_reasons:string[]};
type Page={observations:Observation[];next_offset:number|null;scanned:number};

export default function OddsIntelligencePanel({revision}:{revision:number}){
 const [classification,setClassification]=useState(''),[offset,setOffset]=useState(0);
 const result=useResearchRemote<Page>('/api/v1/sports/odds-intelligence/observations?'+new URLSearchParams({limit:'10',offset:String(offset),...classification?{classification}:{}}),revision);
 return <section className="odds-evidence-panel" aria-label="Odds evidence classifications">
  <div className="odds-evidence-heading"><div><h3>Price evidence & eligibility</h3><p>Provider observation time controls the 15-minute limit. Historical and research prices cannot qualify.</p></div>
   <label>Classification <select aria-label="Price classification" value={classification} onChange={e=>{setClassification(e.target.value);setOffset(0)}}>
    <option value="">All classifications</option><option value="HISTORICAL">Historical</option><option value="RESEARCH_SNAPSHOT">Research snapshots</option><option value="FRESH_MARKET">Fresh markets</option>
   </select></label></div>
  {result.loading&&<p role="status">Loading price evidence…</p>}
  {result.error&&<p role="alert">{result.error}</p>}
  {result.data&&<><div className="odds-evidence-scroll"><table><thead><tr><th>Classification</th><th>Provider / bookmaker</th><th>Market</th><th>Odds</th><th>Observed / age</th><th>Eligibility reasons</th></tr></thead><tbody>
   {result.data.observations.map(row=><tr key={row.odds_id}><td>{row.classification.replaceAll('_',' ')}</td><td>{row.provider||'Unverified provider'} / {row.bookmaker}</td><td>{row.market_key} · {row.outcome_key}</td><td>{row.decimal_odds}</td><td>{new Date(row.observed_at).toLocaleString('en-GB',{timeZone:'Africa/Lagos'})} WAT<br/>{Math.floor(row.age_seconds/60).toLocaleString()} minutes</td><td>{row.rejection_reasons.join(', ')||'Fresh-market checks passed; PAPER only'}</td></tr>)}
  </tbody></table></div>{!result.data.observations.length&&<p>No matching observations in this page of stored evidence.</p>}
   <div className="odds-evidence-heading"><small>Scanned {result.data.scanned} stored rows. Filters apply to this page.</small><div><button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-10))}>Previous</button> <button disabled={result.data.next_offset===null} onClick={()=>setOffset(result.data?.next_offset??offset)}>Next</button></div></div></>}
 </section>;
}
