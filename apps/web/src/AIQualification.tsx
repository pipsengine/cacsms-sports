import {createPortal} from 'react-dom';
import React,{useEffect,useMemo,useRef,useState} from 'react';
import {AlertTriangle,ArrowRight,Ban,BarChart3,Bot,CheckCircle2,ChevronLeft,ChevronRight,Clock3,Download,Eye,X,Filter,Flag,History,Layers3,RefreshCcw,Scale,Search,ShieldCheck,Target,Trophy,XCircle,Volleyball} from 'lucide-react';
import {useResearchScope,useResearchRemote} from './ResearchCatalogue';
import './DeepMatchResearch.css';
import './MarketIntelligence.css';
import './AIQualification.css';

const API='/api/v1/sports/qualification/';
type Step={key:string;name:string;sub:string;status:string;detail:string};
type Gate={key:string;name:string;passed:number;evaluated:number;pass_rate:number|null};
type Summary={evaluated:number;qualified:number;rejected:number;pending:number;qualification_rate:number|null;last_decision_at:string|null;next_cycle_at:string|null;
 runtime:{worker_online:boolean;next_run_at:string|null};pipeline:Step[];gates:Gate[];notice:string;last_cycle:{at?:string}|null;last_cycle_at:string|null;
 trend:{evaluated:number|null;qualified:number|null;rejected:number|null;rate_pp:number|null}};
type Decision={id:string;fixture:string;sport:string;competition:string;country:string;kickoff_at:string;market:string;market_key:string;selection:string;bookmaker:string|null;odds:number|null;
 probability:number;lower:number|null;upper:number|null;implied_probability:number|null;edge:number|null;expected_value:number|null;conservative_ev:number|null;confidence:string|null;
 decision:string;reason_codes:string[];gates:Record<string,string>;decided_at:string|null;odds_observed_at:string|null;origin:string};
type FixtureGroup={fixture_id:string;fixture:string;sport:string;competition:string;country:string;kickoff_at:string;markets:number;qualified:number;rejected:number;pending:number;best:Decision;items:Decision[];not_forecast?:NotForecast[]};
type NotForecast={id:string;market:string;selection:string;skill:number|null;reasons:string[];model:string};
type Breakdown={rejected:number;categories:{key:string;name:string;count:number;share:number|null}[];reason_codes:Record<string,number>};
type Comparison={fixture:string;kickoff_at:string;market:string;selection:string;probability:number;fair_odds:number|null;best_odds:number|null;bookmaker:string|null;odds_observed_at:string|null;implied_probability:number|null;edge:number|null;status:string};
type Coverage={fixtures:number;forecast_fixtures:number;verified_research:number};
type Filters={sports:string[];countries:string[];country_stats?:({country:string;competitions:number}&Coverage)[];competitions:({id:string;name:string;country:string|null}&Partial<Coverage>)[];categories:{key:string;name:string}[];coverage_note?:string};
const coverageLabel=(c?:Partial<Coverage>)=>c&&c.fixtures!=null?` (${c.fixtures} fixture${c.fixtures===1?'':'s'} · ${c.forecast_fixtures?c.forecast_fixtures+' forecast':'no forecasts'})`:'';

const fmt=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v))+' WAT':'—';
const clock=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v))+' WAT':'—';
const n=(v?:number|null)=>v==null?'—':v.toLocaleString('en-NG');
const pct=(v?:number|null)=>v==null?'—':v.toFixed(1)+'%';
const signed=(v?:number|null)=>v==null?'—':(v>0?'+':'')+v.toFixed(1)+'%';
const GATE_LABEL:Record<string,string>={research:'Research',model:'Model',calibration:'Calibration',odds_freshness:'Freshness',market_mapping:'Mapping',value:'Value',uncertainty:'Lower bound',market_risk:'Risk'};
const tabs=[{name:'Qualification Decisions',icon:CheckCircle2},{name:'Market Comparison',icon:Scale},{name:'Quality Gate Inspector',icon:ShieldCheck},{name:'Rejection Intelligence',icon:XCircle},{name:'Qualification History',icon:History}];
function DecisionChip({value}:{value:string}){return <span className={'mi-chip aq-decision '+(value==='QUALIFIED'?'good':value==='REJECTED'?'bad':'warn')}>{value==='QUALIFIED'?<CheckCircle2 size={12}/>:value==='REJECTED'?<XCircle size={12}/>:<Clock3 size={12}/>}{value.toLowerCase()}</span>}
const marketTone=(m:string)=>{const x=m.toLowerCase();return x.includes('over/under')||x.includes('goals')?'ou':x.includes('both teams')?'btts':x.includes('handicap')?'hcp':x.includes('score')?'cs':x.includes('double chance')?'dc':'res'};
function Trend({value,unit='%',invert=false}:{value?:number|null;unit?:string;invert?:boolean}){if(value==null)return null;const up=value>=0;const good=invert?!up:up;return <small className={'aq-trend '+(good?'good':'bad')}>{up?'↑':'↓'} {up?'+':''}{value}{unit}</small>}
function ConfChip({value}:{value:string|null}){return value?<span className={'mi-chip '+(value==='High'?'good':value==='Medium'?'warn':'muted')}>{value}</span>:<>—</>}
function DecisionCounts({g}:{g:FixtureGroup}){return <span className="aq-counts">{g.qualified>0&&<span className="mi-chip good" title="Qualified"><CheckCircle2 size={12}/>{g.qualified}</span>}{g.rejected>0&&<span className="mi-chip bad" title="Rejected"><XCircle size={12}/>{g.rejected}</span>}{g.pending>0&&<span className="mi-chip warn" title="Pending"><Clock3 size={12}/>{g.pending}</span>}</span>}

/** Self-scrolling modal with every evaluated selection for one fixture. */
function FixtureDecisionsModal({group,onClose}:{group:FixtureGroup;onClose:()=>void}){
 const closeRef=useRef<HTMLButtonElement>(null);
 const items=useMemo(()=>[...group.items].sort((a,b)=>(b.probability??-1)-(a.probability??-1)||(b.edge??-1e9)-(a.edge??-1e9)),[group.items]);
 useEffect(()=>{const prev=document.body.style.overflow;document.body.style.overflow='hidden';closeRef.current?.focus();
  const key=(e:KeyboardEvent)=>{if(e.key==='Escape')onClose()};window.addEventListener('keydown',key);
  return()=>{document.body.style.overflow=prev;window.removeEventListener('keydown',key)}},[onClose]);
 return createPortal(<div className="aq-modal-backdrop" onClick={onClose}><section className="aq-modal" role="dialog" aria-modal="true" aria-labelledby="aq-modal-title" onClick={e=>e.stopPropagation()}>
  <header className="aq-modal-head"><div><h3 id="aq-modal-title">{group.fixture}</h3><small>{group.sport} · {group.competition}{group.country?' · '+group.country:''} · Kickoff {fmt(group.kickoff_at)}</small>
   <div className="aq-modal-meta"><span>{n(group.markets)} selections evaluated</span><DecisionCounts g={group}/>{!!group.not_forecast?.length&&<span className="mi-chip muted" title="Markets the model does not forecast"><Ban size={12}/>{group.not_forecast.length} not forecast</span>}</div></div>
   <button ref={closeRef} type="button" className="aq-modal-close" aria-label="Close fixture decisions" onClick={onClose}><X size={20}/></button></header>
  <div className="aq-modal-body"><div className="mi-table"><table><thead><tr><th>Market</th><th>Selection</th><th>Odds</th><th>AI Prob.</th><th>Imp. Prob.</th><th>Edge</th><th>Conf.</th><th>Decision</th><th>Reasons</th></tr></thead>
   <tbody>{items.map(d=><tr key={d.id}><td><span className={'aq-mkt '+marketTone(d.market)}>{d.market}</span>{d.bookmaker&&<small>{d.bookmaker}</small>}</td><td>{d.selection}</td><td title={d.odds==null?'Awaiting a source-backed price':''}>{d.odds?.toFixed(2)??'—'}</td>
    <td className="good">{pct(d.probability)}</td><td>{pct(d.implied_probability)}</td><td className={(d.edge??0)>0?'good':d.edge==null?'':'bad'}>{signed(d.edge)}</td><td><ConfChip value={d.confidence}/></td><td><DecisionChip value={d.decision}/></td>
    <td className="aq-reasons">{d.reason_codes.length?d.reason_codes.map(r=>r.replaceAll('_',' ').toLowerCase()).join(', '):d.decision==='QUALIFIED'?'All gates passed':d.decision==='PENDING'?'Awaiting a source-backed price':'—'}</td></tr>)}
    {!!group.not_forecast?.length&&<><tr className="aq-nf-head"><td colSpan={9}><b>Not forecast</b> — these markets failed the model's out-of-sample validation, so no probability is published for them.</td></tr>
     {group.not_forecast.map(x=><tr key={x.id} className="aq-nf"><td><span className={'aq-mkt '+marketTone(x.market)}>{x.market}</span></td><td>{x.selection}</td><td>—</td><td title="No validated probability">—</td><td>—</td><td>—</td><td>—</td>
      <td><span className="mi-chip muted aq-decision"><Ban size={12}/>not forecast</span></td><td className="aq-reasons">{x.reasons.join('; ')||'Not approved by validation'}{x.skill!=null&&<small> Skill vs base rate: {x.skill>0?'+':''}{x.skill.toFixed(2)}%</small>}</td></tr>)}</>}
   </tbody></table></div></div>
 </section></div>,document.body);
}
function Empty({children}:{children:React.ReactNode}){return <div className="dmr-data-empty">{children}</div>}

export default function AIQualification(){
 const {revision,refresh}=useResearchScope();
 const[tab,setTab]=useState('Qualification Decisions'),[status,setStatus]=useState('ALL'),[sport,setSport]=useState(''),[country,setCountry]=useState(''),[competition,setCompetition]=useState(''),[category,setCategory]=useState(''),[search,setSearch]=useState(''),[query,setQuery]=useState(''),[page,setPage]=useState(0);
 const size=10;
 const sum=useResearchRemote<Summary>(API+'summary',revision);
 const filters=useResearchRemote<Filters>(API+'filters',revision);
 const params=new URLSearchParams({status,group:'fixture',limit:String(size),offset:String(page*size),...query?{search:query}:{},...sport?{sport}:{},...country?{country}:{},...competition?{competition}:{},...category?{category}:{}});
 const list=useResearchRemote<{total:number;decisions:number;groups:FixtureGroup[]}>(API+'decision-details?'+params,revision);
 const[open,setOpen]=useState<FixtureGroup|null>(null);
 const close=React.useCallback(()=>setOpen(null),[]);
 const rej=useResearchRemote<Breakdown>(API+'rejections',revision);
 const refreshRef=useRef(refresh);refreshRef.current=refresh;
 useEffect(()=>{const t=setInterval(()=>refreshRef.current(),60000);return()=>clearInterval(t)},[]);
 useEffect(()=>{const t=setTimeout(()=>{setQuery(search);setPage(0)},300);return()=>clearTimeout(t)},[search]);
 const emptyReason=()=>{
  const comp=competition?filters.data?.competitions.find(c=>c.id===competition):undefined;
  const cs=!comp&&country?filters.data?.country_stats?.find(c=>c.country===country):undefined;
  const scope=comp||cs;const label=comp?comp.name:country;
  if(scope&&scope.fixtures!=null&&!scope.forecast_fixtures)return `No forecasts for ${label}: ${scope.fixtures?`its ${n(scope.fixtures)} upcoming fixture${scope.fixtures===1?' has':'s have'} no verified research yet`:'no upcoming fixtures in the next 7 days'}. ${filters.data?.coverage_note||''}`;
  return 'No decisions match these filters.'};
 const s=sum.data;const online=s?.runtime.worker_online;const total=list.data?.total||0;const pages=Math.max(1,Math.ceil(total/size));
 const pageNumbers=useMemo(()=>[...new Set([0,1,2,page-1,page,page+1,pages-1].filter(x=>x>=0&&x<pages))].sort((a,b)=>a-b),[page,pages]);
 const reset=()=>{setStatus('ALL');setSport('');setCountry('');setCompetition('');setCategory('');setSearch('');setPage(0)};
 const set=(fn:(v:string)=>void)=>(e:React.ChangeEvent<HTMLSelectElement>)=>{fn(e.target.value);setPage(0)};
 const exportCsv=()=>{const rows=(list.data?.groups||[]).flatMap(g=>g.items);const head=['fixture','competition','market','selection','bookmaker','odds','probability','implied_probability','edge','confidence','decision','reasons','decided_at'];
  const csv=[head.join(','),...rows.map(r=>[r.fixture,r.competition,r.market,r.selection,r.bookmaker,r.odds,r.probability,r.implied_probability,r.edge,r.confidence??'',r.decision,r.reason_codes.join(' '),r.decided_at].map(v=>'"'+String(v).replaceAll('"','""')+'"').join(','))].join('\n');
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='qualification-decisions.csv';a.click();URL.revokeObjectURL(a.href)};
 const kpis=[{t:'Evaluated',v:n(s?.evaluated),icon:Layers3,tone:'blue',trend:<Trend value={s?.trend.evaluated}/>},{t:'Qualified',v:n(s?.qualified),icon:CheckCircle2,tone:'green',trend:<Trend value={s?.trend.qualified}/>},{t:'Rejected',v:n(s?.rejected),icon:XCircle,tone:'red',trend:<Trend value={s?.trend.rejected} invert/>},
  {t:'Pending',v:n(s?.pending),icon:Clock3,tone:'orange',sub:'forecasts awaiting a price'},{t:'Qualification Rate',v:pct(s?.qualification_rate),icon:Target,tone:'purple',trend:<Trend value={s?.trend.rate_pp} unit=" pp"/>}];
 const statusCounts={ALL:s?(s.evaluated+s.pending):undefined,QUALIFIED:s?.qualified,REJECTED:s?.rejected,PENDING:s?.pending} as Record<string,number|undefined>;
 const fresh=!!s?.last_cycle_at&&Date.now()-new Date(s.last_cycle_at).getTime()<10*60000;
 return <div className="dmr mi aq">
  {document.getElementById('deep-runtime-badge')&&createPortal(<span className={'dmr-runtime-badge '+(online?'online':'')}><Bot size={23}/>Autonomous Mode: {online?'ON':s?'OFF':'Checking'}<i/></span>,document.getElementById('deep-runtime-badge')!)}
  <div className="dmr-header"><div className="dmr-intro"><div className="dmr-eyebrow">MARKET INTELLIGENCE</div><h2>AI Qualification</h2><p>Mandatory probability, evidence, freshness and risk gates for market approval.</p></div>
   <div className="dmr-kpis aq-kpis">{kpis.map(k=><div className={k.tone} key={k.t}><k.icon/><span>{k.t}</span><b>{k.v}</b>{k.trend||(k.sub&&<small className="mi-kpi-sub">{k.sub}</small>)}</div>)}</div></div>
  <section className="dmr-pipeline mi-pipeline"><div className="dmr-pipeline-title"><Bot/><div><strong>Autonomous Qualification Pipeline</strong><small>Runs automatically for every fixture and market.</small></div></div>
   <div className="dmr-steps">{(s?.pipeline||[]).map((x,i,all)=><React.Fragment key={x.key}><div className="dmr-step" title={x.detail}><span className={x.status==='DONE'?'dmr-done':'dmr-wait'}>{x.status==='DONE'?<CheckCircle2/>:<Clock3/>}</span><b>{x.name}</b><small className="aq-sub">({x.sub})</small></div>{i<all.length-1&&<ArrowRight className="aip-arrow mi-arrow" aria-hidden="true"/>}</React.Fragment>)}</div>
   <div className="dmr-cycle"><span className={'dmr-mode '+(online?'online':'')}><RefreshCcw size={16}/>{online?'Running':s?'Worker offline':'Connecting'}</span><small>{s?.next_cycle_at?'Next run: '+clock(s.next_cycle_at):'Updates automatically'}</small></div></section>
  {[sum,list,rej,filters].some(x=>x.error)&&<div className="dmr-error" role="alert"><AlertTriangle size={16}/>Data unavailable: {[sum,list,rej,filters].map(x=>x.error).filter(Boolean).join('; ')}</div>}
  <div className="dmr-tabs aip-tabs mi-tabs" role="tablist" aria-label="Qualification views">{tabs.map(t=><button type="button" role="tab" aria-selected={tab===t.name} key={t.name} onClick={()=>setTab(t.name)} className={tab===t.name?'active':''}><t.icon size={18}/>{t.name}</button>)}</div>
  {tab==='Qualification Decisions'?<div className="aq-grid">
   <aside className="dmr-card aq-filters" aria-label="Decision filters"><div className="dmr-card-head"><h3><Filter/>Decision Filters</h3><button type="button" className="aq-reset" onClick={reset}>Reset</button></div>
    <label>Sport<span className="aip-select"><Volleyball aria-hidden="true"/><select aria-label="Sport" value={sport} onChange={set(setSport)}><option value="">All Sports</option>{(filters.data?.sports||[]).map(x=><option key={x}>{x}</option>)}</select></span></label>
    <label>Country<span className="aip-select"><Flag aria-hidden="true"/><select aria-label="Country" value={country} onChange={set(setCountry)}><option value="">All Countries</option>{(filters.data?.country_stats||(filters.data?.countries||[]).map(country=>({country}) as any)).map((x:any)=><option key={x.country} value={x.country}>{x.country}{coverageLabel(x)}</option>)}</select></span></label>
    <label>League / Competition<span className="aip-select"><Trophy aria-hidden="true"/><select aria-label="League / Competition" value={competition} onChange={set(setCompetition)}><option value="">All Competitions</option>{(filters.data?.competitions||[]).filter(c=>!country||(c.country||'Unspecified')===country).map(c=><option key={c.id} value={c.id}>{c.name}{coverageLabel(c)}</option>)}</select></span></label>
    <label>Market Category<span className="aip-select"><Layers3 aria-hidden="true"/><select aria-label="Market Category" value={category} onChange={set(setCategory)}><option value="">All Categories</option>{(filters.data?.categories||[]).map(c=><option key={c.key} value={c.key}>{c.name}</option>)}</select></span></label>
    <b className="aq-status-head">Decision Status</b>
    {[['ALL','All',Layers3,''],['QUALIFIED','Qualified',CheckCircle2,'good'],['REJECTED','Rejected',XCircle,'bad'],['PENDING','Pending',Clock3,'warn']].map(([key,label,Icon,tone]:any)=><button type="button" key={key} className={'aq-status '+tone+' '+(status===key?'active':'')} onClick={()=>{setStatus(key);setPage(0)}}><Icon size={16}/>{label} ({n(statusCounts[key])})</button>)}
   </aside>
   <section className="dmr-card mi-markets"><div className="dmr-card-head"><h3><CheckCircle2/>Qualification Decisions ({n(list.data?.decisions)} across {n(total)} fixtures){s&&<span className={'mi-chip '+(fresh?'good':'warn')}>{fresh?<CheckCircle2 size={12}/>:<Clock3 size={12}/>}{fresh?'Up to date':'Awaiting cycle'}</span>}</h3><span className="aq-sync"><RefreshCcw size={18}/><span>Last Sync: {clock(s?.last_cycle_at)}<br/>Next Run: {clock(s?.next_cycle_at)}</span></span></div>
    <p className="dmr-caption">All evaluated markets with probability, odds, edge and final decision. Forecasts without a source-backed price stay Pending.</p>
    <div className="aq-toolbar"><label className="aip-search"><Search size={16}/><input aria-label="Search decisions" placeholder="Search fixture, market or selection…" value={search} onChange={e=>setSearch(e.target.value)}/></label><button type="button" className="aq-export" onClick={exportCsv} disabled={!list.data?.groups?.length}><Download size={16}/>Export</button></div>
    {list.data?.groups?.length?<div className="mi-table"><table><thead><tr><th>#</th><th>Fixture (Sport)</th><th>Kickoff</th><th>Selections</th><th>Top Selection</th><th>Odds</th><th>AI Prob.</th><th>Edge</th><th>Conf.</th><th>Decisions</th><th>Action</th></tr></thead>
     <tbody>{list.data.groups!.map((g,i)=>{const b=g.best;return <tr key={g.fixture_id}><td>{page*size+i+1}</td><td><span className="aq-fixture"><Volleyball size={16} aria-hidden="true"/><span><b>{g.fixture}</b><small>{g.sport} · {g.competition}</small></span></span></td><td className="aq-nowrap">{fmt(g.kickoff_at)}</td><td>{n(g.markets)}</td>
      <td><span className={'aq-mkt '+marketTone(b.market)}>{b.market}</span><small>{b.selection}</small></td><td title={b.odds==null?'Awaiting a source-backed price':''}>{b.odds?.toFixed(2)??'—'}</td><td className="good">{pct(b.probability)}</td><td className={(b.edge??0)>0?'good':b.edge==null?'':'bad'}>{signed(b.edge)}</td><td><ConfChip value={b.confidence}/></td><td><DecisionCounts g={g}/></td>
      <td><button type="button" className="aq-view" onClick={()=>setOpen(g)} aria-label={'View all decisions for '+g.fixture}><Eye size={15}/>View</button></td></tr>})}</tbody></table></div>
     :<Empty>{list.loading?'Loading decisions…':s&&!s.evaluated?`No decisions yet: ${n(s.pending)} forecasts are awaiting a source-backed price. Decisions appear automatically once prices are collected.`:emptyReason()}</Empty>}
    <div className="mi-pager"><span>Showing {total?page*size+1:0}–{Math.min(total,(page+1)*size)} of {n(total)} fixtures</span><div>
     <button type="button" aria-label="Previous page" disabled={page===0} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={16}/></button>
     {pageNumbers.map((p,i)=><React.Fragment key={p}>{i>0&&p-pageNumbers[i-1]>1&&<span>…</span>}<button type="button" className={p===page?'active':''} onClick={()=>setPage(p)}>{p+1}</button></React.Fragment>)}
     <button type="button" aria-label="Next page" disabled={page>=pages-1} onClick={()=>setPage(p=>p+1)}><ChevronRight size={16}/></button></div></div>
   </section>
   <aside className="mi-side"><section className="dmr-card"><div className="dmr-card-head"><h3><ShieldCheck/>Quality Gate Summary</h3></div>
    {(s?.gates||[]).map(g=><div className="aq-gate" key={g.key} title={`${g.passed} of ${g.evaluated} decisions passed`}><span>{g.name}</span><b>{pct(g.pass_rate)}</b><i><em style={{width:(g.pass_rate||0)+'%'}}/></i></div>)}
    {s&&<p className="dmr-caption">{s.evaluated?`Across ${n(s.evaluated)} decisions`:'No decisions yet'}{s.pending?` and ${n(s.pending)} pending forecasts (price-independent gates).`:'.'} Value and risk gates need a price.</p>}</section>
    <section className="dmr-card"><div className="dmr-card-head"><h3><XCircle className="bad"/>Rejection Breakdown ({n(rej.data?.rejected)})</h3></div>
     {(rej.data?.categories||[]).map(c=><div className="mi-row" key={c.key}><span>{c.name}</span><b>{n(c.count)} <small>({pct(c.share)})</small></b></div>)}</section></aside>
  </div>
  :<QualificationSecondaryTab tab={tab} revision={revision}/>}
  {s&&<p className="dmr-note">{s.notice}</p>}
  {open&&<FixtureDecisionsModal group={open} onClose={close}/>}
 </div>;
}

/** Market comparison, gate inspector, rejection intelligence and history views (shared with Qualified Opportunities). */
export function QualificationSecondaryTab({tab,revision,historyTitle='Qualification history'}:{tab:string;revision:number;historyTitle?:string}){
 const comp=useResearchRemote<Comparison[]>(tab==='Market Comparison'?API+'comparison':null,revision);
 const hist=useResearchRemote<{date:string;qualified:number;rejected:number}[]>(tab.endsWith('History')?API+'history':null,revision);
 const inspect=useResearchRemote<{total:number;items:Decision[]}>(tab==='Quality Gate Inspector'?API+'decision-details?status=ALL&limit=50':null,revision);
 const rej=useResearchRemote<Breakdown>(tab==='Rejection Intelligence'?API+'rejections':null,revision);
  return tab==='Market Comparison'?<section className="dmr-card"><div className="dmr-card-head"><h3><Scale/>Market comparison</h3></div><p className="dmr-caption">Model probability and fair odds against the best stored price for every forecast of an upcoming fixture.</p>
   {comp.data?.length?<div className="mi-table"><table><thead><tr><th>Fixture</th><th>Market</th><th>Selection</th><th>AI Prob.</th><th>Fair odds</th><th>Best odds</th><th>Bookmaker</th><th>Imp. Prob.</th><th>Edge</th><th>Price status</th></tr></thead>
    <tbody>{comp.data.map((r,i)=><tr key={i}><td><b>{r.fixture}</b><small>{fmt(r.kickoff_at)}</small></td><td>{r.market}</td><td>{r.selection}</td><td>{pct(r.probability)}</td><td>{r.fair_odds?.toFixed(2)??'—'}</td><td>{r.best_odds?.toFixed(2)??'—'}</td><td>{r.bookmaker||'—'}</td><td>{pct(r.implied_probability)}</td><td className={(r.edge||0)>0?'good':''}>{signed(r.edge)}</td><td><DecisionChip value={r.status==='PRICED'?'priced':'awaiting price'}/></td></tr>)}</tbody></table></div>:<Empty>{comp.loading?'Loading…':'No forecasts for upcoming fixtures.'}</Empty>}</section>
  :tab==='Quality Gate Inspector'?<section className="dmr-card"><div className="dmr-card-head"><h3><ShieldCheck/>Quality gate inspector</h3></div>
   {inspect.data?.items.length?<div className="mi-table"><table><thead><tr><th>Fixture</th><th>Selection</th>{Object.values(GATE_LABEL).map(g=><th key={g}>{g}</th>)}<th>Decision</th></tr></thead>
    <tbody>{inspect.data.items.map(d=><tr key={d.id}><td><b>{d.fixture}</b><small>{d.market} · {d.bookmaker}</small></td><td>{d.selection}</td>{Object.keys(GATE_LABEL).map(g=><td key={g}>{d.gates[g]==='PASS'?<CheckCircle2 className="good" size={16} aria-label="pass"/>:d.gates[g]==='FAIL'?<XCircle className="bad" size={16} aria-label="fail"/>:<span className="muted" title="Needs a price">—</span>}</td>)}<td><DecisionChip value={d.decision}/></td></tr>)}</tbody></table></div>:<Empty>{inspect.loading?'Loading…':'No decisions recorded yet.'}</Empty>}</section>
  :tab==='Rejection Intelligence'?<div className="aq-two"><section className="dmr-card"><div className="dmr-card-head"><h3><XCircle className="bad"/>Rejection categories</h3></div>{(rej.data?.categories||[]).map(c=><div className="aq-gate" key={c.key}><span>{c.name}</span><b>{n(c.count)}</b><i><em className="bad-bar" style={{width:(c.share||0)+'%'}}/></i></div>)}</section>
   <section className="dmr-card"><div className="dmr-card-head"><h3><BarChart3/>Reason codes</h3></div>{rej.data&&Object.keys(rej.data.reason_codes).length?Object.entries(rej.data.reason_codes).map(([k,v])=><div className="mi-row" key={k}><span>{k.replaceAll('_',' ').toLowerCase()}</span><b>{n(v)}</b></div>):<Empty>No rejections recorded.</Empty>}</section></div>
  :<section className="dmr-card"><div className="dmr-card-head"><h3><History/>{historyTitle} (30 days)</h3></div>{hist.data?.length?<div className="mi-table"><table><thead><tr><th>Date</th><th>Qualified</th><th>Rejected</th><th>Rate</th></tr></thead>
   <tbody>{hist.data.map(h=><tr key={h.date}><td>{h.date}</td><td className="good">{n(h.qualified)}</td><td className="bad">{n(h.rejected)}</td><td>{pct(h.qualified+h.rejected?h.qualified*100/(h.qualified+h.rejected):null)}</td></tr>)}</tbody></table></div>:<Empty>{hist.loading?'Loading…':'No decisions in the last 30 days.'}</Empty>}</section>;
}
