import {createPortal} from 'react-dom';
import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Activity,AlertTriangle,ArrowRight,BarChart3,Bot,CalendarDays,CheckCircle2,ChevronLeft,ChevronRight,Clock3,Database,Globe2,History,Layers3,LayoutGrid,Loader2,RefreshCcw,Search,ShieldCheck,Target,XCircle} from 'lucide-react';
import {useResearchScope,useResearchRemote} from './ResearchCatalogue';
import './DeepMatchResearch.css';
import './MarketIntelligence.css';
import OddsIntelligencePanel from './OddsIntelligencePanel';

const API='/api/v1/sports/market-intelligence/';
type Step={key:string;name:string;status:string;detail:string};
type Overview={runtime:{worker_online:boolean;next_run_at:string|null;status:string};price_observations:number;fixtures_priced:number;markets_represented:number;registered_definitions:number;
 model_coverage:number|null;observed_outcomes:number;model_covered_outcomes:number;fresh_prices:number;qualified:number;pipeline:Step[];notice:string;
 benchmark:{status:string;matches?:number;model_brier?:number;market_brier?:number;average_margin?:number;verdict?:string;basis?:string;computed_at?:string}};
type Category={key:string;name:string;registered:number;observed:number;available:number};
type MarketRow={id:string;name:string;sport:string;category:string;kind:string;status:string;observations:number;fixtures:number;lines:string[];latest_observed_at:string|null;model_supported:boolean;
 outcomes:{key:string;label:string}[];sample:{fixture:string;kickoff_at:string;observed_at:string;best:{market_key:string;outcome:string;decimal_odds:number}[]}|null};
type Page={total:number;limit:number;offset:number;markets:MarketRow[]};
type Source={source:string;status:string;permission:string;last_sync?:string|null;next_sync?:string|null;observations?:number;freshness_minutes?:number|null;verified_result_evidence?:number;
 sync_failures?:number;restriction?:string|null;terms_url?:string|null;independence_group?:string|null};
type Coverage={sport:string;country:string;competition:string;seasons:number;fixtures:number;fixtures_priced:number;price_observations:number;verified_results:number;latest_price_at:string|null;research_ready:boolean};
type Sync={at:string;actor:string;action:string;detail:Record<string,unknown>};
type Catalogue={sports:{key:string;name:string;definitions:number;discovery_only?:boolean}[];definitions:{id:string;sport:string;sport_key:string;category:string;name:string;kind:string;origin:string;outcomes:{label:string}[]}[]};

const fmt=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v))+' WAT':'—';
const clock=(v?:string|null)=>v?new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Africa/Lagos'}).format(new Date(v))+' WAT':'—';
const n=(v?:number|null)=>v==null?'—':v.toLocaleString('en-NG');
const STATUS:Record<string,string>={AVAILABLE:'good',OBSERVED:'info',DISCOVERED:'warn',REGISTERED:'muted',ACTIVE:'good',PROHIBITED:'bad',DISABLED:'muted',NO_PERMITTED_FEED:'bad'};
const TITLE:Record<string,string>={AVAILABLE:'Upcoming fixture has source-backed prices',OBSERVED:'Historical closing prices observed (archive)',REGISTERED:'Registered definition, never observed',DISCOVERED:'Observed in a source but not in the registry'};
const LABEL:Record<string,string>={AVAILABLE:'Available',OBSERVED:'Observed',DISCOVERED:'Discovered',REGISTERED:'Registered',ACTIVE:'Healthy',PROHIBITED:'Prohibited',DISABLED:'Disabled',NO_PERMITTED_FEED:'No permitted feed'};
const tabs=[{name:'Odds & Markets',icon:BarChart3},{name:'Sources',icon:Database},{name:'Sports Coverage',icon:Globe2},{name:'Market Catalogue',icon:LayoutGrid},{name:'Sync History',icon:History},{name:'Source Health',icon:Activity}];
function Chip({value}:{value:string}){return <span title={TITLE[value]} className={'mi-chip '+(STATUS[value]||'muted')}>{LABEL[value]||value.replaceAll('_',' ').toLowerCase()}</span>}
function Empty({children}:{children:React.ReactNode}){return <div className="dmr-data-empty">{children}</div>}

export default function MarketIntelligence(){
 const {revision,refresh}=useResearchScope();
 const[tab,setTab]=useState('Odds & Markets'),[category,setCategory]=useState(''),[search,setSearch]=useState(''),[query,setQuery]=useState(''),[page,setPage]=useState(0),[sport,setSport]=useState('football');
 const size=10;
 const ov=useResearchRemote<Overview>(API+'overview',revision);
 const cats=useResearchRemote<Category[]>(API+'categories',revision);
 const list=useResearchRemote<Page>(API+'markets?'+new URLSearchParams({limit:String(size),offset:String(page*size),...category?{category}:{},...query?{search:query}:{}}),revision);
 const sources=useResearchRemote<Source[]>(API+'sources',revision);
 const coverage=useResearchRemote<Coverage[]>(tab==='Sports Coverage'?API+'sports-coverage':null,revision);
 const history=useResearchRemote<Sync[]>(tab==='Sync History'?API+'sync-history':null,revision);
 const catalogue=useResearchRemote<Catalogue>(tab==='Market Catalogue'?'/api/v1/sports/markets/catalogue':null,revision);
 const refreshRef=useRef(refresh);refreshRef.current=refresh;
 useEffect(()=>{const t=setInterval(()=>refreshRef.current(),60000);return()=>clearInterval(t)},[]);
 useEffect(()=>{const t=setTimeout(()=>{setQuery(search);setPage(0)},300);return()=>clearTimeout(t)},[search]);
 const o=ov.data;const online=o?.runtime.worker_online;const total=list.data?.total||0;const pages=Math.max(1,Math.ceil(total/size));
 const allCount=(cats.data||[]).reduce((a,c)=>a+c.registered,0);
 const kpis=[{t:'Price Observations',v:n(o?.price_observations),s:'stored, evidence-backed prices',icon:Database,tone:'purple'},{t:'Fixtures Priced',v:n(o?.fixtures_priced),s:'fixtures with any price',icon:CalendarDays,tone:'blue'},
  {t:'Markets Represented',v:n(o?.markets_represented),s:`of ${n(o?.registered_definitions)} registered`,icon:Target,tone:'orange'},{t:'Model Coverage',v:o?.model_coverage==null?'—':o.model_coverage+'%',s:`${n(o?.model_covered_outcomes)} of ${n(o?.observed_outcomes)} observed outcomes`,icon:ShieldCheck,tone:'green'}];
 const pageNumbers=useMemo(()=>{const set=new Set([0,1,2,page-1,page,page+1,pages-1].filter(x=>x>=0&&x<pages));return [...set].sort((a,b)=>a-b)},[page,pages]);
 const catalogueRows=(catalogue.data?.definitions||[]).filter(d=>d.sport_key===sport);
 const healthSources=(sources.data||[]).filter(x=>x.status!=='NO_PERMITTED_FEED');
 const bench=o?.benchmark;
 return <div className="dmr mi">
  <OddsIntelligencePanel revision={revision}/>
  {document.getElementById('deep-runtime-badge')&&createPortal(<span className={'dmr-runtime-badge '+(online?'online':'')}><Bot size={23}/>Autonomous Mode: {online?'ON':o?'OFF':'Checking'}<i/></span>,document.getElementById('deep-runtime-badge')!)}
  <div className="dmr-header"><div className="dmr-intro"><div className="dmr-eyebrow">MARKET INTELLIGENCE</div><h2>Market Intelligence</h2><p>Verified market prices, bookmaker mapping and price freshness across all supported sports.</p></div>
   <div className="dmr-kpis">{kpis.map(k=><div className={k.tone} key={k.t}><k.icon/><span>{k.t}</span><b>{k.v}</b><small className="mi-kpi-sub">{k.s}</small></div>)}</div></div>
  <section className="dmr-pipeline mi-pipeline"><div className="dmr-pipeline-title"><Bot/><div><strong>Autonomous Market Pipeline</strong><small>Discover → Collect → Map → Validate → Analyse → Qualify</small></div></div>
   <div className="dmr-steps">{(o?.pipeline||[]).map((s,i,all)=><React.Fragment key={s.key}><div className="dmr-step" title={s.detail}><span className={s.status==='DONE'?'dmr-done':'dmr-wait'}>{s.status==='DONE'?<CheckCircle2/>:s.status==='PARTIAL'?<Loader2/>:<Clock3/>}</span><b>{s.name}</b></div>{i<all.length-1&&<ArrowRight className="aip-arrow mi-arrow" aria-hidden="true"/>}</React.Fragment>)}</div>
   <div className="dmr-cycle"><span className={'dmr-mode '+(online?'online':'')}><RefreshCcw size={16}/>{online?'Running':o?'Worker offline':'Connecting'}</span><small>{o?.runtime.next_run_at?'Next run: '+clock(o.runtime.next_run_at):'Updates automatically'}</small></div></section>
  {[ov,cats,list,sources].some(x=>x.error)&&<div className="dmr-error" role="alert"><AlertTriangle size={16}/>Data unavailable: {[ov,cats,list,sources].map(x=>x.error).filter(Boolean).join('; ')}</div>}
  <div className="dmr-tabs aip-tabs mi-tabs" role="tablist" aria-label="Market intelligence views">{tabs.map(t=><button type="button" role="tab" aria-selected={tab===t.name} key={t.name} onClick={()=>setTab(t.name)} className={tab===t.name?'active':''}><t.icon size={18}/>{t.name}</button>)}</div>
  {tab==='Odds & Markets'?<div className="mi-grid">
   <nav className="dmr-card mi-cats" aria-label="Market categories"><div className="dmr-card-head"><h3><Layers3/>Market Categories</h3><span className="mi-pill">{n(allCount)}</span></div>
    <button type="button" className={category===''?'active':''} onClick={()=>{setCategory('');setPage(0)}}><LayoutGrid size={15}/><span>All Markets</span><em>{n(allCount)}</em></button>
    {(cats.data||[]).map(c=><button type="button" key={c.key} className={category===c.key?'active':''} onClick={()=>{setCategory(c.key);setPage(0)}} title={`${c.registered} registered · ${c.observed} observed · ${c.available} available`}><span>{c.name}</span><em>{c.registered}</em>{c.observed>0&&<i>{c.observed}</i>}</button>)}
   </nav>
   <section className="dmr-card mi-markets"><div className="dmr-card-head"><h3><BarChart3/>Discovered Markets ({n(total)})</h3>{o&&<span className={'mi-chip '+(o.fresh_prices?'good':'warn')}>{o.fresh_prices?<CheckCircle2 size={13}/>:<Clock3 size={13}/>}{o.fresh_prices?'Fresh prices':'Archive only (no fresh prices)'}</span>}</div>
    <p className="dmr-caption">All registered and observed markets with latest stored prices, availability and model status. Observed prices are historical closing odds unless marked Available.</p>
    <label className="aip-search"><Search size={16}/><input aria-label="Search markets" placeholder="Search markets (e.g. Over 2.5, BTTS, Asian Handicap)" value={search} onChange={e=>setSearch(e.target.value)}/></label>
    {list.data?.markets.length?<div className="mi-table"><table><thead><tr><th>#</th><th>Market</th><th className="mi-opt">Category</th><th>Selections / Line</th><th>Odds (best, latest fixture)</th><th>Model</th><th>Status</th></tr></thead>
     <tbody>{list.data.markets.map((x,i)=><tr key={x.id} className={x.status==='REGISTERED'?'mi-registered':''}><td>{page*size+i+1}</td><td><b>{x.name}</b><small>{x.sport}{x.observations?` · ${n(x.observations)} prices · ${n(x.fixtures)} fixtures`:''}</small></td>
      <td className="mi-opt"><span className="mi-cat">{(cats.data||[]).find(c=>c.key===x.category)?.name.split(' /')[0]||x.category}</span></td>
      <td>{x.outcomes.slice(0,3).map(z=>z.label).join(' | ')}{x.outcomes.length>3?' …':''}{x.lines.length?<small>lines {x.lines.slice(0,4).join(', ')}{x.lines.length>4?' …':''}</small>:null}</td>
      <td title={x.sample?`${x.sample.fixture} · ${fmt(x.sample.observed_at)}`:'No stored price'}>{x.sample?<>{x.sample.best.slice(0,3).map(q=>q.decimal_odds.toFixed(2)).join(' | ')}<small>{x.sample.fixture}</small></>:<span className="muted">—</span>}</td>
      <td>{x.model_supported?<CheckCircle2 className="good" size={17} aria-label="Approved model capability"/>:<span className="muted">—</span>}</td><td><Chip value={x.status}/></td></tr>)}</tbody></table></div>
     :<Empty>{list.loading?'Loading markets…':'No markets match this filter.'}</Empty>}
    <div className="mi-pager"><span>Showing {total?page*size+1:0}–{Math.min(total,(page+1)*size)} of {n(total)} markets</span><div>
     <button type="button" aria-label="Previous page" disabled={page===0} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={16}/></button>
     {pageNumbers.map((p,i)=><React.Fragment key={p}>{i>0&&p-pageNumbers[i-1]>1&&<span>…</span>}<button type="button" className={p===page?'active':''} onClick={()=>setPage(p)}>{p+1}</button></React.Fragment>)}
     <button type="button" aria-label="Next page" disabled={page>=pages-1} onClick={()=>setPage(p=>p+1)}><ChevronRight size={16}/></button></div></div>
   </section>
   <aside className="mi-side"><section className="dmr-card"><div className="dmr-card-head"><h3><BarChart3/>Market Coverage &amp; Health</h3></div>
    {[['Registered markets',o?.registered_definitions,Layers3],['Markets represented',o?.markets_represented,Target],['Fresh prices (≤15 min)',o?.fresh_prices,Clock3],['Model-covered outcomes',o?.model_covered_outcomes,ShieldCheck],['Qualified opportunities',o?.qualified,CheckCircle2]].map(([label,value,Icon]:any)=>
     <div className={'mi-row '+(label==='Qualified opportunities'&&value?'hl':'')} key={label}><span><Icon size={16}/>{label}</span><b>{n(value)}</b></div>)}
    <div className="mi-bench" title={bench?.basis}><b><Activity size={15}/>Model vs closing market</b>{bench?.status==='COMPUTED'?<><div><span>Model Brier</span><b>{bench.model_brier}</b></div><div><span>Closing market Brier</span><b>{bench.market_brier}</b></div>
     <p className={bench.verdict==='MODEL_BETTER_THAN_CLOSING_MARKET'?'good':'warn'}>{bench.verdict==='MODEL_BETTER_THAN_CLOSING_MARKET'?'Model beats the closing market':'Closing market is sharper than the model'} on {bench.matches} unseen matches (avg margin {bench.average_margin}%).</p></>
     :<p className="dmr-caption">{bench?.status==='INSUFFICIENT_PRICED_HOLDOUT'?'Waiting for enough priced holdout matches.':bench?.status==='NO_MODEL'?'No validated market model yet.':'Not computed yet.'}</p>}</div></section>
    <section className="dmr-card"><div className="dmr-card-head"><h3><RefreshCcw/>Source &amp; Sync Status</h3></div>
     {(sources.data||[]).map(s=><div className="mi-source" key={s.source}><span>{s.status==='ACTIVE'?<CheckCircle2 className="good" size={18}/>:<XCircle className="bad" size={18}/>}<span><b>{s.source}</b><small>{s.status==='ACTIVE'?'Last sync: '+clock(s.last_sync):s.restriction}</small></span></span><Chip value={s.status}/></div>)}</section>
   </aside></div>
  :tab==='Sources'?<section className="dmr-card"><div className="dmr-card-head"><h3><Database/>Sources &amp; permissions</h3></div>{sources.data?.length?<div className="mi-table"><table><thead><tr><th>Source</th><th>Status</th><th>Permission</th><th>Independence group</th><th>Observations</th><th>Restriction / terms</th></tr></thead>
   <tbody>{sources.data.map(s=><tr key={s.source}><td><b>{s.source}</b></td><td><Chip value={s.status}/></td><td>{s.permission}</td><td>{s.independence_group||'—'}</td><td>{n(s.observations)}</td><td>{s.restriction||'—'}{s.terms_url&&<a href={s.terms_url} target="_blank" rel="noreferrer"> terms</a>}</td></tr>)}</tbody></table></div>:<Empty>No sources registered.</Empty>}</section>
  :tab==='Sports Coverage'?<section className="dmr-card"><div className="dmr-card-head"><h3><Globe2/>Sports coverage</h3></div>{coverage.data?.length?<div className="mi-table"><table><thead><tr><th>Country</th><th>Competition</th><th>Seasons</th><th>Fixtures</th><th>Priced</th><th>Prices</th><th>Verified results</th><th>Latest price</th><th>Research</th></tr></thead>
   <tbody>{coverage.data.map(c=><tr key={c.country+c.competition}><td>{c.country}</td><td><b>{c.competition}</b></td><td>{c.seasons}</td><td>{n(c.fixtures)}</td><td>{n(c.fixtures_priced)}</td><td>{n(c.price_observations)}</td><td>{n(c.verified_results)}</td><td>{fmt(c.latest_price_at)}</td><td>{c.research_ready?<Chip value="ACTIVE"/>:<span className="muted" title="Needs a second independent source">price archive only</span>}</td></tr>)}</tbody></table></div>:<Empty>{coverage.loading?'Loading…':'No competitions stored yet.'}</Empty>}</section>
  :tab==='Market Catalogue'?<section className="dmr-card"><div className="dmr-card-head"><h3><LayoutGrid/>Registered market catalogue</h3><select aria-label="Catalogue sport" value={sport} onChange={e=>setSport(e.target.value)}>{(catalogue.data?.sports||[]).filter(s=>!s.discovery_only).map(s=><option key={s.key} value={s.key}>{s.name} ({s.definitions})</option>)}</select></div>
   <p className="dmr-caption">Registered definitions are market types the platform understands, not markets any bookmaker currently offers. Discovery-only sports: {(catalogue.data?.sports||[]).filter(s=>s.discovery_only).map(s=>s.name).join(', ')||'—'}.</p>
   {catalogueRows.length?<div className="mi-table mi-scroll"><table><thead><tr><th>Market</th><th>Category</th><th>Kind</th><th>Selections</th><th>Origin</th></tr></thead><tbody>{catalogueRows.map(d=><tr key={d.id}><td><b>{d.name}</b></td><td>{d.category.replace('_',' ')}</td><td>{d.kind.replace('_',' ').toLowerCase()}</td><td>{d.outcomes.slice(0,4).map(o=>o.label).join(' | ')}</td><td>{d.origin.toLowerCase()}</td></tr>)}</tbody></table></div>:<Empty>{catalogue.loading?'Loading…':'No definitions.'}</Empty>}</section>
  :tab==='Sync History'?<section className="dmr-card"><div className="dmr-card-head"><h3><History/>Sync history</h3></div>{history.data?.length?<div className="mi-table"><table><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Detail</th></tr></thead>
   <tbody>{history.data.map((h,i)=><tr key={i}><td>{fmt(h.at)}</td><td>{h.actor}</td><td>{h.action}</td><td>{Object.entries(h.detail).map(([k,v])=>`${k.replaceAll('_',' ')}: ${Array.isArray(v)?v.length:String(v)}`).join(' · ')||'—'}</td></tr>)}</tbody></table></div>:<Empty>{history.loading?'Loading…':'No synchronisations recorded yet.'}</Empty>}</section>
  :<section className="dmr-card"><div className="dmr-card-head"><h3><Activity/>Source health</h3></div>{healthSources.length?<div className="mi-table"><table><thead><tr><th>Source</th><th>Status</th><th>Last sync</th><th>Next sync</th><th>Data age</th><th>Observations</th><th>Result evidence</th><th>Sync failures</th></tr></thead>
   <tbody>{healthSources.map(s=><tr key={s.source}><td><b>{s.source}</b></td><td><Chip value={s.status}/></td><td>{fmt(s.last_sync)}</td><td>{fmt(s.next_sync)}</td><td>{s.freshness_minutes==null?'—':s.freshness_minutes<120?s.freshness_minutes+' min':Math.round(s.freshness_minutes/60)+' h'}</td><td>{n(s.observations)}</td><td>{n(s.verified_result_evidence)}</td><td>{n(s.sync_failures)}</td></tr>)}</tbody></table></div>:<Empty>No sources registered.</Empty>}</section>}
  {o&&<p className="dmr-note">{o.notice}</p>}
 </div>;
}
