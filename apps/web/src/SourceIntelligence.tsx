import {createPortal} from 'react-dom';
import React,{useEffect,useMemo,useState} from 'react';
import {Activity,AlertTriangle,Bot,CheckCircle2,Clock3,Database,Globe2,Layers,Loader2,RefreshCcw,Search,Settings2,ShieldCheck,Trophy,Wifi,WifiOff} from 'lucide-react';
import {useResearchScope,useResearchRemote} from './ResearchCatalogue';
import {useLiveUpdates} from './LiveUpdates';
import './DeepMatchResearch.css';
import './SourceIntelligence.css';

const API='/api/v1/sports/';
type Source={id:string;source:string;status:string;permission:string;last_sync?:string|null;next_sync?:string|null;observations?:number;freshness_minutes?:number|null;sync_failures?:number;restriction?:string|null;terms_url?:string|null;independence_group?:string|null};
type Job={id:string;source_id:string;source?:string;section:string;status:string;attempts:number;max_attempts:number;started_at?:string|null;observations:number;error?:string|null};
type Overview={mode:string;autonomous?:boolean;updated_at:string;runtime:{worker_online:boolean;status:string|null;next_run_at:string|null;last_success_at:string|null;cycles?:number;interval_seconds?:number;open_intelligence_enabled?:boolean;open_intelligence_steps?:{step:string;status:string}[];blockers?:string[]};coverage:{sports:number;countries:number;competitions:number;seasons:number;authorized_sources:number;observations:number};schedule:{id:string;source_id:string;failures:number;last_full_at:string|null;next_check_at:string|null;last_change:string|null}[];kpis:{active_sources:number;authorized_sources:number;acquisition_jobs:number;pending_jobs?:number;healthy:number;degraded:number;errors:number;failed_jobs:number;successful_jobs:number;observations:number;last_sync:string|null;next_sync:string|null};health:{total:number;healthy:number;degraded:number;offline:number;prohibited:number;pct_healthy:number};pipeline:{key:string;name:string;status:string}[];notice:string};
type Analytics={sources:number;authorized:number;jobs:number;successful_jobs:number;failed_jobs:number;observations:number;sports:{name:string;count:number;pct:number}[];activity_24h:{hour:string;jobs:number}[];job_status:Record<string,number>};
type Option={id?:string;name?:string;label?:string};

const tabs=['Overview','Source Registry','Sources','Source Health','Acquisition Jobs','Analytics'] as const;
const fmt=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v)):'—';
const clock=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v))+' WAT':'—';
const n=(v?:number|null)=>v==null?'—':v.toLocaleString('en-NG');
const ago=(v?:string|null)=>{if(!v)return '—';const mins=Math.round((Date.now()-new Date(v).getTime())/60000);if(mins<1)return 'just now';if(mins<60)return mins+' min ago';const hrs=Math.round(mins/60);return hrs<48?hrs+' h ago':fmt(v)};
const statusClass=(s:string)=>s==='ACTIVE'||s==='COMPLETED'||s==='HEALTHY'||s==='SUCCEEDED'?'good':s==='PROHIBITED'||s==='FAILED'||s==='DEGRADED'?'bad':s==='DISABLED'||s==='PENDING'?'warn':'muted';
const words=(s?:string|null)=>s?s.replaceAll('_',' ').toLowerCase():'—';

export default function SourceIntelligence(){
 const {selection:s,change,revision}=useResearchScope();
 const {connected}=useLiveUpdates();
 const [tab,setTab]=useState<(typeof tabs)[number]>('Overview');
 const [search,setSearch]=useState('');
 const [inspect,setInspect]=useState('');
 const ov=useResearchRemote<Overview>(API+'sources/overview',revision);
 const registry=useResearchRemote<Source[]>(API+'sources/registry',revision);
 const analytics=useResearchRemote<Analytics>(API+'sources/analytics',revision);
 const jobs=useResearchRemote<Job[]>(tab==='Acquisition Jobs'?API+'acquisition/jobs':null,revision);
 const sports=useResearchRemote<Option[]>(inspect==='filters'?API+'research/catalog/sports':null,revision);
 const countries=useResearchRemote<Option[]>(inspect==='filters'&&s.sport?API+'research/catalog/countries?'+new URLSearchParams({sport:s.sport}):null,revision);
 const leagues=useResearchRemote<Option[]>(inspect==='filters'&&s.sport?API+'research/catalog/leagues?'+new URLSearchParams({sport:s.sport,...(s.country?{country:s.country}:{})}):null,revision);
 const seasons=useResearchRemote<Option[]>(inspect==='filters'&&s.league?API+'research/catalog/seasons?'+new URLSearchParams({league_id:s.league}):null,revision);

 const o=ov.data;const online=!!o?.runtime.worker_online;
 const sources=registry.data||[];
 const visible=useMemo(()=>{
  const q=search.toLowerCase();
  let rows=sources;
  if(tab==='Sources')rows=rows.filter(r=>r.permission==='AUTHORIZED'||r.status==='ACTIVE');
  if(tab==='Source Health')rows=rows.filter(r=>r.status!=='PROHIBITED');
  return q?rows.filter(row=>JSON.stringify(row).toLowerCase().includes(q)):rows;
 },[sources,search,tab]);

 const jobRows=useMemo(()=>{
  const list=jobs.data||[];
  const q=search.toLowerCase();
  return q?list.filter(j=>JSON.stringify(j).toLowerCase().includes(q)):list;
 },[jobs.data,search]);

 useEffect(()=>{setSearch('')},[tab]);

 const errors=[ov,registry,analytics,jobs].map(x=>x.error).filter(Boolean);
 const pct=o?.health.pct_healthy??0;
 const coverage=o?.coverage;
 const kpis=[
  {t:'Active Sources',v:n(o?.kpis.active_sources),s:o?`${n(o.kpis.authorized_sources)} authorized · auto`:'Awaiting controller',icon:Layers,tone:'blue'},
  {t:'Acquisition Jobs',v:n(o?.kpis.acquisition_jobs),s:o?`${n(o.kpis.pending_jobs)} queued · ${n(o.kpis.successful_jobs)} done`:'Awaiting controller',icon:Database,tone:'purple'},
  {t:'Healthy',v:n(o?.kpis.healthy),s:o?`${pct}% of active`:'Awaiting controller',icon:ShieldCheck,tone:'green'},
  {t:'Errors',v:n(o?.kpis.errors),s:o?`${n(o.kpis.failed_jobs)} failed jobs`:'Awaiting controller',icon:AlertTriangle,tone:'orange'},
  {t:'Last Sync',v:ago(o?.kpis.last_sync),s:o?.kpis.last_sync?fmt(o.kpis.last_sync):'Controller will sync when due',icon:Clock3,tone:'blue'},
 ];
 const activity=analytics.data?.activity_24h||[];
 const maxJobs=Math.max(1,...activity.map(a=>a.jobs));
 const activityPath=(()=>{
  if(!activity.length)return '';
  const pts=activity.map((a,i)=>({x:i*(100/(activity.length-1||1)),y:100-(a.jobs/maxJobs)*85}));
  return 'M '+pts.map(p=>`${p.x},${p.y}`).join(' L ');
 })();
 const activityFill=activityPath?activityPath+` L 100,100 L 0,100 Z`:'';
 const coverageTiles=[
  {label:'Sports',value:n(coverage?.sports),icon:Trophy},
  {label:'Countries',value:n(coverage?.countries),icon:Globe2},
  {label:'Competitions',value:n(coverage?.competitions),icon:Layers},
  {label:'Seasons',value:n(coverage?.seasons),icon:Database},
  {label:'Observations',value:n(coverage?.observations),icon:Activity},
 ];

 return <div className="dmr si">
  {document.getElementById('deep-runtime-badge')&&createPortal(<span className={'dmr-runtime-badge '+(online?'online':'')}><Bot size={23}/>Autonomous Mode: {online?'ON':o?'OFF':'Checking'}<i/></span>,document.getElementById('deep-runtime-badge')!)}

  <div className="dmr-header si-header">
   <div className="dmr-intro">
    <div className="dmr-eyebrow">ENGINE OPERATIONS</div>
    <div className="si-title-line"><h2>Source Intelligence</h2><span className={'si-mode '+(online?'on':'')}><Bot size={15}/>{o?online?'Autonomous':'Controller offline':'Connecting'}</span></div>
    <p>Autonomous discovery, authorization, collection and sync of authorized sources — self-running, no manual initiation.</p>
   </div>
   <div className="dmr-kpis si-kpis">{kpis.map(k=><div className={k.tone} key={k.t}><k.icon/><span>{k.t}</span><b>{ov.loading&&!o?'…':k.v}</b><small className="mi-kpi-sub">{k.s}</small></div>)}</div>
  </div>

  <section className="dmr-pipeline si-pipeline">
   <div className="dmr-pipeline-title"><Bot/><div><strong>Autonomous Source Acquisition Pipeline</strong><small>{o?`${n(o.runtime.cycles)} controller cycles · ${n(o.kpis.acquisition_jobs)} jobs recorded · no operator start required`:'Loading autonomous pipeline…'}</small></div></div>
   <div className="dmr-steps">{(o&&o.pipeline.length>0)?o.pipeline.map((step,i,all)=><React.Fragment key={step.key}><div className="dmr-step" title={step.status}><span className={step.status==='DONE'?'dmr-done':'dmr-wait'}>{step.status==='DONE'?<CheckCircle2/>:<Clock3/>}</span><b>{step.name}</b></div>{i<all.length-1&&<span className="si-pipe-sep" aria-hidden="true"/>}</React.Fragment>):['Discover','Authorize','Collect','Validate','Register','Sync'].map(name=><div className="dmr-step" key={name}><span className="dmr-wait"><Loader2/></span><b>{name}</b></div>)}</div>
   <div className="dmr-cycle"><span className={'dmr-mode '+(online?'online':'')}><RefreshCcw size={16}/>{online?'Running':o?words(o.runtime.status):'Connecting'}</span><small>{o?.kpis.next_sync?'Next sync: '+clock(o.kpis.next_sync):'Updates automatically'}</small></div>
  </section>

  {errors.length>0&&<div className="dmr-error" role="alert"><AlertTriangle size={16}/>Backend unavailable: {errors.join('; ')}. No data has been simulated.</div>}
  {(o?.runtime.blockers||[]).length>0&&<div className="dmr-error si-blockers" role="status"><AlertTriangle size={16}/>Autonomy blockers: {(o?.runtime.blockers||[]).join(' · ')}</div>}

  <section className="dmr-card si-coverage" aria-label="Autonomous catalogue coverage">
   <div className="dmr-card-head">
    <div><h3><Layers size={18}/> Competition Intelligence <span className="si-sub">(Auto-Discovery)</span></h3><p>Sports, countries, leagues and seasons maintained from authorized sources without manual selection.</p></div>
    <div className="si-live-tools">
     <span className={'si-pill '+(online?'good':'warn')}><RefreshCcw size={13}/>{online?'Self-updating':'Updates paused'}</span>
     <span className={'si-pill '+(connected?'good':'warn')}>{connected?<Wifi size={13}/>:<WifiOff size={13}/>}{connected?'Live feed':'Reconnecting'}</span>
     <span className="si-updated">Last update: {o?clock(o.updated_at):'—'}</span>
    </div>
   </div>
   <div className="si-coverage-tiles">{coverageTiles.map(t=><div className="si-tile" key={t.label}><t.icon size={18}/><span><b>{t.value}</b><small>{t.label}</small></span></div>)}</div>
   <details className="si-filter-details" open={inspect==='filters'} onToggle={e=>setInspect((e.target as HTMLDetailsElement).open?'filters':'')}>
    <summary><Settings2 size={14}/> Inspect catalogue filters <small>(optional · does not start acquisition)</small></summary>
    <div className="si-filter-grid">
     <label>Sport<select aria-label="Sport" value={s.sport} onChange={e=>change('sport',e.target.value)}><option value="">All sports</option>{(sports.data||[]).map(x=><option key={x.id||x.name} value={x.name}>{x.name}</option>)}</select></label>
     <label>Country<select aria-label="Country" value={s.country} disabled={!s.sport} onChange={e=>change('country',e.target.value)}><option value="">All countries</option>{(countries.data||[]).map(x=><option key={x.name} value={x.name}>{x.name}</option>)}</select></label>
     <label>League / Division<select aria-label="League / Division" value={s.league} disabled={!s.sport} onChange={e=>change('league',e.target.value)}><option value="">All competitions</option>{(leagues.data||[]).map(x=><option key={x.id||x.name} value={x.id||x.name}>{x.label||x.name}</option>)}</select></label>
     <label>Season<select aria-label="Season" value={s.season} disabled={!s.league} onChange={e=>change('season',e.target.value)}><option value="">All seasons</option>{(seasons.data||[]).map(x=><option key={x.id||x.name} value={x.id||x.name}>{x.label||x.name}</option>)}</select></label>
     <label>As of (local time)<input type="datetime-local" value={s.asOf} onChange={e=>change('asOf',e.target.value)}/></label>
    </div>
    <p className="si-filter-note">Filters only narrow what you inspect. The autonomous controller keeps discovering and syncing every authorized source on its own schedule.</p>
   </details>
  </section>

  <div className="dmr-tabs si-tabs" role="tablist" aria-label="Source intelligence views">
   {tabs.map(name=><button type="button" role="tab" aria-selected={tab===name} key={name} className={tab===name?'active':''} onClick={()=>setTab(name)}>{name}</button>)}
  </div>

  <div className="si-grid">
   <section className="dmr-card si-records">
    <div className="dmr-card-head">
     <div><h3><Database size={18}/> {tab==='Acquisition Jobs'?'Acquisition Jobs':tab==='Analytics'?'Analytics Summary':tab==='Source Health'?'Source Health Records':'Operational Records'}</h3>
      <p>Verified source status and acquisition history · updated automatically</p></div>
     <span className={'si-pill '+(connected?'good':'warn')}><span className="si-dot"/>{connected?'Live':'Polling'}</span>
    </div>
    <label className="si-search"><Search size={16}/><input aria-label="Search operational records" placeholder="Search source, status, permission..." value={search} onChange={e=>setSearch(e.target.value)}/><small>{tab==='Acquisition Jobs'?jobRows.length:tab==='Analytics'?'—':visible.length} records</small></label>

    {tab==='Analytics'?<div className="si-analytics-panel">
     <div className="si-stat-row"><span>Authorized sources</span><b>{n(analytics.data?.authorized)}</b></div>
     <div className="si-stat-row"><span>Successful jobs</span><b>{n(analytics.data?.successful_jobs)}</b></div>
     <div className="si-stat-row"><span>Failed jobs</span><b>{n(analytics.data?.failed_jobs)}</b></div>
     <div className="si-stat-row"><span>Verified observations</span><b>{n(analytics.data?.observations)}</b></div>
     <div className="si-job-status">{Object.entries(analytics.data?.job_status||{}).map(([k,v])=><span key={k}>{k.replaceAll('_',' ')} <b>{v}</b></span>)}</div>
    </div>:tab==='Acquisition Jobs'?<div className="si-table">{jobRows.length?<table><thead><tr><th>Job</th><th>Source</th><th>Section</th><th>Started</th><th>Status</th><th>Attempts</th><th>Error</th></tr></thead>
     <tbody>{jobRows.map(j=><tr key={j.id}><td>#{j.id.slice(0,8)}</td><td><b>{j.source||j.source_id.slice(0,8)}</b></td><td>{j.section}</td><td>{fmt(j.started_at)}</td><td><em className={statusClass(j.status)}>{j.status}</em></td><td>{j.attempts}/{j.max_attempts}</td><td>{j.error||'—'}</td></tr>)}</tbody></table>
     :<div className="dmr-data-empty">{jobs.loading?'Loading acquisition jobs…':'No acquisition jobs yet — the controller enqueues them when sources are due.'}</div>}</div>
    :<div className="si-table">{visible.length?<table><thead><tr><th>Source</th><th>Status</th><th>Permission</th><th>Last Sync</th><th>Next Sync</th><th>Observations</th></tr></thead>
     <tbody>{visible.map(row=><tr key={row.id||row.source}><td><b>{row.source}</b>{row.independence_group&&<small>{row.independence_group}</small>}{row.restriction&&<small>{row.restriction}</small>}</td>
      <td><em className={statusClass(row.status)}>{row.status}</em></td><td>{row.permission}</td><td>{fmt(row.last_sync)}</td><td>{fmt(row.next_sync)}</td><td>{n(row.observations)}</td></tr>)}</tbody></table>
     :<div className="dmr-data-empty">{registry.loading?'Loading sources…':'No verified source records yet. Authorized open-data adapters register automatically.'}</div>}</div>}
   </section>

   <aside className="si-side">
    <section className="dmr-card si-health">
     <div className="dmr-card-head"><h3><Activity size={18}/> Source Health (Live)</h3></div>
     <div className="si-health-body">
      <div className="si-ring" style={{background:`conic-gradient(#16a34a ${pct}%,#e7edf6 0)`}}><div>{pct}%<small>Healthy</small></div></div>
      <div className="si-health-list">
       <span>Healthy <b>{n(o?.health.healthy)}</b></span>
       <span>Degraded <b>{n(o?.health.degraded)}</b></span>
       <span>Offline / Failed <b>{n(o?.health.offline)}</b></span>
       <span>Prohibited <b>{n(o?.health.prohibited)}</b></span>
      </div>
     </div>
    </section>

    <section className="dmr-card si-activity">
     <div className="dmr-card-head"><h3><Clock3 size={18}/> Acquisition Activity (Last 24 Hours)</h3></div>
     {activity.some(a=>a.jobs>0)?<svg className="si-chart" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Acquisition jobs over the last 24 hours">
      <defs><linearGradient id="si-act-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#1969ef" stopOpacity=".35"/><stop offset="100%" stopColor="#1969ef" stopOpacity=".02"/></linearGradient></defs>
      <path d={activityFill} fill="url(#si-act-fill)"/><path d={activityPath} fill="none" stroke="#1969ef" strokeWidth="1.8" vectorEffect="non-scaling-stroke"/>
     </svg>:<div className="dmr-data-empty">No acquisition runs in the last 24 hours</div>}
     <div className="si-bigstat">{n(analytics.data?.successful_jobs)} <small>successful jobs</small></div>
     <div className="si-bigstat">{n(analytics.data?.failed_jobs)} <small>failed jobs</small></div>
    </section>

    <section className="dmr-card si-schedule">
     <div className="dmr-card-head"><h3><RefreshCcw size={18}/> Sync Schedule</h3></div>
     {(o?.schedule||[]).length?(o!.schedule.map(row=><div className="si-sched-row" key={row.id}><span><b>{row.id.replace(/^open-intel:schedule:/,'')}</b><small>{row.last_change||'Scheduled'}</small></span><em>{row.next_check_at?clock(row.next_check_at):'—'}</em></div>))
      :<div className="dmr-data-empty">Sync schedule appears after the first autonomous cycle.</div>}
    </section>

    <section className="dmr-card si-distribution">
     <div className="dmr-card-head"><h3>Source Distribution by Sport</h3></div>
     {(analytics.data?.sports||[]).length?(analytics.data!.sports.map(row=><div className="si-dist" key={row.name}><span>{row.name}</span><div><i style={{width:`${row.pct}%`}}/></div><b>{row.pct}%</b></div>))
      :<div className="dmr-data-empty">No sport-linked observations yet</div>}
    </section>
  </aside>
  </div>

  <div className="si-foot"><ShieldCheck size={20}/><div><b>Evidence-Driven Autonomous Operations</b><p>{o?.notice||'Source acquisition is driven by the background controller. Authorization and operational status come from backend records only — no simulated provider connections.'}</p></div></div>
 </div>;
}
