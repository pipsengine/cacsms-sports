import {createPortal} from 'react-dom';
import React,{useEffect,useMemo,useRef,useState} from 'react';
import {AlertTriangle,ArrowRight,Bot,CalendarDays,CheckCircle2,ChevronLeft,ChevronRight,CircleDot,Clock3,Download,Filter,Flag,History,Layers3,ListChecks,RefreshCcw,Scale,Search,ShieldCheck,Target,Trophy,Volleyball,XCircle,Database} from 'lucide-react';
import {useResearchScope,useResearchRemote} from './ResearchCatalogue';
import {QualificationSecondaryTab} from './AIQualification';
import './DeepMatchResearch.css';
import './MarketIntelligence.css';
import './AIQualification.css';
import './QualifiedOpportunities.css';

const API='/api/v1/sports/qualification/';
type Step={key:string;name:string;sub:string;status:string;detail:string};
type Gate={key:string;name:string;passed:number;evaluated:number;pass_rate:number|null};
type Summary={evaluated:number;qualified:number;rejected:number;pending:number;qualification_rate:number|null;next_cycle_at:string|null;last_cycle_at:string|null;
 runtime:{worker_online:boolean};pipeline:Step[];gates:Gate[];notice:string;trend:{evaluated:number|null;qualified:number|null;rejected:number|null;rate_pp:number|null}};
type Item={id:string;fixture:string;sport:string;competition:string;country:string;kickoff_at:string;market:string;market_key:string;selection:string;bookmaker:string|null;odds:number|null;
 probability:number;lower:number|null;upper:number|null;implied_probability:number|null;edge:number|null;expected_value:number|null;conservative_ev:number|null;confidence:string|null;
 decision:string;reason_codes:string[];gates:Record<string,string>;decided_at:string|null;odds_observed_at:string|null};
type Evidence=Item&{matchday:number|null;research:{status:string|null;sections:{key:string;name:string;status:string;evidence:number}[];sources:string[];evidence_items:number};
 model:{name:string;holdout_brier:number|null;baseline_brier:number|null;calibration_error:number|null;skill:number|null}|null;rationale:{status:string;text:string};features:Record<string,number>|null};
type Coverage={fixtures:number;forecast_fixtures:number};
type Filters={sports:string[];countries:string[];country_stats?:({country:string}&Coverage)[];competitions:({id:string;name:string;country:string|null}&Partial<Coverage>)[];categories:{key:string;name:string}[]};
const coverageLabel=(c?:Partial<Coverage>)=>c&&c.fixtures!=null?` (${c.fixtures} fixture${c.fixtures===1?'':'s'} · ${c.forecast_fixtures?c.forecast_fixtures+' forecast':'no forecasts'})`:'';

const fmt=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{weekday:'short',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v))+' WAT':'—';
const clock=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v))+' WAT':'—';
const n=(v?:number|null)=>v==null?'—':v.toLocaleString('en-NG');
const pct=(v?:number|null)=>v==null?'—':v.toFixed(1)+'%';
const signed=(v?:number|null)=>v==null?'—':(v>0?'+':'')+v.toFixed(1)+'%';
const marketTone=(m:string)=>{const x=m.toLowerCase();return x.includes('over/under')||x.includes('goals')?'ou':x.includes('both teams')?'btts':x.includes('handicap')?'hcp':x.includes('score')?'cs':x.includes('double chance')?'dc':'res'};
const tabs=[{name:'Qualified Opportunities',icon:Trophy},{name:'Market Comparison',icon:Scale},{name:'Quality Gate Inspector',icon:ShieldCheck},{name:'Rejection Intelligence',icon:XCircle},{name:'Opportunity History',icon:History}];
function Status({value}:{value:string}){return <span className={'mi-chip aq-decision '+(value==='QUALIFIED'?'good':value==='REJECTED'?'bad':'warn')}>{value==='QUALIFIED'?<CheckCircle2 size={12}/>:value==='REJECTED'?<XCircle size={12}/>:<Clock3 size={12}/>}{value.toLowerCase()}</span>}
function Trend({value,unit='%',invert=false}:{value?:number|null;unit?:string;invert?:boolean}){if(value==null)return null;const up=value>=0;return <small className={'aq-trend '+((invert?!up:up)?'good':'bad')}>{up?'↑':'↓'} {up?'+':''}{value}{unit}</small>}
function Empty({children}:{children:React.ReactNode}){return <div className="dmr-data-empty">{children}</div>}

export default function QualifiedOpportunities(){
 const {revision,refresh}=useResearchScope();
 const[tab,setTab]=useState('Qualified Opportunities'),[sport,setSport]=useState(''),[country,setCountry]=useState(''),[competition,setCompetition]=useState(''),[category,setCategory]=useState('');
 const[minProb,setMinProb]=useState(60),[minEv,setMinEv]=useState(2),[onlyQualified,setOnlyQualified]=useState(true),[search,setSearch]=useState(''),[query,setQuery]=useState(''),[page,setPage]=useState(0),[selected,setSelected]=useState('');
 const size=5;
 const sum=useResearchRemote<Summary>(API+'summary',revision);
 const filters=useResearchRemote<Filters>(API+'filters',revision);
 const params=new URLSearchParams({only_qualified:String(onlyQualified),min_probability:String(minProb),min_ev:String(minEv),limit:String(size),offset:String(page*size),
  ...query?{search:query}:{},...sport?{sport}:{},...country?{country}:{},...competition?{competition}:{},...category?{category}:{}});
 const list=useResearchRemote<{total:number;items:Item[]}>(API+'opportunities?'+params,revision);
 const items=list.data?.items||[];
 const current=selected&&items.some(i=>i.id===selected)?selected:items[0]?.id||'';
 const ev=useResearchRemote<Evidence>(current?API+'opportunities/'+encodeURIComponent(current)+'/evidence':null,revision);
 const refreshRef=useRef(refresh);refreshRef.current=refresh;
 useEffect(()=>{const t=setInterval(()=>refreshRef.current(),60000);return()=>clearInterval(t)},[]);
 useEffect(()=>{const t=setTimeout(()=>{setQuery(search);setPage(0)},300);return()=>clearTimeout(t)},[search]);
 const s=sum.data;const online=s?.runtime.worker_online;const total=list.data?.total||0;const pages=Math.max(1,Math.ceil(total/size));
 const pageNumbers=useMemo(()=>[...new Set([0,1,2,3,page-1,page,page+1,pages-1].filter(x=>x>=0&&x<pages))].sort((a,b)=>a-b),[page,pages]);
 const records=s?s.evaluated+s.pending:undefined;
 const share=(v?:number)=>records&&v!=null?` (${(v*100/records).toFixed(1)}%)`:'';
 const fresh=!!s?.last_cycle_at&&Date.now()-new Date(s.last_cycle_at).getTime()<10*60000;
 const reset=()=>{setSport('');setCountry('');setCompetition('');setCategory('');setMinProb(60);setMinEv(2);setOnlyQualified(true);setSearch('');setPage(0)};
 const set=(fn:(v:string)=>void)=>(e:React.ChangeEvent<HTMLSelectElement>)=>{fn(e.target.value);setPage(0)};
 const exportCsv=()=>{const head=['fixture','competition','market','selection','odds','probability','implied_probability','edge','expected_value','confidence','status'];
  const csv=[head.join(','),...items.map(r=>[r.fixture,r.competition,r.market,r.selection,r.odds??'',r.probability,r.implied_probability??'',r.edge??'',r.expected_value??'',r.confidence??'',r.decision].map(v=>'"'+String(v).replaceAll('"','""')+'"').join(','))].join('\n');
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='qualified-opportunities.csv';a.click();URL.revokeObjectURL(a.href)};
 const kpis=[{t:'Opportunity Records',v:n(records),icon:Layers3,tone:'blue',trend:<Trend value={s?.trend.evaluated}/>},{t:'Qualified',v:n(s?.qualified),icon:CheckCircle2,tone:'green',trend:<Trend value={s?.trend.qualified}/>},
  {t:'Rejected',v:n(s?.rejected),icon:XCircle,tone:'red',trend:<Trend value={s?.trend.rejected} invert/>},{t:'Pending',v:n(s?.pending),icon:Clock3,tone:'orange'},{t:'Qualification Rate',v:pct(s?.qualification_rate),icon:Target,tone:'purple',trend:<Trend value={s?.trend.rate_pp} unit=" pp"/>}];
 const e=ev.data;
 return <div className="dmr mi aq qo">
  {document.getElementById('deep-runtime-badge')&&createPortal(<span className={'dmr-runtime-badge '+(online?'online':'')}><Bot size={23}/>Autonomous Mode: {online?'ON':s?'OFF':'Checking'}<i/></span>,document.getElementById('deep-runtime-badge')!)}
  <div className="dmr-header"><div className="dmr-intro"><div className="dmr-eyebrow">MARKET INTELLIGENCE</div><h2>Qualified Opportunities</h2><p>Only eligible opportunities available for allocation, after passing all quality and risk gates.</p></div>
   <div className="dmr-kpis aq-kpis">{kpis.map(k=><div className={k.tone} key={k.t}><k.icon/><span>{k.t}</span><b>{k.v}</b>{k.trend}</div>)}</div></div>
  <section className="dmr-pipeline mi-pipeline"><div className="dmr-pipeline-title"><Bot/><div><strong>Autonomous Opportunity Pipeline</strong><small>From prediction to qualified allocation (fully automated).</small></div></div>
   <div className="dmr-steps">{(s?.pipeline||[]).map((x,i,all)=><React.Fragment key={x.key}><div className="dmr-step" title={x.detail}><span className={x.status==='DONE'?'dmr-done':'dmr-wait'}>{x.status==='DONE'?<CheckCircle2/>:<Clock3/>}</span><b>{x.name}</b><small className="aq-sub">({x.key==='qualify'?'Allocation':x.sub})</small></div>{i<all.length-1&&<ArrowRight className="aip-arrow mi-arrow" aria-hidden="true"/>}</React.Fragment>)}</div>
   <div className="dmr-cycle"><span className={'dmr-mode '+(online?'online':'')}><RefreshCcw size={16}/>{online?'Running':s?'Worker offline':'Connecting'}</span><small>{s?.next_cycle_at?'Next run: '+clock(s.next_cycle_at):'Updates automatically'}</small></div></section>
  {[sum,list,filters].some(x=>x.error)&&<div className="dmr-error" role="alert"><AlertTriangle size={16}/>Data unavailable: {[sum,list,filters].map(x=>x.error).filter(Boolean).join('; ')}</div>}
  <div className="dmr-tabs aip-tabs mi-tabs" role="tablist" aria-label="Opportunity views">{tabs.map(t=><button type="button" role="tab" aria-selected={tab===t.name} key={t.name} onClick={()=>setTab(t.name)} className={tab===t.name?'active':''}><t.icon size={18}/>{t.name}</button>)}</div>
  {tab==='Qualified Opportunities'?<>
  <div className="aq-grid">
   <aside className="dmr-card aq-filters" aria-label="Opportunity filters"><div className="dmr-card-head"><h3><Filter/>Opportunity Filters</h3><button type="button" className="aq-reset" onClick={reset}>Reset</button></div>
    <label>Sport<span className="aip-select"><Volleyball aria-hidden="true"/><select aria-label="Sport" value={sport} onChange={set(setSport)}><option value="">All Sports</option>{(filters.data?.sports||[]).map(x=><option key={x}>{x}</option>)}</select></span></label>
    <label>Country<span className="aip-select"><Flag aria-hidden="true"/><select aria-label="Country" value={country} onChange={set(setCountry)}><option value="">All Countries</option>{(filters.data?.country_stats||(filters.data?.countries||[]).map(country=>({country}) as any)).map((x:any)=><option key={x.country} value={x.country}>{x.country}{coverageLabel(x)}</option>)}</select></span></label>
    <label>League / Competition<span className="aip-select"><Trophy aria-hidden="true"/><select aria-label="League / Competition" value={competition} onChange={set(setCompetition)}><option value="">All Competitions</option>{(filters.data?.competitions||[]).filter(c=>!country||(c.country||'Unspecified')===country).map(c=><option key={c.id} value={c.id}>{c.name}{coverageLabel(c)}</option>)}</select></span></label>
    <label>Market Category<span className="aip-select"><Layers3 aria-hidden="true"/><select aria-label="Market Category" value={category} onChange={set(setCategory)}><option value="">All Categories</option>{(filters.data?.categories||[]).map(c=><option key={c.key} value={c.key}>{c.name}</option>)}</select></span></label>
    <label className="qo-range">Confidence (AI probability) <b>≥ {minProb}%</b><input type="range" aria-label="Minimum AI probability" min={0} max={95} step={5} value={minProb} onChange={ev=>{setMinProb(Number(ev.target.value));setPage(0)}}/></label>
    <label className="qo-range">Min. Expected Value (EV) <b>≥ {minEv.toFixed(1)}%</b><input type="range" aria-label="Minimum expected value" min={0} max={20} step={0.5} value={minEv} onChange={ev=>{setMinEv(Number(ev.target.value));setPage(0)}}/></label>
    <label className="qo-toggle"><span>Show only qualified</span><input type="checkbox" role="switch" aria-label="Show only qualified" checked={onlyQualified} onChange={ev=>{setOnlyQualified(ev.target.checked);setPage(0)}}/><i/></label>
   </aside>
   <section className="dmr-card mi-markets"><div className="dmr-card-head"><h3><Trophy className="dmr-gold"/>{onlyQualified?'Qualified Opportunities':'All Opportunity Records'} ({n(total)}){s&&<span className={'mi-chip '+(fresh?'good':'warn')}>{fresh?<CheckCircle2 size={12}/>:<Clock3 size={12}/>}{fresh?'Up to date':'Awaiting cycle'}</span>}</h3>
     <span className="aq-sync"><RefreshCcw size={18}/><span>Last Sync: {clock(s?.last_cycle_at)}<br/>Next Run: {clock(s?.next_cycle_at)}</span></span><button type="button" className="aq-export" onClick={exportCsv} disabled={!items.length}><Download size={16}/>Export</button></div>
    <p className="dmr-caption">{onlyQualified?'Selections that passed all quality, evidence and risk gates, filtered by your confidence and EV thresholds.':'Every decision and every forecast still awaiting a price (EV threshold applies to priced rows).'}</p>
    <div className="aq-toolbar"><label className="aip-search"><Search size={16}/><input aria-label="Search opportunities" placeholder="Search fixture, team, market or selection…" value={search} onChange={ev=>setSearch(ev.target.value)}/></label></div>
    {items.length?<div className="mi-table"><table><thead><tr><th>#</th><th>Fixture (Sport)</th><th>Market</th><th>Selection</th><th>Odds</th><th>AI Prob.</th><th>Imp. Prob.</th><th>Edge</th><th>EV</th><th>Conf.</th><th>Status</th></tr></thead>
     <tbody>{items.map((d,i)=><tr key={d.id} className={'qo-row '+(d.id===current?'selected':'')} onClick={()=>setSelected(d.id)} tabIndex={0} onKeyDown={k=>{if(k.key==='Enter')setSelected(d.id)}} aria-selected={d.id===current}>
      <td>{page*size+i+1}</td><td><span className="aq-fixture"><Volleyball size={16} aria-hidden="true"/><span><b>{d.fixture}</b><small>{d.sport} · {d.competition}</small></span></span></td><td><span className={'aq-mkt '+marketTone(d.market)}>{d.market}</span></td><td>{d.selection}</td>
      <td>{d.odds?.toFixed(2)??'—'}</td><td className="good">{pct(d.probability)}</td><td>{pct(d.implied_probability)}</td><td className={(d.edge??0)>0?'good':''}>{signed(d.edge)}</td><td className={(d.expected_value??0)>0?'good':''}>{signed(d.expected_value)}</td>
      <td>{d.confidence?<span className={'mi-chip '+(d.confidence==='High'?'good':d.confidence==='Medium'?'warn':'muted')}>{d.confidence}</span>:'—'}</td><td><Status value={d.decision}/></td></tr>)}</tbody></table></div>
     :<Empty>{list.loading?'Loading opportunities…':onlyQualified?`No qualified opportunities: ${n(s?.qualified)} decisions passed every gate${s?.pending?`, and ${n(s.pending)} forecasts are still awaiting a source-backed price`:''}. Turn off “Show only qualified” to inspect them.`:'No records match these filters.'}</Empty>}
    <div className="mi-pager"><span>Showing {total?page*size+1:0} – {Math.min(total,(page+1)*size)} of {n(total)} {onlyQualified?'qualified opportunities':'records'}</span><div>
     <button type="button" aria-label="Previous page" disabled={page===0} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={16}/></button>
     {pageNumbers.map((p,i)=><React.Fragment key={p}>{i>0&&p-pageNumbers[i-1]>1&&<span>…</span>}<button type="button" className={p===page?'active':''} onClick={()=>setPage(p)}>{p+1}</button></React.Fragment>)}
     <button type="button" aria-label="Next page" disabled={page>=pages-1} onClick={()=>setPage(p=>p+1)}><ChevronRight size={16}/></button></div></div>
   </section>
   <aside className="mi-side"><section className="dmr-card"><div className="dmr-card-head"><h3><ListChecks/>Opportunity Summary</h3></div>
    <div className="mi-row"><span><CircleDot size={16}/>Total opportunity records</span><b>{n(records)}</b></div>
    <div className="mi-row hl"><span><CheckCircle2 className="good" size={16}/>Qualified</span><b>{n(s?.qualified)}{share(s?.qualified)}</b></div>
    <div className="mi-row"><span><XCircle className="bad" size={16}/>Rejected</span><b>{n(s?.rejected)}{share(s?.rejected)}</b></div>
    <div className="mi-row"><span><Clock3 size={16} className="warn-ic"/>Pending (awaiting price)</span><b>{n(s?.pending)}{share(s?.pending)}</b></div></section>
    <section className="dmr-card"><div className="dmr-card-head"><h3><ShieldCheck/>Quality Gate Status</h3></div>
     {(s?.gates||[]).map(g=><div className="aq-gate qo-gate" key={g.key} title={`${g.passed} of ${g.evaluated} passed`}><span>{g.pass_rate!=null&&g.pass_rate>=50?<CheckCircle2 className="good" size={16}/>:g.pass_rate==null?<Clock3 size={16} className="muted"/>:<XCircle className="bad" size={16}/>}{g.name}</span><b>{pct(g.pass_rate)}</b><i><em style={{width:(g.pass_rate||0)+'%'}}/></i></div>)}
     <p className="dmr-caption">Across all decisions and pending forecasts; value and risk gates need a price.</p></section></aside>
  </div>
  <section className="dmr-card qo-detail"><div className="dmr-card-head"><h3><Target/>Selected Opportunity – Analysis &amp; Evidence</h3>{e&&<Status value={e.decision}/>}</div>
   {!current?<Empty>Select an opportunity to inspect its evidence. {onlyQualified&&!total?'No qualified opportunities exist yet.':''}</Empty>:!e?<Empty>{ev.error||'Loading evidence…'}</Empty>:<div className="qo-detail-grid">
    <div className="qo-fixture"><div className="qo-teams"><span className="dmr-crest" aria-hidden="true"><ShieldCheck/></span><b>{e.fixture.replace(' vs ',' vs\n')}</b><span className="dmr-crest" aria-hidden="true"><ShieldCheck/></span></div>
     <ul><li><Trophy size={14}/>{e.competition}{e.matchday?` · Matchday ${e.matchday}`:''}</li><li><CalendarDays size={14}/>{fmt(e.kickoff_at)}</li><li><Layers3 size={14}/>Market: {e.market}</li><li><Target size={14}/>Selection: {e.selection}</li><li><Scale size={14}/>Odds: {e.odds?.toFixed(2)??'awaiting price'}{e.bookmaker?` (${e.bookmaker})`:''}</li></ul></div>
    <div className="qo-metrics">{[['AI Probability',pct(e.probability),'good'],['Implied Prob.',pct(e.implied_probability),''],['Edge',signed(e.edge),(e.edge??0)>0?'good':''],['Expected Value',signed(e.expected_value),(e.expected_value??0)>0?'good':''],['Confidence',e.confidence||'—','chip']].map(([l,v,t])=>
     <div key={l}><small>{l}</small>{t==='chip'?<span className={'mi-chip '+(v==='High'?'good':v==='Medium'?'warn':'muted')}>{v}</span>:<b className={t}>{v}</b>}</div>)}
     <div className={'qo-rationale '+e.rationale.status.toLowerCase()}>{e.rationale.status==='QUALIFIED'?<CheckCircle2 size={20}/>:e.rationale.status==='REJECTED'?<XCircle size={20}/>:<Clock3 size={20}/>}<span><b>Qualification Rationale</b>{e.rationale.text}</span></div></div>
    <div className="qo-evidence"><b><Database size={15}/>Evidence</b>
     <div className="qo-sections">{e.research.sections.map(x=><span key={x.key} className={'mi-chip '+(x.status==='VERIFIED'?'good':x.status==='UNAVAILABLE'?'muted':'warn')} title={`${x.evidence} evidence items`}>{x.name}: {x.status.toLowerCase()}</span>)}</div>
     <small>Sources: {e.research.sources.join(', ')||'—'} · {n(e.research.evidence_items)} evidence items</small>
     {e.model&&<small>Model: {e.model.name} · holdout Brier {e.model.holdout_brier??'—'} vs base rate {e.model.baseline_brier??'—'} · calibration error {e.model.calibration_error??'—'}{e.model.skill!=null?` · skill ${(e.model.skill*100).toFixed(1)}%`:''}</small>}
     {e.lower!=null&&<small>95% probability range {e.lower}–{e.upper}%{e.conservative_ev!=null?` · lower-bound EV ${signed(e.conservative_ev)}`:''}</small>}</div>
   </div>}</section></>
  :<QualificationSecondaryTab tab={tab} revision={revision} historyTitle="Opportunity history"/>}
  {s&&<p className="dmr-note">{s.notice} Paper mode: opportunities feed paper allocation only; no wagers are placed.</p>}
 </div>;
}
