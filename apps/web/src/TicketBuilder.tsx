import {createPortal} from 'react-dom';
import React,{useEffect,useRef,useState} from 'react';
import {Activity,AlertTriangle,ArrowDown,ArrowRight,BarChart3,Barcode,Bot,BrainCircuit,CalendarDays,CheckCircle2,ChevronLeft,ChevronRight,Clock3,Crown,Database,FileText,History,
 LayoutGrid,Layers3,List,Lock,Network,RefreshCcw,RefreshCw,Settings2,ShieldCheck,SlidersHorizontal,Target,Ticket,XCircle} from 'lucide-react';
import {useResearchScope,useResearchRemote} from './ResearchCatalogue';
import './DeepMatchResearch.css';
import './MarketIntelligence.css';
import './AIQualification.css';
import './AccumulatorEngine.css';
import './TicketBuilder.css';

const API='/api/v1/sports/tickets/builder/';
type Leg={qualification_id:string;fixture:string;market_key:string;outcome_key:string;odds:number;probability:number;ev:number;bookmaker:string};
type Item={number:number;programme:string;programme_name:string;run_id:string;built_at:string;registered_at:string;legs:number;combined_odds:number|null;status:string;reason:string|null;
 ticket_id:string|null;betslip_id:string|null;linked:boolean;selections:Leg[];probability_lower_bound:number|null;probability_upper_bound:number|null;paper_stake:number|null;potential_return:number|null};
type Rule={programme:string;name:string;min_legs:number;max_legs:number;max_odds:number;daily_cap:number;paper_stake:number|null;schedule:string;min_combined_odds:number|null;
 leg_targets:number[]|null;target_band?:number[];plan_days?:number;cap_unit:string};
type Overview={mode:string;programme:string;readiness:string;recorded_items:number;built:number;rejected:number;build_rate:number|null;avg_legs:number|null;
 trend:{items:number|null;built:number|null;rejected:number|null;build_rate_pp:number|null;avg_legs:number|null};next_run_at:string|null;runtime:{worker_online:boolean};
 pipeline:{key:string;name:string;sub:string;status:string;detail:string}[];recent:Item[];latest:Item|null;rules:Rule[];lifecycle:{tickets:number;betslips:number;booking_codes:number};
 system:{name:string;status:string;detail:string}[];checks:string[];notice:string;
 analytics:{by_programme:{programme:string;name:string;registered:number;rejected:number}[];rejection_reasons:Record<string,number>;linked:number;daily:{date:string;build_rate:number;items:number}[]}};

const fmt=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v)):'—';
const clock=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v))+' WAT':'—';
const n=(v?:number|null,d=0)=>v==null?'—':v.toLocaleString('en-NG',{minimumFractionDigits:d,maximumFractionDigits:d});
const pct=(v?:number|null)=>v==null?'—':v.toFixed(1)+'%';
const odds=(v?:number|null)=>v==null?'—':v>=10000?n(v,0):v.toFixed(2);
const REASON:Record<string,string>={ODDS_NOT_FRESH:'Odds older than 15 minutes at registration',NOT_QUALIFIED:'Decision no longer QUALIFIED',QUALIFICATION_GATES_INCOMPLETE:'Named gates incomplete',
 MISSING_FORECAST_OR_PRICE:'Forecast or price missing',MARKET_MAPPING_MISMATCH:'Market mapping mismatch',FIXTURE_STARTED_OR_MISSING:'Fixture started',CORRELATED_SAME_FIXTURE:'Two legs on one fixture',
 BOOKMAKER_MISMATCH:'Legs priced by different bookmakers',COMBINED_ODDS_OVER_PROGRAMME_LIMIT:'Above programme odds ceiling',JACKPOT_TARGET_NOT_REACHED:'Below jackpot odds floor',
 ROLLOVER_ODDS_OUTSIDE_RANGE:'Outside rollover odds range',DAILY_EXPOSURE_LIMIT_REACHED:'Daily exposure cap reached',DRAW_LEG_COUNT_INVALID:'Invalid draw leg count',SINGLES_REQUIRES_ONE_LEG:'Singles need one leg'};
const tabs=[{name:'Overview',icon:LayoutGrid},{name:'Ticket Builder',icon:SlidersHorizontal},{name:'Tickets & History',icon:History},{name:'Validation Requirements',icon:ShieldCheck},{name:'Programme Analytics',icon:BarChart3}];
const tiles=[{k:'singles',t:'Singles',s:'1 selection',i:Layers3},{k:'accumulator',t:'Accumulator',s:'2–12 legs',i:Network},{k:'jackpot',t:'Jackpot',s:'High-odds combinations',i:Crown},
 {k:'draws',t:'Weekly Draw',s:'2, 5, 8 or 10 draws',i:CalendarDays},{k:'rollover',t:'Daily Rollover',s:'Sequential daily selections',i:RefreshCw}];

function Status({item}:{item:Item}){const ok=item.status==='REGISTERED';return <span className={'mi-chip '+(ok?'good':'bad')} title={item.reason?REASON[item.reason]||item.reason:item.linked?'Linked to an existing ticket with the same legs':''}>{ok?<CheckCircle2 size={12}/>:<XCircle size={12}/>}{ok?'Registered':'Rejected'}</span>}
function Trend({value,unit='%',invert=false}:{value?:number|null;unit?:string;invert?:boolean}){if(value==null)return null;const up=value>=0;return <small className={'aq-trend '+((invert?!up:up)?'good':'bad')}>{up?'↑':'↓'} {up?'+':''}{value}{unit}</small>}
function Empty({children}:{children:React.ReactNode}){return <div className="dmr-data-empty">{children}</div>}
function ruleText(r:Rule){
 if(r.programme==='singles')return `1 leg, max ${r.daily_cap} tickets/day${r.paper_stake?`, ₦${r.paper_stake} paper stake each`:''}`;
 if(r.programme==='accumulator')return `${r.min_legs}–${r.max_legs} legs, max combined odds ${n(r.max_odds)}, daily cap ${r.daily_cap}`;
 if(r.programme==='jackpot')return `${r.min_legs}–${r.max_legs} legs, combined odds ${n(r.min_combined_odds)}–${n(r.max_odds)}, daily cap ${r.daily_cap}`;
 if(r.programme==='draws')return `${(r.leg_targets||[]).join(', ')} full-time draw legs, max odds ${n(r.max_odds)}, ${r.schedule}`;
 return `Sequential daily plan, target odds ${r.target_band?r.target_band.map(x=>x.toFixed(2)).join('–'):'—'}, up to ${r.plan_days} days, ${r.schedule}`;
}
function Chart({points}:{points:{date:string;build_rate:number}[]}){
 if(points.length<2)return <Empty>The build-rate trend appears after registrations on at least two days.</Empty>;
 const W=520,H=150,P=28;const x=(i:number)=>P+i*(W-P*2)/(points.length-1);const y=(v:number)=>H-P-(v/100)*(H-P*1.6);
 const line=points.map((p,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(p.build_rate).toFixed(1)}`).join(' ');
 return <svg className="ae-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Daily build rate">{[0,50,100].map(v=><g key={v}><line x1={P} x2={W-P} y1={y(v)} y2={y(v)}/><text x={4} y={y(v)+4}>{v}%</text></g>)}
  <path className="area" d={`${line} L${x(points.length-1)},${H-P} L${x(0)},${H-P} Z`}/><path className="line" d={line}/>{points.map((p,i)=><circle key={p.date} cx={x(i)} cy={y(p.build_rate)} r={3.5}><title>{p.date}: {p.build_rate}%</title></circle>)}</svg>;
}

export default function TicketBuilder(){
 const {revision,refresh}=useResearchScope();
 const[tab,setTab]=useState('Overview'),[page,setPage]=useState(0),[open,setOpen]=useState(''),[status,setStatus]=useState(''),[prog,setProg]=useState('');
 const ov=useResearchRemote<Overview>(API+'overview',revision);
 const history=useResearchRemote<{total:number;items:Item[]}>(tab==='Tickets & History'?API+'register?'+new URLSearchParams({limit:'15',offset:String(page*15),...(status?{status}:{}),...(prog?{programme:prog}:{})}):null,revision);
 const refreshRef=useRef(refresh);refreshRef.current=refresh;
 useEffect(()=>{const t=setInterval(()=>refreshRef.current(),60000);return()=>clearInterval(t)},[]);
 const o=ov.data;const online=o?.runtime.worker_online;const latest=o?.latest;
 const kpis=[{t:'Recorded Items',v:n(o?.recorded_items),icon:Layers3,tone:'blue',trend:<Trend value={o?.trend.items}/>},{t:'Built Tickets',v:n(o?.built),icon:ShieldCheck,tone:'green',trend:<Trend value={o?.trend.built}/>},
  {t:'Rejected',v:n(o?.rejected),icon:XCircle,tone:'red',trend:<Trend value={o?.trend.rejected} invert/>},{t:'Build Rate',v:pct(o?.build_rate),icon:Target,tone:'orange',trend:<Trend value={o?.trend.build_rate_pp} unit=" pp"/>},
  {t:'Avg. Legs',v:n(o?.avg_legs,1),icon:BarChart3,tone:'blue',trend:<Trend value={o?.trend.avg_legs} unit=""/>}];
 const table=(rows:Item[],full=false)=><div className="mi-table"><table><thead><tr><th>#</th>{full&&<th>Registered</th>}<th>Programme</th><th>Legs</th><th>Total Odds</th>{full&&<><th>Probability bounds</th><th>Reason / ticket</th></>}<th>Status</th></tr></thead>
  <tbody>{rows.map(r=><React.Fragment key={r.run_id+r.number}><tr className={full?'qo-row':''} onClick={()=>full&&setOpen(open===r.run_id+r.number?'':r.run_id+r.number)}><td><b>{n(r.number)}</b></td>{full&&<td>{fmt(r.registered_at)}</td>}<td>{r.programme_name}</td><td>{r.legs}</td><td><b>{odds(r.combined_odds)}</b></td>
   {full&&<><td>{r.probability_upper_bound!=null?`${((r.probability_lower_bound||0)*100).toFixed(1)}–${(r.probability_upper_bound*100).toFixed(1)}%`:'—'}</td><td>{r.reason?REASON[r.reason]||r.reason:r.linked?'Linked to existing ticket':'Ticket + betslip created'}</td></>}<td><Status item={r}/></td></tr>
   {full&&open===r.run_id+r.number&&<tr className="ae-legs"><td colSpan={8}>{r.selections.map(l=><div key={l.qualification_id}><b>{l.fixture}</b> · {l.market_key} {l.outcome_key} @ {l.odds.toFixed(2)} ({l.bookmaker}) · p {(l.probability*100).toFixed(1)}%</div>)}{r.ticket_id&&<div className="tb-id">Ticket {r.ticket_id}</div>}</td></tr>}</React.Fragment>)}</tbody></table></div>;
 const rulesTable=<div className="mi-table tb-rules"><table><thead><tr><th>Programme</th><th>Ticket-building rules</th></tr></thead><tbody>{(o?.rules||[]).map(r=><tr key={r.programme}><td><b>{r.name}</b></td><td>{ruleText(r)}</td></tr>)}</tbody></table></div>;
 return <div className="dmr mi aq ae tb">
  {document.getElementById('deep-runtime-badge')&&createPortal(<span className={'dmr-runtime-badge '+(online?'online':'')}><Bot size={23}/>Autonomous Mode: {online?'ON':o?'OFF':'Checking'}<i/></span>,document.getElementById('deep-runtime-badge')!)}
  <div className="dmr-header"><div className="dmr-intro"><div className="dmr-eyebrow">TICKET &amp; BOOKING</div><h2>Ticket Builder</h2><p>Constructed paper tickets and selection validation using qualified opportunities and strict risk controls.</p></div>
   <div className="dmr-kpis aq-kpis">{kpis.map(k=><div className={k.tone} key={k.t}><k.icon/><span>{k.t}</span><b>{k.v}</b>{k.trend}</div>)}</div></div>
  <section className="dmr-pipeline mi-pipeline"><div className="dmr-pipeline-title"><Bot/><div><strong>Autonomous Ticket Pipeline</strong><small>From qualified opportunities to paper tickets (fully automated)</small></div></div>
   <div className="dmr-steps">{(o?.pipeline||[]).map((x,i,all)=><React.Fragment key={x.key}><div className="dmr-step" title={x.detail}><span className={x.status==='DONE'?'dmr-done':'dmr-wait'}>{x.status==='DONE'?<CheckCircle2/>:<Clock3/>}</span><b>{x.name}</b><small className="aq-sub">({x.sub})</small></div>{i<all.length-1&&<ArrowRight className="aip-arrow mi-arrow" aria-hidden="true"/>}</React.Fragment>)}</div>
   <div className="dmr-cycle"><span className={'dmr-mode '+(online?'online':'')}><RefreshCcw size={16}/>{online?'Running':o?'Worker offline':'Connecting'}</span><small>{o?.next_run_at?'Next run: '+clock(o.next_run_at):'Updates automatically'}</small></div></section>
  {ov.error&&<div className="dmr-error" role="alert"><AlertTriangle size={16}/>Data unavailable: {ov.error}</div>}
  <div className="dmr-tabs aip-tabs mi-tabs" role="tablist" aria-label="Ticket Builder views">{tabs.map(t=><button type="button" role="tab" aria-selected={tab===t.name} key={t.name} onClick={()=>setTab(t.name)} className={tab===t.name?'active':''}><t.icon size={18}/>{t.name}</button>)}</div>
  {tab==='Overview'?<div className="tb-grid">
   <section className="dmr-card tb-flow"><div className="dmr-card-head"><h3><Settings2/>How Tickets Are Built <small>(Process Flow)</small></h3></div>
    <div className="tb-box"><Database/><div><b>Qualified Opportunities</b><small>Verified fixtures, markets, odds and AI probabilities</small></div></div><ArrowDown className="tb-down"/>
    <div className="tb-box"><BrainCircuit/><div><b>Ticket Optimisation</b><small>Bounded combinations per programme; one selection per fixture; probability bounds, never independence</small></div></div><ArrowDown className="tb-down"/>
    <div className="tb-tiles">{tiles.map(t=><div key={t.k}><t.i/><b>{t.t}</b><small>{t.s}</small></div>)}</div><ArrowDown className="tb-down"/>
    <div className="tb-box good"><ShieldCheck/><div><b>Final Validation</b><small>Odds freshness, market identity, bookmaker, odds limits, daily caps and duplicates</small></div></div><ArrowDown className="tb-down"/>
    <div className="tb-box good"><Ticket/><div><b>Ticket Created and Registered</b><small>Stored in PostgreSQL with a paper betslip, passed to Betslip Preparation, then Booking Codes only when verified</small></div></div></section>
   <section className="dmr-card tb-config"><div className="dmr-card-head"><h3><Settings2/>Programme Configuration</h3><span className="mi-chip muted" title="Rules are defined in code (optimizer.PROGRAMMES, programme_engine.SETTINGS)"><Lock size={12}/>Read-only</span></div>
    {[['Programme',<span className="mi-chip info">{o?.programme||'TICKET_BUILDER'}</span>],['Mode',<span className="mi-chip info">{o?.mode||'PAPER'}</span>],
      ['Readiness',<span className={'mi-chip '+(o?.readiness==='READY_FOR_QUALIFIED_DATA'?'good':'warn')}>{o?.readiness||'—'}</span>],['Programmes',o?.rules.length],
      ['Odds freshness','≤ 15 min at registration'],['Registration cadence','Every minute (autonomy cycle)'],['Booking codes','Only when verified; never generated']].map(([k,v]:any)=><div className="mi-row" key={k}><span>{k}</span><b>{v??'—'}</b></div>)}</section>
   <section className="dmr-card tb-recent"><div className="dmr-card-head"><h3><Ticket/>Recent Paper Tickets</h3><button type="button" className="ae-link" onClick={()=>setTab('Tickets & History')}>View All <ArrowRight size={14}/></button></div>
    {o?.recent.length?table(o.recent):<Empty>{ov.loading?'Loading…':'No tickets yet. The builder registers programme tickets every minute once the programmes complete a run.'}</Empty>}</section>
   <section className="dmr-card tb-latest"><div className="dmr-card-head"><h3><FileText/>Latest Registered Ticket</h3>{latest&&<small>{latest.programme_name} · {fmt(latest.registered_at)}</small>}</div>
    {latest?<><div className="mi-table"><table><thead><tr><th>Selection</th><th>Market</th><th>Odds</th><th>Model prob.</th></tr></thead><tbody>{latest.selections.map(l=><tr key={l.qualification_id}><td>{l.fixture}</td><td>{l.market_key} {l.outcome_key}</td><td>{l.odds.toFixed(2)}</td><td className="good-t">{(l.probability*100).toFixed(1)}%</td></tr>)}</tbody></table></div>
     <div className="tb-sum"><div className="hl"><b>{latest.legs}-Leg {latest.programme_name}</b></div><div><small>Combined Odds</small><b>{odds(latest.combined_odds)}</b></div><div><small>Stake</small><b>{latest.paper_stake?'₦'+n(latest.paper_stake,latest.paper_stake%1?2:0):'—'}</b></div><div><small>Potential Return</small><b className="good-t">{latest.potential_return?'₦'+n(latest.potential_return,2):'—'}</b></div></div>
     <p className="dmr-caption">Joint win probability is bounded at {latest.probability_upper_bound!=null?`${((latest.probability_lower_bound||0)*100).toFixed(1)}–${(latest.probability_upper_bound*100).toFixed(1)}%`:'—'}; independence between legs is never assumed.</p></>
     :<Empty>No ticket has been registered yet. A real ticket appears here once a programme builds one from qualified opportunities — no illustrative example is shown.</Empty>}</section>
   <section className="dmr-card tb-rulescard"><div className="dmr-card-head"><h3><Layers3/>Programme Rules <small>(Ticket Generation)</small></h3></div>{rulesTable}</section>
   <section className="dmr-card tb-life"><div className="dmr-card-head"><h3><Layers3/>Ticket Lifecycle <small>(Post-Build)</small></h3></div>
    <div className="tb-lifecycle"><div className="g"><Settings2/><div><b>Ticket Builder</b><small>{n(o?.lifecycle.tickets)} registered tickets</small></div></div><ArrowRight/>
     <div className="b"><List/><div><b>Betslip Preparation</b><small>{n(o?.lifecycle.betslips)} paper betslips</small></div></div><ArrowRight/>
     <div className="p"><Barcode/><div><b>Booking Codes</b><small>{n(o?.lifecycle.booking_codes)} verified codes (when supported)</small></div></div></div></section>
   <section className="dmr-card tb-system"><div className="dmr-card-head"><h3><Activity/>System Status</h3></div>
    {(o?.system||[]).map(s=><div className="mi-row" key={s.name} title={s.detail}><span>{s.status==='HEALTHY'||s.status==='ACTIVE'?<CheckCircle2 className="good" size={18}/>:<Clock3 className="warn-ic" size={18}/>}{s.name}</span><span className={'mi-chip '+(s.status==='HEALTHY'?'good':s.status==='ACTIVE'?'info':'warn')}>{s.status.toLowerCase()}</span></div>)}</section>
  </div>
  :tab==='Ticket Builder'?<div className="aq-two"><section className="dmr-card"><div className="dmr-card-head"><h3><SlidersHorizontal/>Programme rules</h3></div>{rulesTable}
    <p className="dmr-caption">Tickets are composed by each programme engine on its own schedule; the builder registers them. Rules come from code and apply on every path.</p></section>
   <section className="dmr-card"><div className="dmr-card-head"><h3><Ticket/>Register by programme</h3></div>{(o?.analytics.by_programme||[]).map(p=><div className="mi-row" key={p.programme}><span>{p.name}</span><b>{n(p.registered)} registered · {n(p.rejected)} rejected</b></div>)}
    <div className="mi-row hl"><span>Linked to tickets prepared by the 12-stage pipeline</span><b>{n(o?.analytics.linked)}</b></div></section></div>
  :tab==='Tickets & History'?<section className="dmr-card"><div className="dmr-card-head"><h3><History/>Ticket register ({n(history.data?.total)})</h3>
    <div className="tb-filters"><select aria-label="Status" value={status} onChange={e=>{setStatus(e.target.value);setPage(0)}}><option value="">All statuses</option><option value="REGISTERED">Registered</option><option value="REJECTED">Rejected</option></select>
     <select aria-label="Programme" value={prog} onChange={e=>{setProg(e.target.value);setPage(0)}}><option value="">All programmes</option>{tiles.map(t=><option key={t.k} value={t.k}>{t.t}</option>)}</select></div></div>
    {history.data?.items.length?table(history.data.items,true):<Empty>{history.loading?'Loading…':'No tickets recorded yet.'}</Empty>}
    <div className="mi-pager"><span>Page {page+1} of {Math.max(1,Math.ceil((history.data?.total||0)/15))}</span><div><button type="button" aria-label="Previous page" disabled={page===0} onClick={()=>setPage(x=>x-1)}><ChevronLeft size={16}/></button><button type="button" aria-label="Next page" disabled={(page+1)*15>=(history.data?.total||0)} onClick={()=>setPage(x=>x+1)}><ChevronRight size={16}/></button></div></div></section>
  :tab==='Validation Requirements'?<div className="aq-two"><section className="dmr-card"><div className="dmr-card-head"><h3><ShieldCheck/>Checked at registration</h3></div>
    {(o?.checks||[]).map(c=><div className="mi-row" key={c}><span><CheckCircle2 className="good" size={16}/>{c}</span></div>)}
    <p className="dmr-caption">Checks run in tickets.service.prepare_paper_ticket, the single writer of tickets, legs and betslips. A failed check rejects the ticket with its reason; nothing is retried or padded.</p></section>
   <section className="dmr-card"><div className="dmr-card-head"><h3><XCircle/>Rejection reasons</h3></div>
    {o&&Object.keys(o.analytics.rejection_reasons).length?Object.entries(o.analytics.rejection_reasons).sort((a,b)=>b[1]-a[1]).map(([k,v])=><div className="mi-row" key={k}><span>{REASON[k]||k}</span><b>{n(v)}</b></div>):<p className="dmr-caption">No tickets have been rejected.</p>}</section></div>
  :<section className="dmr-card"><div className="dmr-card-head"><h3><BarChart3/>Programme analytics</h3></div>
    <div className="ae-stats">{[['Recorded items',n(o?.recorded_items)],['Build rate',pct(o?.build_rate)],['Avg. legs',n(o?.avg_legs,1)],['Linked (no duplicate)',n(o?.analytics.linked)]].map(([l,v])=><div key={l}><small>{l}</small><b>{v}</b></div>)}</div>
    <Chart points={o?.analytics.daily||[]}/>
    <div className="mi-table"><table><thead><tr><th>Programme</th><th>Registered</th><th>Rejected</th><th>Build rate</th></tr></thead><tbody>{(o?.analytics.by_programme||[]).map(p=><tr key={p.programme}><td>{p.name}</td><td>{n(p.registered)}</td><td>{n(p.rejected)}</td><td>{pct(p.registered+p.rejected?p.registered*100/(p.registered+p.rejected):null)}</td></tr>)}</tbody></table></div></section>}
  {o&&<p className="dmr-note">{o.notice}</p>}
 </div>;
}
