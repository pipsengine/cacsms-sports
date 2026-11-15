import React from 'react';
import {NavLink} from 'react-router-dom';
import {ArrowRight,CheckCircle2,CircleDot,CircleMinus,CircleX,Clock3,Flag,LoaderCircle,Radio,ShieldAlert} from 'lucide-react';
import './StageFlow.css';

export type FlowCounts={total:number;verified:number;settled:number;outcomes:number;waiting:number;blocked:number};
export type FlowStep={key:string;name:string;status:string;caption?:string;meta?:string;href?:string;title?:string;counts?:FlowCounts};
export type Tone='done'|'outcome'|'running'|'waiting'|'blocked'|'skipped'|'pending';

export const OUTCOME_STATUSES=['NO_OPPORTUNITY','INSUFFICIENT_DATA','REJECTED'];
const CONTINUOUS=['monitor','reconcile'];

export function toneOf(status?:string):Tone{
 const s=(status||'').toUpperCase();
 if(['VERIFIED','COMPLETED','MONITORING'].includes(s))return 'done';
 if(OUTCOME_STATUSES.includes(s))return 'outcome';
 if(s==='RUNNING')return 'running';
 if(['WAITING_FOR_DATA','RETRY_SCHEDULED'].includes(s))return 'waiting';
 if(['BLOCKED','FAILED'].includes(s))return 'blocked';
 if(s==='NOT_APPLICABLE')return 'skipped';
 return 'pending';
}

/** Aggregate stage status from counts across many runs. */
export function aggregateStatus(c?:FlowCounts){
 if(!c||!c.total)return 'PENDING';
 if(c.blocked)return 'BLOCKED';
 if(c.settled===c.total)return c.verified?'VERIFIED':'NO_OPPORTUNITY';
 // Partially settled stages are waiting on the remaining fixtures; the bar shows the split.
 return c.waiting?'WAITING_FOR_DATA':'RUNNING';
}

const ICONS:Record<Tone,React.ReactNode>={done:<CheckCircle2/>,outcome:<Flag/>,running:<LoaderCircle className="sf-spin"/>,waiting:<Clock3/>,blocked:<ShieldAlert/>,skipped:<CircleMinus/>,pending:<CircleDot/>};
const LABELS:Record<Tone,string>={done:'Verified',outcome:'Business outcome',running:'In progress',waiting:'Waiting',blocked:'Blocked',skipped:'Not applicable',pending:'Pending'};
// Connector semantics: work flows on, is diverted to monitoring by an outcome, is waiting, or is stopped.
const CONNECTOR:Record<Tone,string>={done:'flow',outcome:'diverted',running:'active',waiting:'active',blocked:'stopped',skipped:'idle',pending:'idle'};

function Bar({c}:{c:FlowCounts}){
 const pct=(n:number)=>c.total?(n/c.total*100)+'%':'0%';
 return <span className="sf-bar" aria-hidden="true"><i className="sf-seg-done" style={{width:pct(c.verified)}}/><i className="sf-seg-outcome" style={{width:pct(c.outcomes)}}/><i className="sf-seg-waiting" style={{width:pct(c.waiting)}}/><i className="sf-seg-blocked" style={{width:pct(c.blocked)}}/></span>;
}

export function StageFlow({steps,selected,onSelect,compact=false,label='Pipeline process flow'}:{steps:FlowStep[];selected?:string|null;onSelect?:(key:string)=>void;compact?:boolean;label?:string}){
 return <ol className={'sf-flow'+(compact?' sf-compact':'')} aria-label={label}>
  {steps.map((step,i)=>{
   const tone=toneOf(step.status);const last=i===steps.length-1;
   const body=<>
    <span className="sf-node" aria-hidden="true">{ICONS[tone]}</span>
    <span className="sf-text">
     <span className="sf-index">{String(i+1).padStart(2,'0')}{CONTINUOUS.includes(step.key)&&<span className="sf-continuous" title="Runs continuously for every fixture"><Radio/>Continuous</span>}</span>
     <b>{step.name}</b>
     <small className="sf-state">{step.caption||LABELS[tone]}</small>
     {step.meta&&<small className="sf-meta">{step.meta}</small>}
     {step.counts&&<Bar c={step.counts}/>}
    </span>
   </>;
   const common={className:'sf-card','aria-label':step.name+': '+(step.caption||LABELS[tone]),title:step.title||step.caption||LABELS[tone]};
   const card=onSelect?<button type="button" {...common} aria-pressed={selected===step.key} onClick={()=>onSelect(step.key)}>{body}</button>
    :step.href?<NavLink to={step.href} {...common}>{body}</NavLink>:<div {...common}>{body}</div>;
   return <li key={step.key} className={'sf-step sf-'+tone+(selected===step.key?' sf-selected':'')}>
    {card}
    {!last&&<span className={'sf-arrow sf-arrow-'+CONNECTOR[tone]} aria-hidden="true"><span className="sf-line"/><ArrowRight/></span>}
   </li>;
  })}
 </ol>;
}

export function FlowLegend(){
 return <div className="sf-legend" aria-label="Process flow legend">
  <span><i className="sf-dot done"/>Verified · flows on</span><span><i className="sf-dot outcome"/>Business outcome · diverted to monitoring</span>
  <span><i className="sf-dot waiting"/>Waiting / in progress</span><span><i className="sf-dot blocked"/>Blocked / failed · stopped</span><span><i className="sf-dot pending"/>Pending / not applicable</span>
 </div>;
}
