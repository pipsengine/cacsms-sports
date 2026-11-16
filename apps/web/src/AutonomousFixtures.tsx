import React,{useEffect,useState} from 'react';
import {createPortal} from 'react-dom';
import {NavLink} from 'react-router-dom';
import {Activity,Bot,CalendarDays,CheckCircle2,ChevronLeft,ChevronRight,Clock3,Database,Dribbble,Ellipsis,Globe2,Layers3,Radio,RefreshCw,Settings2,ShieldAlert,ShieldCheck,Trophy,Volleyball,WifiOff,Workflow} from 'lucide-react';
import {useResearchScope,useResearchRemote} from './ResearchCatalogue';
import {useLiveUpdates} from './LiveUpdates';
import {aggregateStatus,toneOf,type FlowCounts} from './StageFlow';
import {stageHref,workflowStages} from './workflowStages';
import './AutonomousFixtures.css';

const API='/api/v1/sports/fixture-intelligence/overview';
const CATALOG='/api/v1/sports/research/catalog/';
type Sport={id:string;name:string;competitions:number;fixtures_window:number};
type Competition={id:string;name:string;country:string|null;sport:string;fixtures_window:number;fixtures_total:number};
type Country={name:string;competitions:number;fixtures_window:number};
type Pipe={run_id:string;status:string;run_outcome:string|null;settled:number;current_stage:string|null;current_status:string;outcome_stage:string|null;outcome:string|null;stages:{key:string;status:string}[]};
type Row={id:string;kickoff_at:string;home:string;away:string;status:string|null;sport:string;competition:{id:string;name:string;country:string|null};market_focus:string|null;
 odds:{min:number;max:number;quotes:number;bookmakers:number;observed_at:string|null;fresh:boolean}|null;
 prediction:{market:string;outcome:string;probability:number;interval?:{lower:number;upper:number}|null}|null;pipeline:Pipe|null;result:{version:number}|null};
type StageAgg=FlowCounts&{key:string;name:string;counts:Record<string,number>};
type Engine={stage:string;name:string;state:string;detail:string};
type Overview={updated_at:string;metrics:{sports:number;competitions:number;countries:number;teams:number;fixtures_window:number;live_fixtures:number;window_hours:number};
 sports:Sport[];competitions:Competition[];countries:Country[];fixtures:{total:number;page:number;page_size:number;pages:number;rows:Row[]};
 pipeline:{runs:number;fixtures_in_scope:number;run_status:Record<string,number>;stages:StageAgg[]};
 coverage:{fixtures:number;verified_dossiers:number;partial_dossiers:number;team_statistics:number;observations:number};
 activity:{at:string;stage:string;stage_name:string;status:string;failure_code:string|null;fixture:string|null;fixture_id:string|null;run_id:string}[];
 automation:{runtime:{status:string;worker_online:boolean;interval_seconds:number;finished_at?:string|null;last_success_at?:string|null};engines:Engine[];interval_seconds:number;authorized_sources:number;acquisition_jobs:Record<string,number>}};

const TABS=['Fixtures','Competitions','Countries','Leagues & Divisions','Research Coverage'] as const;
const STATUSES=[['upcoming','Upcoming'],['live','Live'],['completed','Completed'],['all','All']] as const;
const HOURS=72;
const fmt=new Intl.NumberFormat('en-NG');
const n=(v?:number|null)=>v===null||v===undefined?'—':fmt.format(v);
const watDate=(v?:string|null)=>{if(!v)return '—';const d=new Date(v);return Number.isNaN(d.getTime())?'—':new Intl.DateTimeFormat('en-NG',{weekday:'short',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(d)};
const watTime=(v?:string|null)=>{if(!v)return '—';const d=new Date(v);return Number.isNaN(d.getTime())?'—':new Intl.DateTimeFormat('en-NG',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(d)};
const words=(v?:string|null)=>(v||'').replaceAll('_',' ').toLowerCase().replace(/^./,c=>c.toUpperCase());
const initials=(name:string)=>name.split(/\s+/).filter(Boolean).slice(0,2).map(w=>w[0]).join('').toUpperCase()||'?';
const hue=(name:string)=>[...name].reduce((h,c)=>(h*31+c.charCodeAt(0))%360,7);
const stageName=(key?:string|null)=>workflowStages.find(s=>s[0]===key)?.[1]||'—';
function sportIcon(name:string){const s=name.toLowerCase();if(s.includes('basket'))return <Dribbble/>;if(s.includes('volley')||s.includes('tennis'))return <Volleyball/>;if(s.includes('foot')||s.includes('soccer'))return <Trophy/>;return <Globe2/>}
const RUN_TONE:Record<string,string>={COMPLETED:'good',MONITORING:'good',WAITING_FOR_DATA:'warn',RETRY_SCHEDULED:'warn',PENDING:'muted',BLOCKED:'bad',FAILED:'bad'};

function Team({name}:{name:string}){return <span className="af-team"><span className="af-avatar" style={{background:`hsl(${hue(name)} 70% 92%)`,color:`hsl(${hue(name)} 55% 32%)`}} aria-hidden="true">{initials(name)}</span><span>{name}</span></span>}

function pageList(page:number,pages:number){const out:(number|'…')[]=[];const add=(p:number)=>{if(!out.includes(p))out.push(p)};
 for(let p=1;p<=Math.min(pages,5);p++)add(p);if(page>4&&page<pages-1){out.push('…');add(page-1);add(page);add(page+1)}if(pages>5){if(out[out.length-1]!==pages-1&&!(out.includes(pages-1)))out.push('…');add(pages)}return out}

export default function AutonomousFixtures(){
 const{selection:s,change,revision,refresh}=useResearchScope();const{connected}=useLiveUpdates();
 const[tab,setTab]=useState<typeof TABS[number]>('Fixtures'),[status,setStatus]=useState<string>('upcoming'),[page,setPage]=useState(1);
 useEffect(()=>setPage(1),[s.sport,s.country,s.league,s.season,status]);
 const query=new URLSearchParams({hours:String(HOURS),status,page:String(page),page_size:'5'});
 if(s.sport)query.set('sport',s.sport);if(s.country)query.set('country',s.country);if(s.league)query.set('competition_id',s.league);if(s.season)query.set('season_id',s.season);
 const data=useResearchRemote<Overview>(API+'?'+query,revision);
 const[last,setLast]=useState<Overview|null>(null);useEffect(()=>{if(data.data)setLast(data.data)},[data.data]);
 const o=data.data||last;
 const sports=useResearchRemote<{id:string;name:string}[]>(CATALOG+'sports',revision);
 const countries=useResearchRemote<{name:string}[]>(s.sport?CATALOG+'countries?sport='+encodeURIComponent(s.sport):null,revision);
 const leagues=useResearchRemote<{id:string;name:string}[]>(s.sport?CATALOG+'leagues?sport='+encodeURIComponent(s.sport)+(s.country?'&country='+encodeURIComponent(s.country):''):null,revision);
 const seasons=useResearchRemote<{id:string;label:string}[]>(s.league?CATALOG+'seasons?league_id='+encodeURIComponent(s.league):null,revision);
 const online=!!o?.automation.runtime.worker_online;
 const select=(c:Competition)=>{change('sport',c.sport);if(c.country)change('country',c.country);change('league',c.id);setTab('Fixtures')};
 const topSports=(o?.sports||[]).slice(0,3);const others=(o?.sports||[]).slice(3);
 const steps=(o?.pipeline.stages||workflowStages.map(([key,name])=>({key,name,total:0,verified:0,settled:0,outcomes:0,waiting:0,blocked:0,counts:{}}))).map((st,i)=>({key:st.key,name:st.name,status:aggregateStatus(st),
  caption:st.total?`${n(st.settled)}/${n(st.total)} settled`:'No runs yet',meta:[st.waiting?`${n(st.waiting)} waiting`:'',st.outcomes?`${n(st.outcomes)} outcomes`:'',st.blocked?`${n(st.blocked)} blocked`:''].filter(Boolean).join(' · ')||undefined,
  counts:st.total?st:undefined,href:stageHref(i),title:Object.entries(st.counts||{}).map(([k,v])=>words(k)+': '+v).join(', ')||'No pipeline runs in scope'}));
 const completedRuns=o?.pipeline.run_status.COMPLETED||0;
 const scopeLabel=[s.sport||'All sports',s.country,o?.competitions.find(c=>c.id===s.league)?.name].filter(Boolean).join(' • ');
 const fx=o?.fixtures;const first=fx&&fx.total?(fx.page-1)*fx.page_size+1:0;const lastRow=fx?Math.min(fx.total,fx.page*fx.page_size):0;
 const title={upcoming:'Upcoming Fixtures',live:'Live Fixtures',completed:'Completed Fixtures',all:'Fixtures'}[status];
 const period={upcoming:`Next ${HOURS} hours`,live:'In play now',completed:`Last ${HOURS} hours`,all:`±${HOURS} hours`}[status];

 return <div className="af-root">
  {document.getElementById('fixtures-runtime-badge')&&createPortal(<span className={'af-runtime-badge '+(online?'online':'offline')}><Bot size={24}/>Autonomous Mode: {online?'ON':'OFF'}<span className="af-dot"/></span>,document.getElementById('fixtures-runtime-badge')!)}
  <section className="af-top"><div className="af-intro"><div className="af-eyebrow">SPORTS INTELLIGENCE</div><div className="af-title-line"><h2>Fixtures &amp; Competitions</h2><span className={'af-mode'+(online?'':' af-mode-off')}><Bot size={15}/>{o?online?'Autonomous':'Controller offline':'Connecting'}</span></div><p>Autonomous discovery, update and research of sports, competitions, seasons and fixtures from authorized sources.</p></div>
   <div className="af-metrics">
    <div className="af-metric blue"><span className="af-metric-icon"><Trophy/></span><span>Sports<strong>{n(o?.metrics.sports)}</strong><small>{n(o?.metrics.countries)} countries</small></span></div>
    <div className="af-metric violet"><span className="af-metric-icon"><Layers3/></span><span>Competitions<strong>{n(o?.metrics.competitions)}</strong><small>{n(o?.metrics.teams)} canonical teams</small></span></div>
    <div className="af-metric green"><span className="af-metric-icon"><CalendarDays/></span><span>Fixtures ({HOURS}h)<strong>{n(o?.metrics.fixtures_window)}</strong><small>Upcoming, all sports</small></span></div>
    <div className="af-metric orange"><span className="af-metric-icon"><Radio/></span><span>Live fixtures<strong>{n(o?.metrics.live_fixtures)}</strong><small>Reported in play</small></span></div>
   </div></section>

  <section className="af-card af-pipeline" aria-label="Autonomous research pipeline"><div className="af-card-head"><div className="af-pipeline-title"><span className="af-pipeline-icon"><Bot/></span><div><h3>Autonomous Research Pipeline</h3><p>{o?`${n(o.pipeline.runs)} fixture runs in scope · ${n(completedRuns)} completed · self-running, no manual initiation`:'Loading pipeline progress…'}</p></div></div><span className={'af-pill '+(online?'good':'warn')}><span className="af-dot"/>{online?'Running':o?words(o.automation.runtime.status):'Checking'}</span></div>
   <ol className="af-reference-flow" aria-label="Research pipeline">{[
 {name:'Discover',keys:['discover'],caption:n(o?.metrics.sports)+' sports'},
 {name:'Extract',keys:['acquire'],caption:n(o?.metrics.competitions)+' comps'},
 {name:'Validate',keys:['research'],caption:o?n(o.coverage.verified_dossiers)+' verified':'Checking'},
 {name:'Analyze',keys:['analyse'],caption:n(o?.metrics.fixtures_window)+' fixtures'},
 {name:'Update',keys:['monitor'],caption:connected?'Live sync':'Connecting'}
 ].map(step=>{const actual=steps.find(x=>step.keys.includes(x.key));const tone=toneOf(actual?.status);return <li key={step.name} className={'tone-'+tone}><NavLink to={actual?.href||'/sports/orchestrator'} title={actual?.title}><span>{tone==='done'?<CheckCircle2/>:tone==='blocked'?<ShieldAlert/>:<Clock3/>}</span><b>{step.name}</b><small>{step.caption}</small></NavLink><ChevronRight className="af-flow-arrow"/></li>})}</ol></section>

  {data.error&&<div className="af-error" role="alert">Fixture intelligence unavailable: {data.error}</div>}

  <div className="af-columns"><div className="af-primary">
   <section className="af-card"><div className="af-card-head"><div><h3><Layers3 size={19}/> Competition Intelligence <span className="af-sub">(Auto-Discovery)</span></h3><p>Catalogue of sports, countries, leagues and seasons maintained from authorized sources.</p></div><span className={'af-pill '+(online?'good':'warn')}><RefreshCw size={14}/>{online?'Self-updating':'Updates paused'}</span></div>
    <div className="af-sport-tiles">{topSports.map((sp,i)=><button type="button" key={sp.id} className={'af-sport t'+i+(s.sport===sp.name?' active':'')} aria-pressed={s.sport===sp.name} onClick={()=>change('sport',s.sport===sp.name?'':sp.name)}><span className="af-sport-icon">{sportIcon(sp.name)}</span><span><b>{sp.name}</b><small>{n(sp.competitions)} comps · {n(sp.fixtures_window)} fixtures</small></span></button>)}
     {others.length>0&&<div className="af-sport t3"><span className="af-sport-icon"><Ellipsis/></span><span><b>Other sports</b><small>{n(others.reduce((a,b)=>a+b.competitions,0))} comps · {others.length} sports</small></span></div>}
     {o&&!o.sports.length&&<div className="af-empty-small">No sports registered yet. The authorized discovery feeds populate this catalogue automatically.</div>}</div>
    <details className="af-filter-details"><summary><Settings2 size={14}/> Filter catalogue</summary><div className="af-selectors">
     <label>Sport<select value={s.sport} onChange={e=>change('sport',e.target.value)}><option value="">All sports</option>{(sports.data||[]).map(x=><option key={x.id} value={x.name}>{x.name}</option>)}</select></label>
     <label>Country<select value={s.country} disabled={!s.sport} onChange={e=>change('country',e.target.value)}><option value="">All countries</option>{(countries.data||[]).map(x=><option key={x.name} value={x.name}>{x.name}</option>)}</select></label>
     <label>League / Division<select value={s.league} disabled={!s.sport} onChange={e=>change('league',e.target.value)}><option value="">All competitions</option>{(leagues.data||[]).map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
     <label>Season<select value={s.season} disabled={!s.league} onChange={e=>change('season',e.target.value)}><option value="">All seasons</option>{(seasons.data||[]).map(x=><option key={x.id} value={x.id}>{x.label}</option>)}</select></label>
    </div></details></section>

   <section className="af-card af-list"><div className="af-tabs" role="tablist" aria-label="Competition views">{TABS.map(t=><button role="tab" type="button" aria-selected={tab===t} className={tab===t?'active':''} onClick={()=>setTab(t)} key={t}>{{'Fixtures':<CalendarDays size={16}/>,'Competitions':<Layers3 size={16}/>,'Countries':<Globe2 size={16}/>,'Leagues & Divisions':<Trophy size={16}/>,'Research Coverage':<ShieldCheck size={16}/>}[t]}{t}</button>)}</div>
    {tab==='Fixtures'&&<div role="tabpanel" aria-label="Fixtures">
     <div className="af-list-head"><div><h3>{title} ({n(fx?.total)})</h3><p>{scopeLabel} • {period} • Automatically updated</p></div><div className="af-list-tools"><span className={'af-pill '+(connected?'good':'warn')}><span className="af-dot"/>{connected?'Live feed':'Reconnecting'}</span><span className="af-updated"><RefreshCw size={13}/>Last update: {o?watTime(o.updated_at)+' WAT':'—'}</span></div></div>
     <div className="af-status-filters" role="group" aria-label="Fixture status">{STATUSES.map(([key,label])=><button type="button" key={key} aria-pressed={status===key} className={status===key?'active':''} onClick={()=>setStatus(key)}>{label}</button>)}</div>
     {!o&&data.loading?<div className="af-empty">Loading fixtures…</div>:!fx?.rows.length?<div className="af-empty"><WifiOff/><strong>No {status==='all'?'':status+' '}fixtures in this scope</strong><span>Discovery keeps running; fixtures appear here as soon as authorized sources publish them.</span></div>:
     <div className="af-table-wrap"><table><thead><tr><th>Date / Time (WAT)</th><th>Fixture</th><th>Competition</th><th>Market Focus</th><th>Odds (range)</th><th>AI Prob.</th><th>Status</th></tr></thead><tbody>{fx.rows.map(r=>{const p=r.pipeline;const ctx=new URLSearchParams({fixture_id:r.id,...(p?{run_id:p.run_id}:{})});return <tr key={r.id}>
      <td className="af-nowrap">{watDate(r.kickoff_at)}</td>
      <td><NavLink className="af-fixture" to={'/sports/fixtures?'+ctx} title="Open the fixture's workflow context"><Team name={r.home}/><span className="af-vs">vs</span><Team name={r.away}/></NavLink></td>
      <td><span className="af-comp">{r.competition.name}</span><small className="af-muted">{[r.competition.country,r.sport].filter(Boolean).join(' · ')}</small></td>
      <td>{r.market_focus?<span className="af-market">{r.market_focus}</span>:<span className="af-muted">—</span>}</td>
      <td className="af-nowrap">{r.odds?<><span>{r.odds.min.toFixed(2)} – {r.odds.max.toFixed(2)}</span><small className={'af-fresh '+(r.odds.fresh?'good':'stale')}>{r.odds.fresh?'Fresh':'Stale'} · {r.odds.bookmakers} bk</small></>:<span className="af-muted">No prices</span>}</td>
      <td>{r.prediction?<div className="af-prob" title={r.prediction.interval?`95% interval ${Math.round(r.prediction.interval.lower*100)}–${Math.round(r.prediction.interval.upper*100)}%`:undefined}><b>{Math.round(r.prediction.probability*100)}%</b><small>{r.prediction.outcome}</small><span className="af-prob-bar"><i style={{width:Math.round(r.prediction.probability*100)+'%'}}/></span></div>:<span className="af-muted">No forecast</span>}</td>

      <td><span className={'af-status '+(p?RUN_TONE[p.status]||'muted':'muted')}>{p?.status==='COMPLETED'||p?.status==='MONITORING'?<CheckCircle2 size={13}/>:p?.status==='BLOCKED'||p?.status==='FAILED'?<ShieldAlert size={13}/>:<Clock3 size={13}/>}{p?words(p.status):'Awaiting run'}</span>{p?.outcome&&<small className="af-outcome">{words(p.outcome)} at {stageName(p.outcome_stage)}</small>}</td></tr>})}</tbody></table></div>}
     {fx&&fx.total>0&&<div className="af-pagination"><span>Showing {n(first)} – {n(lastRow)} of {n(fx.total)} fixtures</span><nav aria-label="Fixture pages"><button type="button" aria-label="Previous page" disabled={fx.page<=1} onClick={()=>setPage(fx.page-1)}><ChevronLeft size={16}/></button>{pageList(fx.page,fx.pages).map((p,i)=>p==='…'?<span key={'gap'+i} className="af-gap">…</span>:<button type="button" key={p} aria-current={p===fx.page?'page':undefined} className={p===fx.page?'active':''} onClick={()=>setPage(p)}>{n(p)}</button>)}<button type="button" aria-label="Next page" disabled={fx.page>=fx.pages} onClick={()=>setPage(fx.page+1)}><ChevronRight size={16}/></button></nav></div>}
    </div>}
    {tab==='Competitions'&&<div role="tabpanel" aria-label="Competitions">{!o?.competitions.length?<div className="af-empty"><Layers3/><strong>No competitions in this scope</strong></div>:<div className="af-table-wrap"><table><thead><tr><th>Competition</th><th>Country</th><th>Sport</th><th>Fixtures ({HOURS}h)</th><th>All fixtures</th><th/></tr></thead><tbody>{o.competitions.map(c=><tr key={c.id}><td><b>{c.name}</b></td><td>{c.country||'—'}</td><td>{c.sport}</td><td>{n(c.fixtures_window)}</td><td>{n(c.fixtures_total)}</td><td><button type="button" className="af-link" onClick={()=>select(c)}>View fixtures</button></td></tr>)}</tbody></table></div>}</div>}
    {tab==='Countries'&&<div role="tabpanel" aria-label="Countries" className="af-grid">{!o?.countries.length?<div className="af-empty"><Globe2/><strong>No countries recorded</strong></div>:o.countries.map(c=><button type="button" key={c.name} className={'af-tile'+(s.country===c.name?' active':'')} onClick={()=>change('country',s.country===c.name?'':c.name)}><Globe2 size={18}/><b>{c.name}</b><small>{n(c.competitions)} competitions · {n(c.fixtures_window)} fixtures ({HOURS}h)</small></button>)}</div>}
    {tab==='Leagues & Divisions'&&<div role="tabpanel" aria-label="Leagues and divisions" className="af-groups">{!o?.competitions.length?<div className="af-empty"><Trophy/><strong>No leagues in this scope</strong></div>:Object.entries(o.competitions.reduce<Record<string,Competition[]>>((acc,c)=>{const key=c.country||'International / unspecified';(acc[key]=acc[key]||[]).push(c);return acc},{})).sort(([a],[b])=>a.localeCompare(b)).map(([country,items])=><div key={country} className="af-group"><h4>{country}</h4><div>{items.map(c=><button type="button" key={c.id} className={'af-chip'+(s.league===c.id?' active':'')} onClick={()=>select(c)}>{c.name}<small>{n(c.fixtures_window)}</small></button>)}</div></div>)}</div>}
    {tab==='Research Coverage'&&<div role="tabpanel" aria-label="Research coverage" className="af-coverage">{o&&<><div className="af-cov-grid">
      <div><small>Fixtures in scope</small><b>{n(o.coverage.fixtures)}</b></div>
      <div><small>Verified dossiers</small><b>{n(o.coverage.verified_dossiers)}</b><span>{o.coverage.fixtures?Math.round(o.coverage.verified_dossiers/o.coverage.fixtures*100):0}% of fixtures</span></div>
      <div><small>Partial dossiers</small><b>{n(o.coverage.partial_dossiers)}</b></div>
      <div><small>Source observations</small><b>{n(o.coverage.observations)}</b></div>
      <div><small>Team statistics</small><b>{n(o.coverage.team_statistics)}</b></div></div>
      <div className="af-cov-stages">{o.pipeline.stages.filter(x=>['acquire','research','analyse','predict'].includes(x.key)).map(x=><div key={x.key}><span>{x.name}</span><span className="af-cov-bar"><i className="done" style={{width:(x.total?x.verified/x.total*100:0)+'%'}}/><i className="outcome" style={{width:(x.total?x.outcomes/x.total*100:0)+'%'}}/></span><b>{n(x.settled)}/{n(x.total)}</b></div>)}</div>
      <p className="af-muted">Coverage counts persisted dossiers and evidence for fixtures within ±{HOURS} hours. A dimension counts only when verified or explicitly marked unavailable.</p></>}</div>}
   </section></div>

   <aside className="af-side">
    <section className="af-card"><div className="af-card-head"><h3><Settings2 size={26}/> Automation Engine</h3><span className={'af-pill '+(online?'good':'warn')}><span className="af-dot"/>{online?'Running':o?words(o.automation.runtime.status):'—'}</span></div>
     <ul className="af-engines">{(o?.automation.engines||[]).map(e=><li key={e.stage}><span className={'af-engine-icon '+e.state.toLowerCase()}>{e.state==='ACTIVE'?<CheckCircle2 size={16}/>:e.state==='BLOCKED'||e.state==='OFFLINE'?<ShieldAlert size={16}/>:<Clock3 size={16}/>}</span><span><b>{e.name}</b><small>{e.detail}</small></span><em className={e.state.toLowerCase()}>{words(e.state)}</em></li>)}
      {o&&<li><span className={'af-engine-icon '+(online?'active':'offline')}><RefreshCw size={16}/></span><span><b>Continuous update (scheduled)</b><small>{o.automation.runtime.finished_at?'Last cycle '+watTime(o.automation.runtime.finished_at)+' WAT':'No cycle reported yet'}</small></span><em className={online?'active':'offline'}>Every {o.automation.interval_seconds}s</em></li>}</ul></section>
    <section className="af-card"><div className="af-card-head"><div><h3><Activity size={19}/> Live Activity</h3><p>Recorded pipeline stage changes</p></div><NavLink className="af-action" to="/sports/orchestrator"><RefreshCw size={14}/>View log</NavLink></div>
     <ol className="af-activity">{o?.activity.length?o.activity.map((a,i)=><li key={i} className={'tone-'+toneOf(a.status)}><time>{watTime(a.at)}</time><span><b>{a.stage_name}: {words(a.status)}</b>{a.fixture&&<small>{a.fixture}</small>}{a.failure_code&&a.status!=='VERIFIED'&&<small className="af-muted">{a.failure_code}</small>}</span></li>):<li className="af-empty-small">No stage activity recorded yet.</li>}</ol></section>
    <details className="af-card af-source-details"><summary><Database size={17}/> Source &amp; Update Health</summary>
     <div className="af-health-rows"><div><span>Authorized sources</span><b>{n(o?.automation.authorized_sources)}</b></div>{Object.entries(o?.automation.acquisition_jobs||{}).map(([k,v])=><div key={k}><span>Acquisition jobs · {words(k)}</span><b>{n(v)}</b></div>)}<div><span>Live update stream</span><b>{connected?'Connected':'Reconnecting'}</b></div><div><span>Last successful cycle</span><b>{o?.automation.runtime.last_success_at?watDate(o.automation.runtime.last_success_at):'None'}</b></div></div>
     <button type="button" className="af-action wide" onClick={refresh}><RefreshCw size={14}/>Refresh view</button></details>
   </aside></div>
  <p className="af-disclaimer">Database-backed records only. Prices, forecasts and statuses appear only when persisted evidence exists; missing data is shown as missing. Paper mode remains enforced.</p>
 </div>;
}
