import {LiveUpdatesProvider} from './LiveUpdates';
import {WorkflowProvider} from './WorkflowContext';
import {ResearchScopeProvider} from './ResearchCatalogue';
import React from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter,Routes,Route,Navigate}from'react-router-dom';import App from './App';import './style.css';createRoot(document.getElementById('root')!).render(<React.StrictMode><BrowserRouter><Routes><Route path="/sports/*" element={<LiveUpdatesProvider><ResearchScopeProvider><WorkflowProvider><App/></WorkflowProvider></ResearchScopeProvider></LiveUpdatesProvider>}/><Route path="*" element={<Navigate to="/sports/dashboard" replace/>}/></Routes></BrowserRouter></React.StrictMode>);
