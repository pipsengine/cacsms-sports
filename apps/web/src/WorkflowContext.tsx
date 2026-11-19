import {useBackendRefresh} from './LiveUpdates';
import React,{createContext,useContext,useEffect,useState} from 'react';
import {NavLink,useLocation,useNavigate} from 'react-router-dom';
import {workflowStages,stageHref} from './workflowStages';
import {useResearchScope} from './ResearchCatalogue';
import './WorkflowContext.css';
type Row=Record<string,unknown>;
type Stage={stage_key:string;name:string;status:string;error:string|null;started_at:string|null;finished_at:string|null;duration_ms:number|null;retry_count:number;next_retry_at:string|null;evidence_ids:string[];output:Row;href:string;input_version?:number;output_version?:number;output_reference?:string|null;failure_code?:string|null;next_stage?:string|null;quality_score?:number|null};
type Context={fixture:{id:string;home_name:string;away_name:string;kickoff_at:string;competition_id:string;season_id:string|null;sport:string;competition:string};run:{id:string;fixture_id:string;status:string;progress:number;stages:Stage[]}|null;datasets:Record<string,Row[]>;operations:Row[]};
const Workflow=createContext<{data:Context|null;error:string;loading:boolean}>({data:null,error:'',loading:false});
export function WorkflowProvider({children}:{children:React.ReactNode}){
 const location=useLocation(),{selectFixture}=useResearchScope();const params=new URLSearchParams(location.search);const run=params.get('run_id'),fixture=params.get('fixture_id');
 const[data,setData]=useState<Context|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),[revision,setRevision]=useState(0);
 useEffect(()=>{setData(null)},[run,fixture]);
 useBackendRefresh(setRevision);
 useEffect(()=>{if(!run&&!fixture){setData(null);setError('');setLoading(false);return}const controller=new AbortController();setLoading(true);const q=new URLSearchParams();if(run)q.set('run_id',run);if(fixture)q.set('fixture_id',fixture);
 fetch('/api/v1/sports/pipeline/context?'+q,{signal:controller.signal}).then(async r=>{const result=await r.json();if(!r.ok)throw Error(result.detail||'Workflow context unavailable');return result}).then((next:Context)=>{if(!controller.signal.aborted){setData(next);setError('')}}).catch(e=>{if(!controller.signal.aborted){setError(String(e.message));setData(null)}}).finally(()=>{if(!controller.signal.aborted)setLoading(false)});return()=>controller.abort()},[run,fixture,revision]);
 const f=data?.fixture;
 useEffect(()=>{if(f)selectFixture(f)},[f?.id,f?.sport,f?.competition_id,f?.season_id,selectFixture]);
 return <Workflow.Provider value={{data,error,loading}}>{children}</Workflow.Provider>;
}
function redact(key:string,value:unknown):unknown{if(/password|secret|token|api.?key|authorization|cookie/i.test(key))return '[REDACTED]';if(Array.isArray(value))return value.map(v=>redact('',v));if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,redact(k,v)]));return value}
export function WorkflowContextPanel(){
 const{data,error,loading}=useContext(Workflow),location=useLocation(),navigate=useNavigate();const query=new URLSearchParams(location.search);
 if(!query.has('run_id')&&!query.has('fixture_id'))return null;
 const path=location.pathname.replace('/sports/','');const target=workflowStages.find(item=>item[2]===path||(item[0]==='allocate'&&path.startsWith('programmes/')));
 const key=target?.[0]||query.get('stage')||'discover',stage=data?.run?.stages.find(s=>s.stage_key===key),records=data?.datasets[key]||[];
 return <section className="panel workflow-context" aria-label="Fixture workflow context"><div className="panel-head"><div><span className="eyebrow">SHARED WORKFLOW CONTEXT</span><h3>{data?data.fixture.home_name+' vs '+data.fixture.away_name:'Loading fixture context'}</h3><p>{data?.fixture.competition} {data&&' | '+new Date(data.fixture.kickoff_at).toLocaleString()}</p></div><button className="secondary" onClick={()=>navigate(location.pathname,{replace:true})}>Clear context</button></div>
 {error?<p className="error" role="alert">{error}</p>:!data?<p>{loading?'Loading actual workflow records...':'No fixture context found.'}</p>:<><nav className="workflow-step-links" aria-label="Workflow stages">{workflowStages.map((s,i)=><NavLink key={s[0]} to={stageHref(i,data.run||{fixture_id:data.fixture.id})} className={key===s[0]?'selected':''}>{i+1}. {s[1]}</NavLink>)}</nav>
 <div className="workflow-context-metrics"><div><small>Run</small><strong>{data.run?.id.slice(0,12)||'Awaiting automatic run'}</strong></div><div><small>{target?.[1]||key}</small><strong>{stage?.status.replaceAll('_',' ')||'No stage execution yet'}</strong></div><div><small>Progress</small><strong>{data.run?Math.round(data.run.progress*100)+'%':'-'}</strong></div><div><small>Evidence records</small><strong>{records.length}</strong></div></div>
 {stage?.error&&<div className="workflow-reason" role="status">{stage.error}</div>}
 {stage&&<p className="research-caption">Started: {stage.started_at?new Date(stage.started_at).toLocaleString():'Not started'} | Finished: {stage.finished_at?new Date(stage.finished_at).toLocaleString():'-'} | {stage.duration_ms??0} ms | Retries: {stage.retry_count}{stage.next_retry_at?' | Retry due '+new Date(stage.next_retry_at).toLocaleString():''}</p>}
 {stage&&<p className="research-caption">Input v{stage.input_version??0} | Output v{stage.output_version??0}{stage.output_reference?' ('+stage.output_reference.slice(0,8)+')':''}{stage.quality_score!=null?' | Quality '+stage.quality_score:''}{stage.failure_code&&stage.status!=='VERIFIED'?' | '+stage.failure_code:''}{stage.next_stage?' | Next: '+stage.next_stage.toUpperCase():''}</p>}
 <details><summary>{target?.[3]||'Stage'}: recorded operation, evidence and inputs ({records.length})</summary><pre>{JSON.stringify(redact('',{stage,records}),null,2)}</pre></details>
 {key==='allocate'&&<div className="workflow-step-links">{['accumulator','singles','jackpot','draws','rollover'].map(p=><NavLink key={p} to={'/sports/programmes/'+p+'?'+new URLSearchParams({fixture_id:data.fixture.id,...(data.run?{run_id:data.run.id}:{}),stage:'allocate'})}>{p}</NavLink>)}</div>}
 </>}
 </section>;
}
