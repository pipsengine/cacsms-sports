import React,{createContext,useContext,useEffect,useRef,useState} from 'react';
const Live=createContext({revision:0,connected:false});
export function LiveUpdatesProvider({children}:{children:React.ReactNode}){
 const[revision,setRevision]=useState(0),[connected,setConnected]=useState(false);
 useEffect(()=>{let debounce:ReturnType<typeof setTimeout>|undefined;const refresh=()=>setRevision(n=>n+1);const source=new EventSource('/api/v1/sports/live/stream');source.addEventListener('hello',()=>{setConnected(true);refresh()});source.addEventListener('change',()=>{setConnected(true);if(debounce)clearTimeout(debounce);debounce=setTimeout(refresh,300)});source.onerror=()=>setConnected(false);const timer=setInterval(refresh,10000);const wake=()=>{if(!document.hidden)refresh()};document.addEventListener('visibilitychange',wake);window.addEventListener('online',refresh);return()=>{source.close();clearInterval(timer);if(debounce)clearTimeout(debounce);document.removeEventListener('visibilitychange',wake);window.removeEventListener('online',refresh)}},[]);
 return <Live.Provider value={{revision,connected}}>{children}</Live.Provider>;
}
export function useLiveUpdates(){return useContext(Live)}
export function useBackendRefresh(setter:React.Dispatch<React.SetStateAction<number>>){const{revision}=useLiveUpdates();const previous=useRef(revision);useEffect(()=>{if(previous.current!==revision){previous.current=revision;setter(n=>n+1)}},[revision,setter])}
