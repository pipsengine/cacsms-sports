"""AI Predictions layout check using isolated (mocked) API responses. Values are test fixtures only."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE=os.getenv('CACSMS_UI_URL','http://localhost:5173')
STAMP='2026-11-16T15:58:00Z'


def market(key,name,fam,sels):
    return dict(key=key,name=name,family=fam,observed_at=STAMP,selections=[dict(key=k,name=n,odds=o,observed_at=STAMP,predicted=p) for k,n,o,p in sels])


def evaluation(i,market_key,mname,sel,prob,lo,hi,odds,decision,reasons):
    return dict(prediction_id='p'+str(i),market_key=market_key,market=mname,family='Main Markets',outcome_key=sel.upper(),selection=sel,probability=prob,lower=lo,upper=hi,model='Logit 1.0',predicted_at=STAMP,
                odds=odds,odds_observed_at=STAMP,ev=round((prob/100*odds-1)*100,1) if odds else None,conservative_ev=round((lo/100*odds-1)*100,1) if odds and lo else None,decision=decision,reasons=reasons,gates={})


def workspace(ident,empty=False):
    home,away=('FC Bayern München','1. FC Köln') if ident=='f1' else ('Other Home','Other Away')
    markets=[] if empty else [market('1X2','1X2 (Match Result)','Main Markets',[('HOME','Home',1.27,True),('DRAW','Draw',5.40,True),('AWAY','Away',12.0,True)]),
        market('BTTS','Both Teams to Score','Both Teams to Score',[('YES','Yes',2.08,True),('NO','No',1.73,True)]),
        market('DC','Double Chance','Double Chance',[('1X','1X',1.05,False),('X2','X2',3.60,False),('12','12',1.13,False)]),
        market('AH_0','Asian Handicap 0','Handicap Markets',[('HOME','Home',1.36,False),('AWAY','Away',3.20,False)]),
        market('CS','Correct Score','Correct Score',[('1-0','1-0',6.0,False),('2-0','2-0',5.75,False)]),
        market('OU_2.5','Over/Under 2.5','Totals / Over-Under',[('OVER','Over',1.56,True),('UNDER','Under',2.47,True)])]
    fams=['Main Markets','Goals Markets','Both Teams to Score','Double Chance','Handicap Markets','Totals / Over-Under','Half Time Markets','Correct Score','Multigoals','Other Markets']
    evals=[] if empty else [evaluation(1,'1X2','1X2 (Match Result)','Home',82.4,80.1,84.6,1.27,'QUALIFIED',[]),evaluation(2,'OU_2.5','Over/Under 2.5','Over',71.6,68.0,75.0,1.56,'QUALIFIED',[]),
        evaluation(3,'BTTS','Both Teams to Score','No',68.1,64.0,72.0,1.73,'QUALIFIED',[]),evaluation(4,'1X2','1X2 (Match Result)','Draw',12.1,10.0,14.0,5.40,'REJECTED',['INSUFFICIENT_VALUE']),
        evaluation(5,'1X2','1X2 (Match Result)','Away',5.5,4.0,7.0,12.0,'REJECTED',['INSUFFICIENT_VALUE'])]
    row=lambda k,l,h,a:dict(key=k,label=l,home=h,away=a,unit='')
    return dict(fixture=dict(id=ident,home=home,away=away,kickoff_at='2026-11-16T16:30:00Z',matchday=12,competition_id='league',competition='Bundesliga',country='Germany',sport='Football',season_id='season'),cutoff=STAMP,
        teams=dict(home=dict(name=home,standing=dict(rank=1,points=68),form='WWWDW'),away=dict(name=away,standing=dict(rank=14,points=12),form='LWLDL')),
        bookmakers=[] if empty else ['SportyBet'],bookmaker=None if empty else 'SportyBet',markets=markets,families=[dict(name=f,count=sum(mk['family']==f for mk in markets)) for f in fams],
        coverage=dict(selections=14,modelled=7,percent=None if empty else 50.0,inventory='UNVERIFIED',last_sync=None if empty else STAMP,next_sync='2026-11-16T16:00:00Z',fresh=not empty),
        outcome=dict(probabilities={} if empty else {'HOME':82.4,'DRAW':12.1,'AWAY':5.5},confidence=None if empty else 'High'),evaluations=evals,
        insights=[] if empty else [home+' 1st (68 pts); '+away+' 14th (12 pts).',away+' last 5: 1W, 1D, 3L.','Expected goals: 2.71 vs 1.08.'],verdict=None if empty else 'Model favours home win (82.4%).',
        key_metrics=[] if empty else [row('xg_per_match','xG (Expected Goals)',2.71,1.08),row('attack_strength','Attack Strength',94.6,63.1),row('defence_strength','Defence Strength',88.2,56.8)],
        research=dict(summary=[dict(key='statistics',name='Statistical Analysis',status='VERIFIED')],evidence_groups=[dict(key='sources',name='External Sources',count=3)],evidence=[]),
        models=[dict(id='m',name='Logit',version='1.0',status='ACTIVE',approved=True,calibration_verified=True,calibration_error=0.021,holdout_brier=0.198,baseline_brier=0.241,holdout_count=300)],
        pipeline=[dict(key=k,name=n,status=None if empty and k in ('markets','model','predict') else 'VERIFIED') for k,n in [('markets','Markets'),('collect','Collect'),('research','Research'),('features','Features'),('model','Model'),('predict','Predict'),('validate','Validate')]],
        history=[dict(id='h'+str(i),market='1X2 (Match Result)',selection=s,probability=p,model='Logit 1.0',model_status='ACTIVE',predicted_at=STAMP,after_cutoff=False) for i,(s,p) in enumerate([('Home',82.4),('Draw',12.1)])],
        metrics=dict(fixtures_analysed=24736,predictions=19842,model_brier=0.198,average_probability=71.4),runtime=dict(worker_online=True,next_run_at='2026-11-16T16:00:00Z'),message='Test prediction context')


def main():
    with sync_playwright() as p:
        b=p.chromium.launch();page=b.new_page(viewport={'width':1672,'height':941});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.add_init_script("try{if(!sessionStorage.getItem('aip-test')){localStorage.removeItem('cacsms.predictions.markets');sessionStorage.setItem('aip-test','1')}}catch(e){}")
        def respond(route):
            url=route.request.url
            if '/market-scanner/fixtures/' in url:
                ident=url.split('/fixtures/')[1].split('?')[0];data=workspace(ident,empty=ident=='f2')
            else:
                endpoint=url.split('/catalog/')[1].split('?')[0]
                data={'sports':[dict(id='sport',name='Football')],'countries':[dict(name='Germany')],'leagues':[dict(id='league',name='Bundesliga')],'seasons':[dict(id='season',label='2026/2027',is_current=True)],
                      'fixtures':[dict(id='f1',home='FC Bayern München',away='1. FC Köln',kickoff='2026-11-16T16:30:00Z',status='SCHEDULED'),dict(id='f2',home='Other Home',away='Other Away',kickoff='2026-11-16T16:30:00Z',status='SCHEDULED')]}[endpoint]
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        page.route('**/research/catalog/**',respond);page.route('**/market-scanner/**',respond)
        page.goto(BASE+'/sports/predictions');page.locator('.dmr-match').wait_for()
        assert page.locator('.aip-tabs button').count()==6
        assert page.locator('.aip-pipeline .dmr-step').count()==7
        assert page.locator('.aip-market-table tbody tr').count()==6
        assert page.locator('.aip-selected-row').count()==3, 'default selection = modelled markets'
        page.get_by_label('Select Double Chance').check();assert page.locator('.aip-selected-row').count()==4
        page.get_by_role('button',name='Handicap Markets (1)').click();assert page.locator('.aip-market-table tbody tr').count()==1
        page.get_by_role('button',name='All Markets (6)').click()
        page.get_by_label('Search markets').fill('over');assert page.locator('.aip-market-table tbody tr').count()==1
        page.get_by_label('Search markets').fill('')
        assert page.locator('.aip-outcomes>div').count()==3 and page.get_by_text('82.4%').count()>=2
        assert page.locator('.aip-cards .aip-table tbody tr').count()==3 and page.locator('.aip-cards .aip-decision-icon.good').count()==3
        assert page.locator('.aip-families button').count()==7, 'empty categories hidden'
        page.get_by_text('Model favours home win (82.4%).').wait_for()
        page.locator('.dmr-kickoff b',has_text='Bundesliga — Matchday 12').wait_for()
        (ROOT/'artifacts').mkdir(exist_ok=True);page.screenshot(path=str(ROOT/'artifacts/predictions-test-desktop.png'),full_page=True,animations='disabled')
        for tab in ['SportyBet Markets','Probability Analysis','Model Intelligence','Evidence & Research','Prediction History','Match Prediction']:
            page.get_by_role('tab',name=tab,exact=True).click()
        page.reload();page.locator('.dmr-match').wait_for()
        assert page.locator('.aip-selected-row').count()==4, 'selection persists per viewer'
        page.get_by_label('Fixture',exact=True).select_option('f2')
        page.locator('.dmr-home h3',has_text='Other Home').wait_for()
        page.get_by_text('No 1X2 forecast from an ACTIVE model before the cutoff.').wait_for()
        assert page.get_by_text('No ACTIVE-model forecast to summarise.').count()==1
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(200)
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.get_by_label('Fixture',exact=True).select_option('f1');page.locator('.dmr-home h3',has_text='FC Bayern').wait_for()
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(ROOT/'artifacts/predictions-test-mobile.png'),full_page=True,animations='disabled')
        assert not errors,errors
        b.close()
    print('PASS: AI Predictions layout, catalogue filters/search/selection persistence, outcome, selections, verdict, 6 tabs, empty states, desktop/mobile overflow.')

if __name__=='__main__':main()
