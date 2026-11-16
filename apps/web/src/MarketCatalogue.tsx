import React,{useMemo,useState} from 'react';
import {AlertTriangle,BarChart3,CheckCircle2,Clock3,Layers3,ListChecks,RefreshCcw,Search,ShieldCheck} from 'lucide-react';
import {useResearchRemote} from './ResearchCatalogue';

type Market={id:string;name:string;category:string;kind:string;period:string;outcome_type:string;origin:string;where_offered:boolean;outcomes:{key:string;label:string}[];
 parameter:{type:string;values?:number[]}|null;statuses:string[];offered:boolean;bookmakers:string[];lines:string[];odds:{bookmaker:string;line:string;outcome:string;decimal_odds:number|null}[];
 odds_observed_at:string|null;model_supported:boolean;research:string;probability:number|null;decision:string|null;top_outcome:Ranked|null};
type Ranked={definition_id:string;market:string;outcome:string;line:string;probability:number;lower:number|null;upper:number|null;skill:number|null;market_skill?:number|null;model:string};
type Coverage={registered:number;discovered:number;offered:number;fresh:number;stale:number;model_supported:number;evaluated:number;qualified:number;unsupported:number;unavailable:number;missing_data_reasons:Record<string,number>;last_sync:string|null};
type View={fixture_id:string;sport:string;markets:Market[];coverage:Coverage;analysis_ranking:Ranked[];ranking_basis:string;categories:{key:string;name:string;registered:number}[];notice:string;scan:{started_at:string;summary:Record<string,unknown>}|null};

const STORE='cacsms.predictions.marketDefinitions';
const REASONS:Record<string,string>={NO_SOURCE_BACKED_ODDS_FOR_FIXTURE:'No source-backed odds for this fixture yet',NO_APPROVED_MODEL_FOR_MARKET:'No approved model for the market',NO_FORECAST_BEFORE_CUTOFF:'No forecast before cutoff',
 INSUFFICIENT_VALUE:'Price offers insufficient value',ODDS_STALE_OR_FUTURE:'Odds older than 15 minutes',NO_CONSERVATIVE_EDGE:'No lower-bound edge',MODEL_NOT_INDEPENDENTLY_APPROVED:'Model not approved',
 CALIBRATION_NOT_VERIFIED:'Calibration unverified',RESEARCH_UNVERIFIED_OR_LEAKAGE:'Research unverified',NO_MATCHING_BOOKMAKER_PRICE:'No matching price'};
const CHIP:Record<string,string>={REGISTERED:'muted',DISCOVERED:'info',AVAILABLE:'info',FRESH:'good',STALE:'warn',MODEL_SUPPORTED:'info',EVALUATED:'info',QUALIFIED:'good',UNSUPPORTED:'muted',UNAVAILABLE:'bad'};
const label=(r:Ranked)=>r.outcome.replace('_',' ').toLowerCase().replace(/^./,c=>c.toUpperCase())+(r.line?' '+r.line:'');
const fmt=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v))+' WAT':'—';
function stored(){try{const v=JSON.parse(localStorage.getItem(STORE)||'null');return Array.isArray(v)?v.filter(x=>typeof x==='string'):null}catch{return null}}

export default function MarketCatalogue({fixtureId,revision}:{fixtureId:string;revision:number}){
 const res=useResearchRemote<View>(fixtureId?'/api/v1/sports/markets/fixtures/'+encodeURIComponent(fixtureId):null,revision);
 const v=res.data;const markets=v?.markets||[];
 const offeredCount=markets.filter(x=>x.offered).length;
 const[mode,setMode]=useState<'auto'|'offered'|'registered'>('auto'),[category,setCategory]=useState('all'),[search,setSearch]=useState(''),[chosen,setChosen]=useState<string[]|null>(stored);
 const view=mode==='auto'?(offeredCount?'offered':'registered'):mode;
 const selected=useMemo(()=>new Set(chosen??markets.filter(x=>x.offered&&x.model_supported).map(x=>x.id)),[chosen,markets]);
 const toggle=(id:string)=>{const next=new Set(selected);next.has(id)?next.delete(id):next.add(id);const list=[...next];setChosen(list);try{localStorage.setItem(STORE,JSON.stringify(list))}catch{}};
 const pool=markets.filter(x=>view==='offered'?x.offered||x.statuses.includes('UNAVAILABLE'):true);
 const rows=pool.filter(x=>(category==='all'||x.category===category)&&(x.name+' '+x.outcomes.map(o=>o.label).join(' ')+' '+x.lines.join(' ')).toLowerCase().includes(search.toLowerCase()));
 const offeredBy=(key:string)=>markets.filter(x=>x.category===key&&x.offered).length;
 const c=v?.coverage;
 const coverage:[string,number|undefined,string][]=[['Registered definitions',c?.registered,'Market types the platform understands'],['Offered for this fixture',c?.offered,'Observed in source-backed odds'],
  ['Fresh odds (≤15 min)',c?.fresh,''],['Stale odds',c?.stale,''],['Model-supported',c?.model_supported,'Approved model capability recorded'],['Evaluated',c?.evaluated,''],
  ['Qualified',c?.qualified,'Passed every gate incl. lower-bound EV'],['Unsupported',c?.unsupported,'Offered but no approved model'],['Unavailable',c?.unavailable,'Removed or suspended by source'],['Selected for tracking',markets.filter(x=>selected.has(x.id)).length,'Saved in this browser']];
 return <section className="dmr-card aip-catalogue mc" aria-label="Bookmaker market catalogue">
  <div className="mc-head"><div className="aip-cat-title"><span className="aip-book"><Layers3 size={18}/></span><div><h3>Bookmaker Markets <small>(Market Catalogue · {v?.sport?.replace('_',' ')||'—'})</small></h3>
   <p title={v?.notice}>Registered definitions are shown immediately; only <b>AVAILABLE</b> markets were observed in source-backed odds for this fixture. No market is presented as offered by SportyBet.</p></div></div>
   <div className="aip-sync-times"><RefreshCcw size={20}/><span><small>Last sync: {fmt(c?.last_sync)}</small><small>Last scan: {fmt(v?.scan?.started_at)}</small></span></div></div>
  {res.error&&<div className="dmr-error" role="alert"><AlertTriangle size={16}/>Market catalogue unavailable: {res.error}</div>}
  <div className="mc-body">
   <nav className="aip-families mc-categories" aria-label="Market categories"><b>Market Categories</b>
    <button type="button" className={category==='all'?'active':''} onClick={()=>setCategory('all')}><span>All Markets</span><em>{markets.length}</em></button>
    {(v?.categories||[]).map(k=><button type="button" key={k.key} disabled={!k.registered} className={category===k.key?'active':''} onClick={()=>setCategory(k.key)} title={offeredBy(k.key)+' offered for this fixture'}>
     <span>{k.name}</span><em>{k.registered}</em>{offeredBy(k.key)>0&&<i className="mc-live">{offeredBy(k.key)}</i>}</button>)}
   </nav>
   <div className="aip-market-table mc-explorer">
    <div className="mc-toolbar"><div className="mc-toggle" role="group" aria-label="Catalogue view"><button type="button" className={view==='offered'?'active':''} onClick={()=>setMode('offered')}>Offered for this fixture ({offeredCount})</button><button type="button" className={view==='registered'?'active':''} onClick={()=>setMode('registered')}>Registered catalogue ({markets.length})</button></div>
     <label className="aip-search"><Search size={16}/><input aria-label="Search markets" placeholder="Search markets (e.g. Over 2.5, BTTS, Asian Handicap)" value={search} onChange={e=>setSearch(e.target.value)}/></label></div>
    {res.loading&&!v?<div className="dmr-data-empty">Loading market catalogue…</div>:rows.length?<div className="aip-scroll mc-scroll"><table><thead><tr><th/><th>Market</th><th>Selections</th><th className="mc-opt">Line</th><th className="mc-opt">Bookmaker</th><th>Latest odds</th><th className="mc-opt">Odds time</th><th>Status</th><th>Model</th><th className="mc-opt">Research</th><th>Prob.</th><th>AI</th></tr></thead>
     <tbody>{rows.map(x=><tr key={x.id} className={x.offered?'':'mc-registered'}><td><input type="checkbox" aria-label={'Select '+x.name} checked={selected.has(x.id)} onChange={()=>toggle(x.id)}/></td>
      <td><b>{x.name}</b><small>{x.kind==='SCHEDULED'?x.category.replace('_',' '):x.kind.replace('_',' ').toLowerCase()}{x.where_offered?' · where offered':''}</small></td>
      <td className="mc-sel" title={x.outcomes.map(o=>o.label).join(' | ')}>{x.outcomes.slice(0,4).map(o=>o.label).join(' | ')}{x.outcomes.length>4?' +'+(x.outcomes.length-4)+' more':''}</td><td className="mc-opt">{x.lines.join(', ')||(x.parameter?.type==='line'?'by line':'—')}</td>
      <td className="mc-opt">{x.bookmakers.join(', ')||'—'}</td>
      <td>{x.odds.length?x.odds.slice(0,3).map(o=>o.decimal_odds?.toFixed(2)).join(' | '):<span className="muted">No odds</span>}</td><td className="mc-opt">{fmt(x.odds_observed_at)}</td>
      <td><span className="mc-chips">{x.statuses.map(s=><i key={s} className={'mc-chip '+(CHIP[s]||'')}>{s.replace('_',' ')}</i>)}</span></td>
      <td>{x.model_supported?<CheckCircle2 className="good" size={16} aria-label="Approved model capability"/>:<span className="muted">—</span>}</td>
      <td className="mc-opt">{x.research==='VERIFIED'?<ShieldCheck className="good" size={16} aria-label="Research verified"/>:<span className="muted" title={x.research}>{x.research==='NOT_STARTED'?'—':x.research.toLowerCase()}</span>}</td>
      <td title={x.top_outcome?`${x.top_outcome.model} · validated skill ${x.top_outcome.skill??'—'}%`:'No approved model forecast'}>{x.top_outcome?<><b>{label(x.top_outcome)}</b> {x.top_outcome.probability.toFixed(1)}%</>:x.probability==null?'—':x.probability.toFixed(1)+'%'}</td><td>{x.decision?<i className={'mc-chip '+(x.decision==='QUALIFIED'?'good':x.decision==='UNSUPPORTED'?'muted':'bad')}>{x.decision.toLowerCase()}</i>:'—'}</td></tr>)}</tbody></table></div>
     :<div className="dmr-data-empty">{view==='offered'?'No markets have been observed in source-backed odds for this fixture yet. Switch to the registered catalogue to see supported definitions.':'No markets match this filter.'}</div>}
   </div>
   <aside className="aip-selected mc-coverage" aria-label="AI market coverage"><div className="aip-selected-head"><b><BarChart3 size={17}/>AI Market Coverage</b></div>
    {coverage.map(([label,value,hint])=><div key={label} className="mc-cov-row" title={hint}><span>{label}</span><b>{value??'—'}</b></div>)}
    <div className="mc-best" title={v?.ranking_basis}><b><ShieldCheck size={15}/>Most suitable for analysis</b>{v?.analysis_ranking?.length?v.analysis_ranking.slice(0,6).map((r,i)=><div key={r.definition_id+r.outcome+r.line}><span><em>{i+1}</em>{r.market.replace(' (Match Result)','').replace('Double Chance (1X, X2, 12)','Double Chance')} · {label(r)}</span><b>{r.probability.toFixed(1)}%</b><small>validated market skill {r.market_skill??r.skill??'—'}% · 95% {r.lower??'—'}–{r.upper??'—'}%</small></div>):<p className="dmr-caption">No validated model forecast for this fixture yet.</p>}</div>
    <div className="mc-reasons"><b><ListChecks size={15}/>Missing-data reasons</b>{c&&Object.keys(c.missing_data_reasons).length?Object.entries(c.missing_data_reasons).map(([k,n])=><div key={k}><span>{REASONS[k]||k.replaceAll('_',' ').toLowerCase()}</span><em>{n}</em></div>):<p className="dmr-caption">None recorded.</p>}</div>
    <p className="dmr-caption"><Clock3 size={12}/> Last successful sync: {fmt(c?.last_sync)}</p>
   </aside>
  </div>
 </section>;
}
