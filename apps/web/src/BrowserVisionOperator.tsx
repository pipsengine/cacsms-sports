import {createPortal} from 'react-dom';
import React,{useMemo,useState} from 'react';
import {Activity,AlertTriangle,Bot,Camera,CheckCircle2,Clock3,Database,Eye,FileText,Layers,Loader2,Monitor,RefreshCcw,Search,Settings2,ShieldCheck,Wifi,WifiOff,XCircle} from 'lucide-react';
import {useResearchScope,useResearchRemote} from './ResearchCatalogue';
import {useLiveUpdates} from './LiveUpdates';
import './DeepMatchResearch.css';
import './BrowserVisionOperator.css';

const API='/api/v1/sports/';
type Session={id:string;fixture_id:string;source_id:string;source?:string;url:string;status:string;vision_status:string;evidence_hash:string|null;error:string|null;created_at:string|null};
type SourceRow={id:string;name:string;status:string;permission:string;observations:number;restriction?:string|null;terms_url?:string|null;last_sync?:string|null;next_sync?:string|null};
type HealthCheck={name:string;status:string;detail:string};
type Overview={mode:string;autonomous?:boolean;updated_at:string;runtime:{worker_online:boolean;status:string|null;next_run_at:string|null;last_success_at:string|null;cycles?:number;interval_seconds?:number;blockers?:string[]};kpis:{sessions:number;captured:number;vision_verified:number;in_progress:number;failed:number;authorized_sources:number;prohibited_sources:number;readiness_pct:number};pipeline:{key:string;name:string;status:string}[];readiness:Record<string,string|boolean>;health:HealthCheck[];boundaries:{name:string;detail:string}[];sources:SourceRow[];recent:Session[];notice:string};
type Option={id?:string;name?:string;label?:string};

const tabs=['Overview','Source Registry','Sessions & Evidence','Vision Readiness','Automation','Audit'] as const;
const fmt=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v)):'—';
const clock=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v))+' WAT':'—';
const n=(v?:number|null)=>v==null?'—':v.toLocaleString('en-NG');
const words=(s?:string|null)=>s?String(s).replaceAll('_',' '):'—';
const tone=(s:string)=>s==='CAPTURED'||s==='VERIFIED'||s==='ACTIVE'||s==='READY'||s==='DONE'||s==='ACTIVE'?'good':s==='FAILED'||s==='PROHIBITED'||s==='NOT_CONFIGURED'||s==='OFFLINE'?'bad':s==='PENDING'||s==='RUNNING'||s==='WAITING'||s==='CONFIGURED'?'warn':'muted';

export default function BrowserVisionOperator(){
 const {selection:s,change,revision}=useResearchScope();
 const {connected}=useLiveUpdates();
 const [tab,setTab]=useState<(typeof tabs)[number]>('Overview');
 const [search,setSearch]=useState('');
 const [inspect,setInspect]=useState('');
 const [selected,setSelected]=useState<Session|null>(null);
 const ov=useResearchRemote<Overview>(API+'browser/overview',revision);
 const readiness=useResearchRemote<Record<string,string|boolean>>(API+'browser/readiness',revision);
 const sports=useResearchRemote<Option[]>(inspect==='filters'?API+'research/catalog/sports':null,revision);
 const countries=useResearchRemote<Option[]>(inspect==='filters'&&s.sport?API+'research/catalog/countries?'+new URLSearchParams({sport:s.sport}):null,revision);
 const leagues=useResearchRemote<Option[]>(inspect==='filters'&&s.sport?API+'research/catalog/leagues?'+new URLSearchParams({sport:s.sport,...(s.country?{country:s.country}:{})}):null,revision);
 const seasons=useResearchRemote<Option[]>(inspect==='filters'&&s.league?API+'research/catalog/seasons?'+new URLSearchParams({league_id:s.league}):null,revision);

 const o=ov.data;const online=!!o?.runtime.worker_online;
 const sessions=o?.recent||[];
 const sources=o?.sources||[];
 const pct=o?.kpis.readiness_pct??0;
 const visibleSessions=useMemo(()=>{
  const q=search.toLowerCase();
  return q?sessions.filter(row=>JSON.stringify(row).toLowerCase().includes(q)):sessions;
 },[sessions,search]);
 const visibleSources=useMemo(()=>{
  const q=search.toLowerCase();
  return q?sources.filter(row=>JSON.stringify(row).toLowerCase().includes(q)):sources;
 },[sources,search]);
 const errors=[ov,readiness].map(x=>x.error).filter(Boolean);
 const kpis=[
  {t:'Browser Sessions',v:n(o?.kpis.sessions),s:'Persisted capture records',icon:Monitor,tone:'blue'},
  {t:'Captured Evidence',v:n(o?.kpis.captured),s:'Screenshots with hash',icon:Camera,tone:'purple'},
  {t:'Vision-Verified',v:n(o?.kpis.vision_verified),s:o?`${pct}% of captured`:'Awaiting controller',icon:ShieldCheck,tone:'green'},
  {t:'In Progress',v:n(o?.kpis.in_progress),s:'Pending / running',icon:Clock3,tone:'orange'},
  {t:'Failed',v:n(o?.kpis.failed),s:'Recorded capture failures',icon:XCircle,tone:'orange'},
 ];

 return <div className="dmr bvo">
  {document.getElementById('deep-runtime-badge')&&createPortal(<span className={'dmr-runtime-badge '+(online?'online':'')}><Bot size={23}/>Controller: {online?'Online':o?'Offline':'Checking'}<i/></span>,document.getElementById('deep-runtime-badge')!)}

  <div className="dmr-header bvo-header">
   <div className="dmr-intro">
    <div className="dmr-eyebrow">ENGINE OPERATIONS</div>
    <div className="bvo-title-line"><h2>Browser &amp; Vision Operator</h2><span className="bvo-mode"><Bot size={15}/>{o?'Manual capture':'Connecting'}</span></div>
    <p>Authorized browser capture is administrator initiated. No autonomous browser collection is currently dispatched.</p>
   </div>
   <div className="dmr-kpis bvo-kpis">{kpis.map(k=><div className={k.tone} key={k.t}><k.icon/><span>{k.t}</span><b>{ov.loading&&!o?'…':k.v}</b><small className="mi-kpi-sub">{k.s}</small></div>)}</div>
  </div>

  <section className="dmr-pipeline bvo-pipeline">
   <div className="dmr-pipeline-title"><Bot/><div><strong>Capture Pipeline</strong><small>{o?`${n(o.runtime.cycles)} controller cycles · ${n(o.kpis.authorized_sources)} authorized sources · administrator-initiated capture only`:'Loading capture pipeline…'}</small></div></div>
   <div className="dmr-steps">{(o&&o.pipeline.length)?o.pipeline.map((step,i,all)=><React.Fragment key={step.key}><div className="dmr-step" title={step.status}><span className={step.status==='DONE'?'dmr-done':'dmr-wait'}>{step.status==='DONE'?<CheckCircle2/>:<Clock3/>}</span><b>{step.name}</b></div>{i<all.length-1&&<span className="bvo-pipe-sep" aria-hidden="true"/>}</React.Fragment>):['Discover','Authorize','Browse','Capture','Analyse','Verify'].map(name=><div className="dmr-step" key={name}><span className="dmr-wait"><Loader2/></span><b>{name}</b></div>)}</div>
   <div className="dmr-cycle"><span className="dmr-mode"><RefreshCcw size={16}/>Browser scheduler not configured</span><small>Controller status is separate from browser capture.</small></div>
  </section>

  {errors.length>0&&<div className="dmr-error" role="alert"><AlertTriangle size={16}/>Backend unavailable: {errors.join('; ')}. No capture states have been simulated.</div>}
  {(o?.runtime.blockers||[]).length>0&&<div className="dmr-error bvo-blockers" role="status"><AlertTriangle size={16}/>Autonomy blockers: {(o?.runtime.blockers||[]).join(' · ')}</div>}

  <section className="dmr-card bvo-coverage" aria-label="Autonomous capture coverage">
   <div className="dmr-card-head">
    <div><h3><Layers size={18}/> Capture Scope <span className="bvo-sub">(Auto-Governed)</span></h3><p>Only explicitly authorized HTTPS origins on the host allowlist are reachable. Prohibited sources stay blocked.</p></div>
    <div className="bvo-live-tools">
     <span className={'bvo-pill '+(online?'good':'warn')}><RefreshCcw size={13}/>{online?'Self-updating':'Updates paused'}</span>
     <span className={'bvo-pill '+(connected?'good':'warn')}>{connected?<Wifi size={13}/>:<WifiOff size={13}/>}{connected?'Live feed':'Reconnecting'}</span>
     <span className="bvo-updated">Last update: {o?clock(o.updated_at):'—'}</span>
    </div>
   </div>
   <div className="bvo-coverage-tiles">
    {[['Authorized',n(o?.kpis.authorized_sources),ShieldCheck],['Prohibited',n(o?.kpis.prohibited_sources),AlertTriangle],['Captured',n(o?.kpis.captured),Camera],['Vision verified',n(o?.kpis.vision_verified),Eye],['In progress',n(o?.kpis.in_progress),Clock3]].map(([label,value,Icon]:any)=><div className="bvo-tile" key={label}><Icon size={18}/><span><b>{value}</b><small>{label}</small></span></div>)}
   </div>
   <details className="bvo-filter-details" open={inspect==='filters'} onToggle={e=>setInspect((e.target as HTMLDetailsElement).open?'filters':'')}>
    <summary><Settings2 size={14}/> Inspect research catalogue <small>(optional · does not start browser capture)</small></summary>
    <div className="bvo-filter-grid">
     <label>Sport<select aria-label="Sport" value={s.sport} onChange={e=>change('sport',e.target.value)}><option value="">All sports</option>{(sports.data||[]).map(x=><option key={x.id||x.name} value={x.name}>{x.name}</option>)}</select></label>
     <label>Country<select aria-label="Country" value={s.country} disabled={!s.sport} onChange={e=>change('country',e.target.value)}><option value="">All countries</option>{(countries.data||[]).map(x=><option key={x.name} value={x.name}>{x.name}</option>)}</select></label>
     <label>League / Division<select aria-label="League / Division" value={s.league} disabled={!s.sport} onChange={e=>change('league',e.target.value)}><option value="">All competitions</option>{(leagues.data||[]).map(x=><option key={x.id||x.name} value={x.id||x.name}>{x.label||x.name}</option>)}</select></label>
     <label>Season<select aria-label="Season" value={s.season} disabled={!s.league} onChange={e=>change('season',e.target.value)}><option value="">All seasons</option>{(seasons.data||[]).map(x=><option key={x.id||x.name} value={x.id||x.name}>{x.label||x.name}</option>)}</select></label>
     <label>As of (local time)<input type="datetime-local" value={s.asOf} onChange={e=>change('asOf',e.target.value)}/></label>
    </div>
    <p className="bvo-filter-note">Catalogue filters only narrow inspection context. Administrator-initiated browser capture is gated by server-side authorization and the host allowlist — not by this form.</p>
   </details>
  </section>

  <div className="dmr-tabs bvo-tabs" role="tablist" aria-label="Browser and vision views">
   {tabs.map(name=><button type="button" role="tab" aria-selected={tab===name} key={name} className={tab===name?'active':''} onClick={()=>setTab(name)}>{name}</button>)}
  </div>

  <div className="bvo-grid">
   <div className="bvo-main">
    {tab==='Overview'&&<>
     <section className="dmr-card">
      <div className="dmr-card-head"><h3><Database size={18}/> Operational Overview</h3></div>
      <div className="bvo-health-body">
       <div className="bvo-ring" style={{background:`conic-gradient(#16a34a ${pct}%,#e7edf6 0)`}}><div>{pct}%<small>Vision verified</small></div></div>
       <div className="bvo-facts">
        <div>Authorized sources <b>{n(o?.kpis.authorized_sources)}</b></div>
        <div>Active / stored sessions <b>{n(o?.kpis.sessions)}</b></div>
        <div>Evidence captured <b>{n(o?.kpis.captured)}</b></div>
        <div>Vision-verified <b>{n(o?.kpis.vision_verified)}</b></div>
        <div>Failed / blocked <b>{n(o?.kpis.failed)}</b></div>
       </div>
      </div>
     </section>
     <section className="dmr-card">
      <div className="dmr-card-head"><div><h3><Monitor size={18}/> Browser Sessions</h3><p>Latest persisted capture records</p></div><span className={'bvo-pill '+(connected?'good':'warn')}><span className="bvo-dot"/>{connected?'Live':'Polling'}</span></div>
      <label className="bvo-search"><Search size={16}/><input aria-label="Search sessions" placeholder="Search source, status, URL..." value={search} onChange={e=>setSearch(e.target.value)}/><small>{visibleSessions.length} records</small></label>
      <div className="bvo-table">{visibleSessions.length?<table><thead><tr><th>#</th><th>Source</th><th>Status</th><th>Vision</th><th>Started</th><th>Evidence</th></tr></thead>
       <tbody>{visibleSessions.map((row,i)=><tr key={row.id}><td>{i+1}</td><td><b>{row.source||row.source_id.slice(0,8)}</b><small>{row.url}</small></td><td><em className={tone(row.status)}>{row.status}</em></td><td><em className={tone(row.vision_status)}>{row.vision_status}</em></td><td>{fmt(row.created_at)}</td><td>{row.evidence_hash?<button type="button" className="bvo-link" onClick={()=>setSelected(row)}>Inspect</button>:'—'}</td></tr>)}</tbody></table>
       :<div className="dmr-data-empty">{ov.loading?'Loading sessions…':'No browser captures yet. Authorized allowlisted hosts are captured by the autonomous controller when configured.'}</div>}</div>
     </section>
    </>}

    {tab==='Source Registry'&&<section className="dmr-card">
     <div className="dmr-card-head"><h3><ShieldCheck size={18}/> Source Registry &amp; Permission</h3></div>
     <label className="bvo-search"><Search size={16}/><input aria-label="Search sources" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search source, permission, status..."/><small>{visibleSources.length} records</small></label>
     <div className="bvo-table">{visibleSources.length?<table><thead><tr><th>Source</th><th>Status</th><th>Permission</th><th>Observations</th><th>Restriction</th></tr></thead>
      <tbody>{visibleSources.map(row=><tr key={row.id}><td><b>{row.name}</b></td><td><em className={tone(row.status)}>{row.status}</em></td><td>{row.permission}</td><td>{n(row.observations)}</td><td>{row.restriction||'—'}{row.terms_url&&<> · <a href={row.terms_url} target="_blank" rel="noreferrer">terms</a></>}</td></tr>)}</tbody></table>
      :<div className="dmr-data-empty">No sources registered.</div>}</div>
    </section>}

    {tab==='Sessions & Evidence'&&<section className="dmr-card">
     <div className="dmr-card-head"><h3><Camera size={18}/> Capture Sessions &amp; Evidence</h3></div>
     <label className="bvo-search"><Search size={16}/><input aria-label="Search evidence" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search captures..."/><small>{visibleSessions.length} records</small></label>
     <div className="bvo-table">{visibleSessions.length?<table><thead><tr><th>Started</th><th>Source URL</th><th>Status</th><th>SHA-256</th><th>Action</th></tr></thead>
      <tbody>{visibleSessions.map(row=><tr key={row.id}><td>{fmt(row.created_at)}</td><td>{row.url}</td><td><em className={tone(row.status)}>{row.status}</em></td><td title={row.evidence_hash||''}>{row.evidence_hash?.slice(0,18)||'—'}</td><td><button type="button" className="bvo-link" onClick={()=>setSelected(row)}>Inspect</button></td></tr>)}</tbody></table>
      :<div className="dmr-data-empty">No capture sessions yet.</div>}</div>
    </section>}

    {tab==='Vision Readiness'&&<section className="dmr-card">
     <div className="dmr-card-head"><h3><Eye size={18}/> Vision Inference Readiness</h3></div>
     <div className="bvo-facts">{Object.entries(readiness.data||o?.readiness||{}).map(([k,v])=><div key={k}>{words(k)} <b>{String(v)}</b></div>)}</div>
     <p className="bvo-filter-note">Screenshot capture is not computer-vision verification. An approved inference provider and independent review are required before marking evidence verified.</p>
    </section>}

    {tab==='Automation'&&<section className="dmr-card">
     <div className="dmr-card-head"><h3><RefreshCcw size={18}/> Automation &amp; Scheduling</h3></div>
     <div className="bvo-facts">
      <div>Auto capture <b>{online?'Enabled (controller)':'Paused / offline'}</b></div>
      <div>Controller interval <b>{o?.runtime.interval_seconds?o.runtime.interval_seconds+'s':'—'}</b></div>
      <div>Authorized sources <b>{n(o?.kpis.authorized_sources)}</b></div>
      <div>Next run <b>{clock(o?.runtime.next_run_at)}</b></div>
      <div>Retry / recovery <b>Controller-managed</b></div>
     </div>
     <p className="bvo-filter-note">Scheduling is owned by the autonomous controller. This page does not enable prohibited hosts or start unpaid browser jobs from the browser UI.</p>
    </section>}

    {tab==='Audit'&&<section className="dmr-card">
     <div className="dmr-card-head"><h3><FileText size={18}/> Operational Audit</h3></div>
     <p className="bvo-filter-note">Capture outcomes and source policy changes are persisted as audit events. Use Administration → Audit Trail for the full ledger.</p>
     <div className="bvo-table">{sessions.length?<table><thead><tr><th>Time</th><th>Source</th><th>Outcome</th><th>Detail</th></tr></thead>
      <tbody>{sessions.map(row=><tr key={row.id}><td>{fmt(row.created_at)}</td><td>{row.source||row.source_id.slice(0,8)}</td><td><em className={tone(row.status)}>{row.status}</em></td><td>{row.error||row.evidence_hash?.slice(0,18)||row.vision_status}</td></tr>)}</tbody></table>
      :<div className="dmr-data-empty">No capture audit rows yet.</div>}</div>
    </section>}

    <section className="dmr-card">
     <div className="dmr-card-head"><h3><Camera size={18}/> Recent Capture History</h3></div>
     <div className="bvo-table">{sessions.length?<table><thead><tr><th>Time</th><th>Source</th><th>Outcome</th><th>Evidence</th></tr></thead>
      <tbody>{sessions.slice(0,8).map(row=><tr key={row.id}><td>{fmt(row.created_at)}</td><td>{row.source||row.url}</td><td><em className={tone(row.status)}>{row.status}</em></td><td>{row.evidence_hash?<button type="button" className="bvo-link" onClick={()=>setSelected(row)}>View</button>:'—'}</td></tr>)}</tbody></table>
      :<div className="dmr-data-empty">No recent captures.</div>}</div>
    </section>
   </div>

   <aside className="bvo-side">
    <section className="dmr-card">
     <div className="dmr-card-head"><h3><Eye size={18}/> Vision Inference Readiness</h3></div>
     <div className="bvo-facts">
      <div>Status <b>{words(String(o?.readiness.inference_status||'—'))}</b></div>
      <div>Verification policy <b>{words(String(o?.readiness.verification_policy||'—'))}</b></div>
      <div>Prediction pipeline <b>{words(String(o?.readiness.prediction_pipeline||'—'))}</b></div>
     </div>
    </section>
    <section className="dmr-card">
     <div className="dmr-card-head"><h3><ShieldCheck size={18}/> Acquisition Boundaries</h3></div>
     <div className="bvo-boundaries">{(o?.boundaries||[]).map(b=><div key={b.name}><b>{b.name}</b><span>{b.detail}</span></div>)}</div>
    </section>
    <section className="dmr-card">
     <div className="dmr-card-head"><h3><Activity size={18}/> System Health</h3></div>
     <div className="bvo-health-list">{(o?.health||[]).map(h=><div key={h.name}><span className={tone(h.status)}>{h.status==='READY'||h.status==='ACTIVE'||h.status==='CONFIGURED'?<CheckCircle2 size={16}/>:h.status==='NOT_CONFIGURED'||h.status==='OFFLINE'?<XCircle size={16}/>:<Clock3 size={16}/>}</span><span><b>{h.name}</b><small>{h.detail}</small></span><em className={tone(h.status)}>{words(h.status)}</em></div>)}</div>
    </section>
    <section className="dmr-card bvo-preview">
     <div className="dmr-card-head"><h3><Monitor size={18}/> Live Capture Preview</h3></div>
     {selected?<div className="bvo-preview-body">
      <div className="bvo-preview-meta"><div>Source <b>{selected.source||selected.source_id.slice(0,8)}</b></div><div>Captured <b>{fmt(selected.created_at)}</b></div><div>Hash <b title={selected.evidence_hash||''}>{selected.evidence_hash?.slice(0,24)||'—'}</b></div><div>Vision <em className={tone(selected.vision_status)}>{selected.vision_status}</em></div></div>
      <p className="bvo-filter-note">Screenshot bytes are stored on the evidence root and are not embedded in this dashboard. Status and hashes come from backend records only.</p>
      <button type="button" className="bvo-ghost" onClick={()=>setSelected(null)}>Clear selection</button>
     </div>:<div className="dmr-data-empty">Select a capture with evidence to inspect hash and vision status. No simulated page previews are shown.</div>}
    </section>
   </aside>
  </div>

  <div className="bvo-foot"><ShieldCheck size={20}/><div><b>Evidence-Driven Autonomous Operations</b><p>{o?.notice||'Browser capture is gated by authorization and allowlisting. Screenshots are not vision-verified research. PAPER mode prevents live wagering.'}</p></div></div>
 </div>;
}
