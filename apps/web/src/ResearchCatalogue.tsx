import {StandingsGovernance} from './StandingsGovernance';
import React,{createContext,useContext,useEffect,useMemo,useState} from 'react';
import {CalendarDays,Database,Filter,RefreshCcw,ShieldCheck} from 'lucide-react';
import './ResearchCatalogue.css';

const API='/api/v1/sports/research/catalog/';
type Row=Record<string,unknown>;
type Option={id?:string;name?:string;label?:string};
type Selection={sport:string;country:string;league:string;season:string;fixture:string;asOf:string};
type ScopeContext={selection:Selection;change:(key:keyof Selection,value:string)=>void;revision:number;refresh:()=>void};
const Scope=createContext<ScopeContext|null>(null);
const initial:Selection={sport:'',country:'',league:'',season:'',fixture:'',asOf:''};
export function ResearchScopeProvider({children}:{children:React.ReactNode}){
 const[selection,setSelection]=useState<Selection>(initial),[revision,setRevision]=useState(0);
 const change=(key:keyof Selection,value:string)=>setSelection(s=>{
  const next={...s,[key]:value};
  if(key==='sport'){next.country='';next.league='';next.season='';next.fixture=''}
  if(key==='country'){next.league='';next.season='';next.fixture=''}
  if(key==='league'){next.season='';next.fixture=''}
  if(key==='season')next.fixture='';
  return next;
 });
 return <Scope.Provider value={{selection,change,revision,refresh:()=>setRevision(n=>n+1)}}>{children}</Scope.Provider>;
}
export function useResearchScope(){const value=useContext(Scope);if(!value)throw Error('Research provider missing');return value}
export function useResearchRemote<T>(url:string|null,revision:number){
 const[state,setState]=useState<{key:string|null;data:T|null;loading:boolean;error:string}>({key:null,data:null,loading:false,error:''});
 useEffect(()=>{if(!url){setState({key:null,data:null,loading:false,error:''});return}const controller=new AbortController();setState({key:url,data:null,loading:true,error:''});fetch(url,{signal:controller.signal}).then(async r=>{const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Unable to load records (HTTP '+r.status+')');return data}).then(data=>setState({key:url,data,loading:false,error:''})).catch(e=>{if(!controller.signal.aborted)setState({key:url,data:null,loading:false,error:String(e.message||e)})});return()=>controller.abort()},[url,revision]);
 return state.key===url?state:{key:url,data:null,loading:!!url,error:''};
}
function Selector({label,value,onChange,options,disabled=false,placeholder}:{label:string;value:string;onChange:(v:string)=>void;options:Option[];disabled?:boolean;placeholder:string}){
 return <label className="research-field"><span>{label}</span><select aria-label={label} value={value} disabled={disabled} onChange={e=>onChange(e.target.value)}><option value="">{placeholder}</option>{options.map(o=><option key={o.id||o.name} value={o.id||o.name}>{o.label||o.name}</option>)}</select></label>;
}
export function ResearchFilters(){
 const{selection:s,change,revision,refresh}=useResearchScope();
 const sports=useResearchRemote<Option[]>(API+'sports',revision);
 // Sport values use canonical names, while league and season values use shared IDs.
 const countries=useResearchRemote<Option[]>(s.sport?API+'countries?'+new URLSearchParams({sport:s.sport}):null,revision);
 const leagues=useResearchRemote<Option[]>(s.sport?API+'leagues?'+new URLSearchParams({sport:s.sport,...(s.country?{country:s.country}:{})}):null,revision);
 const seasons=useResearchRemote<Option[]>(s.league?API+'seasons?'+new URLSearchParams({league_id:s.league}):null,revision);
 const errors=[sports,countries,leagues,seasons].map(x=>x.error).filter(Boolean);
 return <section className="panel research-filter-panel" aria-label="Shared research filters"><div className="panel-head"><div><h3><Filter size={16}/> Shared research catalogue</h3><p>Competition and season selection follows you across research pages.</p></div><button type="button" className="secondary" onClick={refresh}><RefreshCcw size={14}/> Refresh</button></div><div className="research-filters">
 <Selector label="Sport" value={s.sport} onChange={v=>change('sport',v)} options={(sports.data||[]).map(o=>({name:o.name}))} placeholder={sports.loading?'Loading sports...':'Choose sport'}/>
 <Selector label="Country" value={s.country} onChange={v=>change('country',v)} options={countries.data||[]} disabled={!s.sport||countries.loading} placeholder="All countries"/>
 <Selector label="League / Division" value={s.league} onChange={v=>change('league',v)} options={leagues.data||[]} disabled={!s.sport||leagues.loading} placeholder="Choose competition"/>
 <Selector label="Season" value={s.season} onChange={v=>change('season',v)} options={seasons.data||[]} disabled={!s.league||seasons.loading} placeholder="All available history"/>
 <label className="research-field"><span>As of (local time)</span><input type="datetime-local" value={s.asOf} onChange={e=>change('asOf',e.target.value)}/></label></div>
 {errors.length>0&&<p className="error" role="alert">Catalogue unavailable: {errors.join('; ')}</p>}
 {!sports.loading&&!sports.error&&!sports.data?.length&&<p className="research-caption">No sports registered. Use authorized fixture intake to populate the shared catalogue.</p>}
 {s.league&&!seasons.loading&&!seasons.error&&!seasons.data?.length&&<p className="research-caption">No seasons registered for this competition. Existing fixtures remain available under all history.</p>}
 </section>;
}
function Empty({children}:{children:React.ReactNode}){return <div className="empty"><Database size={30}/><b>No verified records available</b><span>{children}</span></div>}
function Records({rows,columns}:{rows:Row[];columns:[string,string][]}){return <div className="table-scroll"><table><thead><tr>{columns.map(([key,title])=><th key={key}>{title}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={String(row.id||row.club||i)}>{columns.map(([key])=><td key={key}>{key==='rank'?<span className={Number(row.rank??row.computed_rank)<=2?'research-rank leader':'research-rank'}>{String(row.rank??row.computed_rank??'-')}</span>:key==='kickoff'||key.endsWith('_at')?row[key]?new Date(String(row[key])).toLocaleString():'-':row[key]==null?'-':typeof row[key]==='object'?<code className="research-value">{JSON.stringify(row[key])}</code>:String(row[key])}</td>)}</tr>)}</tbody></table></div>}
type StandingReport={mode:string;scope:string;warning:string|null;rows:Row[];source:{name:string;source_url:string;captured_at:string;verified_at:string;official:boolean;source_reference:string}|null;verified_matches?:number};
type Dossier={status:string;cutoff:string;warning:string;evidence:Row[];dossiers:Row[];features:Row[];predictions:Row[];fixture:{id:string;home:string;away:string}};
export function ResearchCatalogueWorkspace({page}:{page:'fixtures'|'statistics'|'research'|'match-analysis'|'predictions'}){
 const{selection:s,change,revision}=useResearchScope();const[scope,setScope]=useState('overall');const[clubQuery,setClubQuery]=useState('');
 const params=useMemo(()=>new URLSearchParams({...s.league?{league_id:s.league}:{},...s.season?{season_id:s.season}:{}}),[s.league,s.season]);
 const history=useMemo(()=>{const q=new URLSearchParams(params);if(s.asOf){const date=new Date(s.asOf);if(!Number.isNaN(date.getTime()))q.set('as_of',date.toISOString())}return q},[params,s.asOf]);
 const fixtureData=useResearchRemote<Row[]>(s.league?API+'fixtures?'+params:null,revision);
 const tableData=useResearchRemote<StandingReport>(s.league&&page==='statistics'?API+'standings?'+history+'&scope='+scope:null,revision);
 const dossierData=useResearchRemote<Dossier>(s.fixture&&!['statistics','fixtures'].includes(page)?API+'dossiers/'+encodeURIComponent(s.fixture)+(history.has('as_of')?'?as_of='+encodeURIComponent(history.get('as_of')!):''):null,revision);
 const dataset=page==='statistics'?tableData:page==='fixtures'?fixtureData:dossierData;
 const tableRows=(tableData.data?.rows||[]).filter(row=>String(row.club).toLowerCase().includes(clubQuery.toLowerCase()));
 const titles={fixtures:'Competition fixtures',statistics:'League standings',research:'Match evidence dossier','match-analysis':'Research and feature evidence',predictions:'Stored prediction evidence'};
 return <section className="panel research-workspace"><div className="panel-head"><div><h3><CalendarDays size={17}/>{titles[page]}</h3><p>{page==='statistics'?'Verified source tables with an explicitly unofficial football fallback.':'Shared fixture identities, actual records and traceable evidence.'}</p></div><span className="tag"><ShieldCheck size={12}/> PAPER ONLY</span></div>
 {page==='statistics'&&<div className="dataset-tabs" role="group" aria-label="Standings scope">{['overall','home','away'].map(v=><button type="button" key={v} className={scope===v?'selected':''} onClick={()=>setScope(v)}>{v[0].toUpperCase()+v.slice(1)}</button>)}</div>}
 {page==='statistics'&&<label className="research-club-search"><span>Find club</span><input aria-label="Find club" placeholder="Search club name" value={clubQuery} onChange={e=>setClubQuery(e.target.value)}/></label>}
 {!['statistics','fixtures'].includes(page)&&<Selector label="Fixture" value={s.fixture} onChange={v=>change('fixture',v)} options={(fixtureData.data||[]).map(f=>({id:String(f.id),name:String(f.home)+' vs '+String(f.away)+' | '+new Date(String(f.kickoff)).toLocaleDateString()}))} disabled={!s.league||fixtureData.loading} placeholder={fixtureData.loading?'Loading fixtures...':'Choose fixture'}/>}
 {fixtureData.error&&page!=='fixtures'&&<p className="error" role="alert">Fixture catalogue: {fixtureData.error}</p>}
 {dataset.loading?<div className="empty">Loading research records...</div>:dataset.error?<p className="error" role="alert">{dataset.error}</p>:page==='fixtures'?fixtureData.data?.length?<><Records rows={fixtureData.data} columns={[["kickoff","Kickoff"],["home","Home"],["away","Away"],["status","Status"],["home_score","Home goals"],["away_score","Away goals"]]}/><p className="research-caption">Latest 100 fixtures. Scores appear only when supported by verified result evidence.</p></>:<Empty>Select a competition with ingested fixtures.</Empty>:page==='statistics'?tableData.data?<>
 <div className="research-provenance"><span className="evidence-state neutral">{tableData.data.mode.replaceAll('_',' ')}</span><span>{tableData.data.source?tableData.data.source.official?'Official source snapshot':'Verified source snapshot':`${tableData.data.verified_matches??0} verified completed fixtures`}</span></div>
 {tableData.data.warning&&<div className="research-warning">{tableData.data.warning}</div>}
 {tableData.data.source&&<p className="research-caption">{tableData.data.source.name} | Captured {new Date(tableData.data.source.captured_at).toLocaleString()} | Verified {new Date(tableData.data.source.verified_at).toLocaleString()} | <a href={tableData.data.source.source_url} target="_blank" rel="noreferrer">Source evidence</a> | Reference: {tableData.data.source.source_reference}</p>}
 {tableRows.length?<Records rows={tableRows} columns={[["rank","Pos"],["club","Club"],["played","P"],["wins","W"],["draws","D"],["losses","L"],["goals_for","GF"],["goals_against","GA"],["goal_difference","GD"],["points","Pts"],["form","Form"]]}/>:<Empty>{tableData.data.rows.length?'No clubs match your search.':'No verified standings for the selected season, cutoff and scope.'}</Empty>}
 <p className="research-caption">The top two ranks are highlighted. Computed ranks are research only and do not qualify wagers.</p></>:<Empty>Select a competition to inspect league standings.</Empty>:dossierData.data?<>
 <div className="research-provenance"><strong>{dossierData.data.fixture.home} vs {dossierData.data.fixture.away}</strong><span className="evidence-state neutral">{dossierData.data.status.replaceAll('_',' ')}</span><span>Cutoff: {new Date(dossierData.data.cutoff).toLocaleString()}</span></div><div className="research-warning">{dossierData.data.warning}</div>
 <div className="mini-metrics">{[['Evidence records',dossierData.data.evidence.length],['Research versions',dossierData.data.dossiers.length],['Feature snapshots',dossierData.data.features.length],['Stored forecasts',dossierData.data.predictions.length]].map(([label,count])=><div className="mini-metric" key={label}><span>{label}</span><strong>{count}</strong></div>)}</div>
 {page==='research'?dossierData.data.evidence.length?<Records rows={dossierData.data.evidence} columns={[["section","Section"],["source","Source"],["observed_at","Observed"],["verification","Provenance"],["data","Evidence"]]}/>:<Empty>No authorized pre-match observations linked to this fixture.</Empty>:page==='match-analysis'?dossierData.data.features.length?<Records rows={dossierData.data.features} columns={[["id","Feature ID"],["research_id","Research ID"],["cutoff_at","Cutoff"],["features","Features"]]}/>:<Empty>No feature snapshots for this fixture and cutoff.</Empty>:dossierData.data.predictions.length?<Records rows={dossierData.data.predictions} columns={[["model_id","Model ID"],["market_key","Market"],["outcome_key","Selection"],["probability","Probability"],["predicted_at","Predicted"]]}/>:<Empty>No stored forecasts for this fixture and cutoff. Models must pass the existing approval and calibration gates.</Empty>}
 {page==='research'&&dossierData.data.dossiers.length>0&&<><h4>Research dossier versions</h4><Records rows={dossierData.data.dossiers} columns={[["version","Version"],["status","Status"],["sections","Section review"],["evidence_ids","Evidence IDs"]]}/></>}
 </>:<Empty>Select a competition and fixture to inspect its research evidence.</Empty>}
 {page==='statistics'&&<StandingsGovernance scope={scope}/>}
 </section>;
}
