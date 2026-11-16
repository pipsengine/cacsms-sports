import {createPortal} from 'react-dom';
import React,{useEffect,useRef,useState} from 'react';
import {Activity,AlertTriangle,ArrowRight,BarChart3,Bot,CalendarClock,CheckCircle2,ChevronLeft,ChevronRight,Clock3,Database,Layers3,LayoutGrid,ListChecks,Lock,RefreshCcw,Settings2,ShieldCheck,SlidersHorizontal,Target,Ticket,XCircle,History} from 'lucide-react';
import {useResearchScope,useResearchRemote} from './ResearchCatalogue';
import './DeepMatchResearch.css';
import './MarketIntelligence.css';
import './AIQualification.css';
import './AccumulatorEngine.css';

type Key='accumulator'|'singles'|'jackpot';
const CONFIG:Record<Key,{title:string;description:string;pipeline:string;pipelineSub:string;label:string;empty:string}>={
 accumulator:{title:'Accumulator Engine',description:'Multi-selection optimisation using only qualified opportunities, with evidence, risk and configuration controls.',
  pipeline:'Autonomous Programme Pipeline',pipelineSub:'Fetch Qualified Opportunities → Select & Optimise → Validate → Build Ticket → Publish',label:'ACCUMULATOR',
  empty:'No runs recorded yet. The engine records one paper composition decision every 15 minutes.'},
 singles:{title:'Automatic Singles',description:'Single-outcome selections with daily caps and independent risk gates.',
  pipeline:'Autonomous Singles Pipeline',pipelineSub:'From qualified opportunities to published singles (fully automated)',label:'SINGLES',
  empty:'No runs recorded yet. The engine records a paper run every 5 minutes, including blocked runs.'},
 jackpot:{title:'Jackpot Engine',description:'High-odds candidate screening and ticket generation using qualified opportunities and strict risk controls.',
  pipeline:'Autonomous Jackpot Pipeline',pipelineSub:'From qualified opportunities to paper jackpot (fully automated)',label:'JACKPOT',
  empty:'No runs recorded yet. The engine records a paper run every 15 minutes, including blocked runs.'}};
type Step={key:string;name:string;sub:string;status:string;detail:string};
type Leg={qualification_id:string;fixture:string;kickoff_at:string;market_key:string;outcome_key:string;odds:number;probability:number;ev:number;bookmaker:string};
type Run={id:string;number:number|null;created_at:string;status:string;selections:number;combined_odds:number|null;reasons:string[];trigger:string;candidate_count:number|null;
 probability_lower_bound:number|null;probability_upper_bound:number|null;legs:Leg[];tickets:TicketT[];settlement:string|null};
type Policy={min_legs:number;max_legs:number;max_odds:number;daily_cap:number;freshness_minutes:number;mode:string;schedule_minutes:number;paper_stake:number|null;cap_unit:string;one_per_fixture_per_day:boolean;min_combined_odds:number|null};
type TicketT={legs:Leg[];combined_odds:number;paper_stake:number|null;potential_return:number|null};
type Overview={mode:string;policy:Policy;readiness:string;recorded_runs:number;completed:number;blocked:number;avg_selections:number|null;avg_combined_odds:number|null;
 trend:{runs:number|null;completed:number|null;blocked:number|null;avg_selections:number|null;avg_odds:number|null;success_rate_pp:number|null};eligible_candidates:number;
 success_rate:number|null;settled_tickets:number;tickets:number;today:{used:number;cap:number};excluded:Record<string,number>;
 last_run:Run|null;next_run_at:string;runtime:{worker_online:boolean};pipeline:Step[];notice:string;
 validation:{qualified_upcoming:number;items:{key:string;name:string;pass_rate:number|null;detail:string}[]};
 analytics:{runs:number;completion_rate:number|null;avg_legs:number|null;avg_odds:number|null;settled:number;paper_hit_rate:number|null;paper_roi:number|null;daily:{date:string;completion_rate:number;runs:number}[]};
 system:{name:string;status:string;detail:string}[]};

const fmt=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v)):'—';
const clock=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v))+' WAT':'—';
const n=(v?:number|null,d=0)=>v==null?'—':v.toLocaleString('en-NG',{minimumFractionDigits:d,maximumFractionDigits:d});
const pct=(v?:number|null)=>v==null?'—':v.toFixed(1)+'%';
const big=(v?:number|null)=>v==null?'—':v>=1e6?(v/1e6).toFixed(2)+'M':v>=1e4?(v/1e3).toFixed(1)+'K':v.toFixed(2);
const REASON:Record<string,string>={INSUFFICIENT_FRESH_QUALIFIED_OPPORTUNITIES:'Not enough fresh qualified opportunities',DAILY_CAP_REACHED:'Daily cap reached',NO_VALID_DIVERSIFIED_COMBINATION:'No valid diversified combination',
 ODDS_NOT_FRESH:'Odds older than 15 min',QUALITY_GATE_NOT_PASSED:'Quality gate not passed',MODEL_NOT_ACTIVE_APPROVED:'Model not active/approved',NO_POSITIVE_EV:'No positive EV',FIXTURE_STARTED:'Fixture started',MARKET_MAPPING_MISMATCH:'Market mapping mismatch',
 JACKPOT_ODDS_UNREACHABLE:'Eligible prices cannot reach the jackpot odds floor',NO_VALID_SELECTION:'No valid selection',ALREADY_SELECTED_TODAY:'Already selected today'};
const tabs=[{name:'Overview',icon:LayoutGrid},{name:'Programme Rules',icon:SlidersHorizontal},{name:'Run History',icon:History},{name:'Validation Requirements',icon:ShieldCheck},{name:'Programme Analytics',icon:BarChart3}];
function RunStatus({value}:{value:string}){return <span className={'mi-chip '+(value==='COMPLETED'?'good':'bad')}>{value==='COMPLETED'?<CheckCircle2 size={12}/>:<XCircle size={12}/>}{value==='COMPLETED'?'Completed':'Blocked'}</span>}
function Trend({value,unit='%',invert=false}:{value?:number|null;unit?:string;invert?:boolean}){if(value==null)return null;const up=value>=0;return <small className={'aq-trend '+((invert?!up:up)?'good':'bad')}>{up?'↑':'↓'} {up?'+':''}{value}{unit}</small>}
function Empty({children}:{children:React.ReactNode}){return <div className="dmr-data-empty">{children}</div>}
function Chart({points}:{points:{date:string;completion_rate:number}[]}){
 if(points.length<2)return <Empty>The completion-rate trend appears after runs on at least two days.</Empty>;
 const W=520,H=150,P=28;const x=(i:number)=>P+i*(W-P*2)/(points.length-1);const y=(v:number)=>H-P-(v/100)*(H-P*1.6);
 const line=points.map((p,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(p.completion_rate).toFixed(1)}`).join(' ');
 return <svg className="ae-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Daily completion rate">{[0,50,100].map(v=><g key={v}><line x1={P} x2={W-P} y1={y(v)} y2={y(v)}/><text x={4} y={y(v)+4}>{v}%</text></g>)}
  <path className="area" d={`${line} L${x(points.length-1)},${H-P} L${x(0)},${H-P} Z`}/><path className="line" d={line}/>{points.map((p,i)=><circle key={p.date} cx={x(i)} cy={y(p.completion_rate)} r={3.5}><title>{p.date}: {p.completion_rate}%</title></circle>)}
  {points.filter((_,i)=>i%Math.ceil(points.length/6)===0).map(p=>{const i=points.indexOf(p);return <text key={'t'+p.date} className="tick" x={x(i)} y={H-8} textAnchor="middle">{p.date.slice(5)}</text>})}</svg>;
}

export default function AccumulatorEngine(){return <ProgrammeEngine programme="accumulator"/>}
export function SinglesEngine(){return <ProgrammeEngine programme="singles"/>}
export function JackpotEngine(){return <ProgrammeEngine programme="jackpot"/>}

export function ProgrammeEngine({programme}:{programme:Key}){
 const API=`/api/v1/sports/programmes/${programme}/`;const C=CONFIG[programme];const singles=programme==='singles',jackpot=programme==='jackpot';
 const odds=(v?:number|null)=>jackpot?n(v,0):v?.toFixed(2)??'—';
 const {revision,refresh}=useResearchScope();
 const[tab,setTab]=useState('Overview'),[page,setPage]=useState(0),[open,setOpen]=useState('');
 const ov=useResearchRemote<Overview>(API+'overview',revision);
 const recent=useResearchRemote<{total:number;items:Run[]}>(API+'run-history?limit=5',revision);
 const history=useResearchRemote<{total:number;items:Run[]}>(tab==='Run History'?API+'run-history?limit=15&offset='+page*15:null,revision);
 const refreshRef=useRef(refresh);refreshRef.current=refresh;
 useEffect(()=>{const t=setInterval(()=>refreshRef.current(),60000);return()=>clearInterval(t)},[]);
 const o=ov.data;const online=o?.runtime.worker_online;const p=o?.policy;
 const kpis=[{t:'Recorded Runs',v:n(o?.recorded_runs),icon:Layers3,tone:'blue',trend:<Trend value={o?.trend.runs}/>},{t:'Completed',v:n(o?.completed),icon:CheckCircle2,tone:'green',trend:<Trend value={o?.trend.completed}/>},
  {t:'Blocked',v:n(o?.blocked),icon:XCircle,tone:'red',trend:<Trend value={o?.trend.blocked} invert/>},
  ...(singles?[{t:'Success Rate',v:pct(o?.success_rate),icon:Target,tone:'orange',trend:<Trend value={o?.trend.success_rate_pp} unit=" pp"/>},{t:'Avg. Odds',v:n(o?.avg_combined_odds,2),icon:BarChart3,tone:'blue',trend:<Trend value={o?.trend.avg_odds} unit=""/>}]
   :jackpot?[{t:'Avg. Legs',v:n(o?.avg_selections,1),icon:Target,tone:'orange',trend:<Trend value={o?.trend.avg_selections} unit=""/>},{t:'Avg. Odds',v:big(o?.avg_combined_odds),icon:BarChart3,tone:'blue',trend:<Trend value={o?.trend.avg_odds}/>}]
   :[{t:'Avg. Selections',v:n(o?.avg_selections,1),icon:Target,tone:'purple',trend:<Trend value={o?.trend.avg_selections} unit=""/>},{t:'Avg. Combined Odds',v:n(o?.avg_combined_odds,2),icon:BarChart3,tone:'blue',trend:<Trend value={o?.trend.avg_odds}/>}])];
 const firstFixture=(r:Run)=>r.legs[0]?r.legs[0].fixture+(r.selections>1&&singles?` +${r.selections-1} more`:''):'—';
 const runTable=(rows:Run[],full=false)=><div className="mi-table"><table><thead><tr><th>#</th><th>Run Time</th>{singles?<><th>Selection (Fixture)</th>{full&&<th>Singles</th>}<th>Odds</th></>:jackpot?<><th>Legs</th><th>Total Odds</th></>:<><th>Selections</th><th>Combined Odds</th></>}{full&&<><th>Probability bounds</th><th>Reasons / legs</th><th>Paper result</th></>}<th>Status</th></tr></thead>
  <tbody>{rows.map(r=><React.Fragment key={r.id}><tr className={full&&r.legs.length?'qo-row':''} onClick={()=>full&&setOpen(open===r.id?'':r.id)}><td><b>{r.number}</b></td><td>{fmt(r.created_at)}</td>{singles&&<td>{firstFixture(r)}</td>}{(!singles||full)&&<td>{r.selections}</td>}<td><b>{odds(r.combined_odds)}</b></td>
   {full&&<><td>{r.probability_upper_bound!=null?`${(r.probability_lower_bound!*100).toFixed(1)}–${(r.probability_upper_bound*100).toFixed(1)}%`:'—'}</td><td>{r.reasons.length?r.reasons.map(x=>REASON[x]||x).join(', '):`${r.legs.length} legs (click to expand)`}</td><td>{r.settlement||(r.status==='COMPLETED'?'Awaiting results':'—')}</td></>}
   <td><RunStatus value={r.status}/></td></tr>
   {full&&open===r.id&&<tr className="ae-legs"><td colSpan={9}>{r.legs.map(l=><div key={l.qualification_id}><b>{l.fixture}</b> · {l.market_key} {l.outcome_key} @ {l.odds.toFixed(2)} ({l.bookmaker}) · p {(l.probability*100).toFixed(1)}% · EV {l.ev>0?'+':''}{l.ev}%</div>)}</td></tr>}</React.Fragment>)}</tbody></table></div>;
 return <div className="dmr mi aq ae">
  {document.getElementById('deep-runtime-badge')&&createPortal(<span className={'dmr-runtime-badge '+(online?'online':'')}><Bot size={23}/>Autonomous Mode: {online?'ON':o?'OFF':'Checking'}<i/></span>,document.getElementById('deep-runtime-badge')!)}
  <div className="dmr-header"><div className="dmr-intro"><div className="dmr-eyebrow">BETTING PROGRAMMES</div><h2>{C.title}</h2><p>{C.description}</p></div>
   <div className="dmr-kpis aq-kpis">{kpis.map(k=><div className={k.tone} key={k.t}><k.icon/><span>{k.t}</span><b>{k.v}</b>{k.trend}</div>)}</div></div>
  <section className="dmr-pipeline mi-pipeline"><div className="dmr-pipeline-title"><Bot/><div><strong>{C.pipeline}</strong><small>{C.pipelineSub}</small></div></div>
   <div className="dmr-steps">{(o?.pipeline||[]).map((x,i,all)=><React.Fragment key={x.key}><div className="dmr-step" title={x.detail}><span className={x.status==='DONE'?'dmr-done':'dmr-wait'}>{x.status==='DONE'?<CheckCircle2/>:<Clock3/>}</span><b>{x.name}</b><small className="aq-sub">({x.sub})</small></div>{i<all.length-1&&<ArrowRight className="aip-arrow mi-arrow" aria-hidden="true"/>}</React.Fragment>)}</div>
   <div className="dmr-cycle"><span className={'dmr-mode '+(online?'online':'')}><RefreshCcw size={16}/>{online?'Running':o?'Worker offline':'Connecting'}</span><small>{o?'Next run: '+clock(o.next_run_at):'Updates automatically'}</small></div></section>
  {[ov,recent].some(x=>x.error)&&<div className="dmr-error" role="alert"><AlertTriangle size={16}/>Data unavailable: {[ov,recent].map(x=>x.error).filter(Boolean).join('; ')}</div>}
  <div className="dmr-tabs aip-tabs mi-tabs" role="tablist" aria-label={C.title+' views'}>{tabs.map(t=><button type="button" role="tab" aria-selected={tab===t.name} key={t.name} onClick={()=>setTab(t.name)} className={tab===t.name?'active':''}><t.icon size={18}/>{t.name}</button>)}</div>
  {tab==='Overview'?<div className="ae-grid">
   <section className="dmr-card"><div className="dmr-card-head"><h3><Settings2/>Programme Configuration</h3><span className="mi-chip muted" title="Policy is defined in code (optimizer.PROGRAMMES) and applied on every path"><Lock size={12}/>Read-only</span></div>
    {[...(programme!=='accumulator'?[['Programme',<span className="mi-chip info">{C.label}</span>]]:[]),['Mode',<span className="mi-chip info">{o?.mode||'PAPER'}</span>],['Readiness',<span className={'mi-chip '+(o?.readiness==='READY_FOR_QUALIFIED_DATA'?'good':'warn')}>{o?.readiness||'—'}</span>],['Min Legs',p?.min_legs],['Max Legs',p?.max_legs],['Max Odds',p?n(p.max_odds,jackpot?0:2):'—'],...(jackpot?[['Min Total Odds',p?.min_combined_odds?n(p.min_combined_odds):'—']]:[]),['Daily Cap',p?.daily_cap],...(singles?[['Paper stake',p?.paper_stake?`₦${p.paper_stake}`:'—'],['Used today',o?`${o.today.used} / ${o.today.cap}`:'—']]:[]),['Odds freshness',p?`≤ ${p.freshness_minutes} min`:'—']].map(([k,v]:any)=><div className="mi-row" key={k}><span>{k}</span><b>{v??'—'}</b></div>)}</section>
   <section className="dmr-card"><div className="dmr-card-head"><h3><Ticket/>Recent Programme Runs</h3><button type="button" className="ae-link" onClick={()=>setTab('Run History')}>View All <ArrowRight size={14}/></button></div>
    {recent.data?.items.length?runTable(recent.data.items):<Empty>{recent.loading?'Loading…':C.empty}</Empty>}</section>
   <section className="dmr-card ae-mode"><div className="dmr-card-head"><h3><Layers3/>Execution Mode</h3></div><div className="ae-paper"><b>PAPER</b><small>Simulation only • No live wagers</small></div>
    <div className="mi-row"><span><CalendarClock size={16}/>Auto Run (Scheduled)</span><span className={'mi-chip '+(online?'good':'warn')}>{online?'On':'Scheduler offline'}</span></div>
    <div className="mi-row"><span><Clock3 size={16}/>Next Scheduled Run</span><b>{fmt(o?.next_run_at)}{o?' WAT':''}</b></div></section>
   <section className="dmr-card"><div className="dmr-card-head"><h3><ShieldCheck/>Validation Requirements</h3><small>{n(o?.validation.qualified_upcoming)} qualified upcoming</small></div>
    {(o?.validation.items||[]).map(v=><div className="aq-gate" key={v.key} title={v.detail}><span>{v.name}</span><b>{pct(v.pass_rate)}</b><i><em style={{width:(v.pass_rate||0)+'%'}}/></i></div>)}
    {o&&!o.validation.qualified_upcoming&&<p className="dmr-caption">No qualified opportunities for upcoming fixtures yet, so there is nothing to validate.</p>}</section>
   <section className="dmr-card"><div className="dmr-card-head"><h3><BarChart3/>Programme Analytics <small>(last {n(o?.analytics.runs)} runs)</small></h3></div>
    <div className="ae-stats">{[...(singles?[['Success rate',pct(o?.analytics.paper_hit_rate),'good'],['Avg. odds',n(o?.analytics.avg_odds,2),''],['Total runs',n(o?.analytics.runs),'']]:
     jackpot?[['Success rate',pct(o?.analytics.paper_hit_rate),'good'],['Avg. legs',n(o?.analytics.avg_legs,1),''],['Avg. odds',big(o?.analytics.avg_odds),'']]:[['Completion rate',pct(o?.analytics.completion_rate),'good'],['Avg. legs',n(o?.analytics.avg_legs,1),''],['Avg. odds',n(o?.analytics.avg_odds,2),'']]),['Est. ROI (paper)',o?.analytics.paper_roi==null?'—':(o.analytics.paper_roi>0?'+':'')+o.analytics.paper_roi+'%',(o?.analytics.paper_roi??0)>0?'good':'']].map(([l,v,t])=><div key={l} className={t}><small>{l}</small><b>{v}</b></div>)}</div>
    <Chart points={o?.analytics.daily||[]}/><p className="dmr-caption">ROI only from runs whose every leg has a verified result ({n(o?.analytics.settled)} settled).</p></section>
   <section className="dmr-card"><div className="dmr-card-head"><h3><Activity/>System Status</h3></div>
    {(o?.system||[]).map(s=><div className="mi-row" key={s.name} title={s.detail}><span>{s.status==='HEALTHY'||s.status==='ACTIVE'?<CheckCircle2 className="good" size={18}/>:<Clock3 className="warn-ic" size={18}/>}{s.name}</span><span className={'mi-chip '+(s.status==='HEALTHY'?'good':s.status==='ACTIVE'?'info':'warn')}>{s.status.toLowerCase()}</span></div>)}</section>
  </div>
  :tab==='Programme Rules'?<div className="aq-two"><section className="dmr-card"><div className="dmr-card-head"><h3><SlidersHorizontal/>Programme rules</h3></div>
    {[['Selections per ticket',p?`${p.min_legs}–${p.max_legs}`:'—'],['Maximum combined odds',p?n(p.max_odds,jackpot?0:2):'—'],...(jackpot?[['Minimum combined odds',p?.min_combined_odds?n(p.min_combined_odds):'—'],['Candidate pool','20 best-EV fresh qualified opportunities (bounded search)']]:[]),['Daily ticket cap',p?.daily_cap],['Odds freshness',p?`≤ ${p.freshness_minutes} minutes`:'—'],['Fixtures per ticket','Unique (one selection per fixture)'],['Joint probability','Bounds only; independence never assumed'],['Schedule',p?`Every ${p.schedule_minutes} minutes (idempotent)`:'—'],['Execution','Paper composition; no wagers or booking codes']].map(([k,v]:any)=><div className="mi-row" key={k}><span>{k}</span><b>{v??'—'}</b></div>)}</section>
   <section className="dmr-card"><div className="dmr-card-head"><h3><ListChecks/>Eligibility now</h3></div><div className="mi-row hl"><span>Eligible fresh qualified opportunities</span><b>{n(o?.eligible_candidates)}</b></div>
    {o&&Object.keys(o.excluded).length?Object.entries(o.excluded).map(([k,v])=><div className="mi-row" key={k}><span>{REASON[k]||k}</span><b>{n(v)}</b></div>):<p className="dmr-caption">No qualified decisions were excluded.</p>}</section></div>
  :tab==='Run History'?<section className="dmr-card"><div className="dmr-card-head"><h3><History/>Run history ({n(history.data?.total)})</h3></div>
    {history.data?.items.length?runTable(history.data.items,true):<Empty>{history.loading?'Loading…':'No runs recorded yet.'}</Empty>}
    <div className="mi-pager"><span>Page {page+1} of {Math.max(1,Math.ceil((history.data?.total||0)/15))}</span><div><button type="button" aria-label="Previous page" disabled={page===0} onClick={()=>setPage(x=>x-1)}><ChevronLeft size={16}/></button><button type="button" aria-label="Next page" disabled={(page+1)*15>=(history.data?.total||0)} onClick={()=>setPage(x=>x+1)}><ChevronRight size={16}/></button></div></div></section>
  :tab==='Validation Requirements'?<section className="dmr-card"><div className="dmr-card-head"><h3><ShieldCheck/>Validation requirements</h3></div>
    {(o?.validation.items||[]).map(v=><div className="aq-gate" key={v.key}><span><b>{v.name}</b> — {v.detail}</span><b>{pct(v.pass_rate)}</b><i><em style={{width:(v.pass_rate||0)+'%'}}/></i></div>)}
    <p className="dmr-caption">Every leg must also be a QUALIFIED decision whose named gates (research, model, calibration, odds freshness, market mapping, value, lower-bound value, market risk) all passed, from an ACTIVE approved model, for an upcoming fixture.</p></section>
  :<section className="dmr-card"><div className="dmr-card-head"><h3><BarChart3/>Programme analytics</h3></div>
    <div className="ae-stats">{[['Runs analysed',n(o?.analytics.runs)],['Completion rate',pct(o?.analytics.completion_rate)],['Settled runs',n(o?.analytics.settled)],['Paper hit rate',pct(o?.analytics.paper_hit_rate)],['Est. ROI (paper)',o?.analytics.paper_roi==null?'—':o.analytics.paper_roi+'%']].map(([l,v])=><div key={l}><small>{l}</small><b>{v}</b></div>)}</div>
    <Chart points={o?.analytics.daily||[]}/>
    {o?.analytics.daily.length?<div className="mi-table"><table><thead><tr><th>Date</th><th>Runs</th><th>Completion rate</th></tr></thead><tbody>{[...o.analytics.daily].reverse().map(d=><tr key={d.date}><td>{d.date}</td><td>{d.runs}</td><td>{pct(d.completion_rate)}</td></tr>)}</tbody></table></div>:null}</section>}
  {o&&<p className="dmr-note">{o.notice}</p>}
 </div>;
}
