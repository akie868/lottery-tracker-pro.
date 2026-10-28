"""Lottery Tracker Pro web server. No fabricated draw data."""
import os, re, time, json, sqlite3, threading
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get('LOTTERY_DB',str(ROOT/'draws.sqlite3')))
app=Flask(__name__,static_folder=str(ROOT/'static'))
GAMES={'pick3':3,'pick4':4,'pick5':5,'multimatch':6,'powerball':5}
LOCK=threading.Lock()
STATE={'last_attempt':None,'last_success':None,'errors':{},'sources':{'powerball':'NY Open Data','maryland':'Maryland Lottery official winning numbers'}}

def db():
 c=sqlite3.connect(DB,timeout=15);c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE IF NOT EXISTS draws (game TEXT NOT NULL, date TEXT NOT NULL, session TEXT NOT NULL DEFAULT \'\', numbers TEXT NOT NULL, bonus TEXT NOT NULL DEFAULT \'\', source TEXT NOT NULL, PRIMARY KEY(game,date,session))')
 return c

def save(rows):
 if not rows:return 0
 with LOCK:
  c=db()
  c.executemany('INSERT INTO draws(game,date,session,numbers,bonus,source) VALUES(?,?,?,?,?,?) ON CONFLICT(game,date,session) DO UPDATE SET numbers=excluded.numbers,bonus=excluded.bonus,source=excluded.source',rows)
  c.commit();c.close()
 return len(rows)

def parse_md(html):
 """Parse HTML tables by headings; reject incomplete rows rather than inventing results."""
 soup=BeautifulSoup(html,'html.parser'); out=[]
 # Maryland's results are organized in game-specific tables.
 for table in soup.select('table'):
  heads=' '.join(x.get_text(' ',strip=True) for x in table.select('th')).lower()
  prior=[]
  for p in table.find_all_previous(['h2','h3','h4'],limit=3):prior.append(p.get_text(' ',strip=True).lower())
  context=' '.join(prior)
  game=None
  if 'pick 3' in heads and 'pick 4' in heads:game='picks'
  elif 'multi-match' in context or 'multi-match' in heads:game='multimatch'
  elif 'powerball' in context or 'powerball' in heads:continue
  if not game:continue
  for tr in table.select('tr'):
   cells=tr.find_all('td',recursive=False)
   if not cells:continue
   raw=[c.get_text(' ',strip=True) for c in cells]
   match=re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})',raw[0])
   if not match:continue
   m,d,y=map(int,match.groups());y+=2000 if y<100 else 0
   try: date=datetime(y,m,d).strftime('%Y-%m-%d')
   except ValueError:continue
   if game=='picks':
    session='Midday' if re.search('midday|\\bMID\\b',raw[0],re.I) else 'Evening' if re.search('evening|\\bEVE\\b',raw[0],re.I) else ''
    if not session:continue
    for i,n in enumerate([3,4,5],start=1):
     if i>=len(cells):continue
     txt=cells[i].get_text(' ',strip=True)
     # Maryland renders individual digits as separate list elements.
     digits=[x.get_text(' ',strip=True) for x in cells[i].select('li')]
     if len(digits)!=n:digits=re.findall(r'\d',txt)
     if len(digits)==n and all(re.fullmatch('[0-9]',x) for x in digits):out.append((f'pick{n}',date,session,json.dumps(digits),'','Maryland Lottery'))
   else:
    txt=' '.join(raw[1:]);balls=[x.get_text(' ',strip=True) for x in tr.select('td li')]
    if len(balls)!=6:balls=re.findall(r'\b\d{1,2}\b',txt)
    if len(balls)==6 and all(x.isdigit() and 1<=int(x)<=43 for x in balls):out.append(('multimatch',date,'',json.dumps([str(int(x)) for x in balls]),'','Maryland Lottery'))
 return out

def sync_md():
 r=requests.get('https://www.mdlottery.com/player-tools/winning-numbers/',headers={'User-Agent':'Mozilla/5.0 LotteryTrackerPro/1.0'},timeout=25);r.raise_for_status()
 rows=parse_md(r.text)
 if not rows:raise ValueError('Could not read verified results from Maryland Lottery page; source layout may have changed')
 return save(rows)

def sync_powerball():
 year=datetime.now(timezone.utc).year
 # NY Open Data republishes Powerball results, typically after the draw.
 url='https://data.ny.gov/resource/d6yy-54nr.json'
 params={'$where':f"draw_date >= '{year-1}-01-01T00:00:00'",'$limit':1500,'$order':'draw_date DESC'}
 r=requests.get(url,params=params,timeout=25);r.raise_for_status();data=r.json();rows=[]
 for item in data:
  nums=str(item.get('winning_numbers','')).split()
  if len(nums)!=6 or not all(x.isdigit() for x in nums):continue
  date=str(item.get('draw_date',''))[:10]
  if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):continue
  rows.append(('powerball',date,'',json.dumps([str(int(x)) for x in nums[:5]]),str(int(nums[5])),'NY Open Data'))
 if not rows:raise ValueError('No valid Powerball records returned')
 return save(rows)

def refresh():
 STATE['last_attempt']=datetime.now(timezone.utc).isoformat();counts={};errors={}
 for name,fn in [('maryland',sync_md),('powerball',sync_powerball)]:
  try:counts[name]=fn()
  except Exception as e:errors[name]=str(e)
 STATE['errors']=errors
 if counts:STATE['last_success']=datetime.now(timezone.utc).isoformat()
 return {'imported':counts,'errors':errors,'last_attempt':STATE['last_attempt']}

@app.get('/')
def index():return send_from_directory(ROOT/'static','index.html')
@app.get('/api/draws')
def draws():
 game=request.args.get('game','pick3');year=request.args.get('year',str(datetime.now().year));session=request.args.get('session','all')
 if game not in GAMES:return jsonify(error='Unknown game'),400
 try:y=int(year)
 except ValueError:return jsonify(error='Invalid year'),400
 if not 1990<=y<=2100:return jsonify(error='Invalid year'),400
 c=db();sql='SELECT * FROM draws WHERE game=? AND date>=? AND date<?';args=[game,f'{y}-01-01',f'{y+1}-01-01']
 if session in ('Midday','Evening'):sql+=' AND session=?';args.append(session)
 sql+=' ORDER BY date DESC, session DESC';records=[dict(r) for r in c.execute(sql,args)];c.close()
 for r in records:r['numbers']=json.loads(r['numbers'])
 return jsonify({'draws':records,'game':game,'year':y,'status':STATE})
def analyze_prediction(game, target, session, method, lookback):
 from collections import Counter
 from datetime import date as date_type
 if game not in GAMES:raise ValueError('Unknown game')
 try: target_date=date_type.fromisoformat(target)
 except ValueError:raise ValueError('Invalid target date')
 if not 1990 <= target_date.year <= 2100:raise ValueError('Date out of range')
 if method not in ('balanced','hot','cold','same'):raise ValueError('Unknown analysis method')
 if session not in ('all','Midday','Evening'):raise ValueError('Unknown drawing session')
 if lookback not in (30,60,90,365,0):raise ValueError('Invalid lookback')
 c=db();sql='SELECT date,session,numbers,bonus FROM draws WHERE game=? AND date<?';args=[game,target]
 if session!='all' and game.startswith('pick'):sql+=' AND session=?';args.append(session)
 sql+=' ORDER BY date DESC,session DESC';rows=[dict(r) for r in c.execute(sql,args)];c.close()
 for r in rows:r['numbers']=json.loads(r['numbers'])
 if lookback: rows=[r for r in rows if (target_date-date_type.fromisoformat(r['date'])).days<=lookback]
 same=[r for r in rows if r['date'][5:]==target[5:]]
 is_pick=game.startswith('pick');count=GAMES[game];lo=0 if is_pick else 1;hi=9 if is_pick else (43 if game=='multimatch' else 69)
 def rank(data, position=None):
  freq=Counter();last={};
  for idx,r in enumerate(data):
   values=[int(x) for x in r['numbers']]
   if position is not None:values=[values[position]]
   for n in set(values):
    freq[n]+=1
    if n not in last:last[n]=idx
  universe=list(range(lo,hi+1))
  if method=='same' and same:freq=Counter();last={}
  if method=='same' and same:
   for idx,r in enumerate(same):
    values=[int(x) for x in r['numbers']]
    if position is not None:values=[values[position]]
    for n in set(values):
     freq[n]+=1
     if n not in last:last[n]=idx
  if method=='cold':return sorted(universe,key=lambda n:(freq[n],-(last.get(n,len(data))),n))
  return sorted(universe,key=lambda n:(-freq[n],last.get(n,len(data)),n))
 if is_pick: suggestion=[str(rank(rows,i)[0]) for i in range(count)] if rows else []
 else:suggestion=sorted([str(n) for n in rank(rows)[:count]],key=lambda n:int(n)) if rows else []
 bonus=''
 if game=='powerball' and rows:
  bfreq=Counter(int(r['bonus']) for r in rows if r['bonus'] and r['bonus'].isdigit())
  ballrange=range(1,27)
  bonus=str(sorted(ballrange,key=lambda n:(bfreq[n] if method=='cold' else -bfreq[n],n))[0])
 freq=Counter();last_seen={};
 for i,r in enumerate(rows):
  for n in set(map(int,r['numbers'])):
   freq[n]+=1
   if n not in last_seen:last_seen[n]=(r['date'],i)
 ranked=rank(rows)
 return {'game':game,'target_date':target,'session':session,'method':method,'lookback_days':lookback,'sample_draws':len(rows),'same_calendar_date_draws':len(same),'same_date_examples':[{'date':r['date'],'numbers':r['numbers'],'bonus':r['bonus']} for r in same[:15]],'suggestion':suggestion,'bonus':bonus,'rankings':[{'number':n,'appearances':freq[n],'last_seen':last_seen[n][0] if n in last_seen else None,'missed_draws':last_seen[n][1] if n in last_seen else len(rows)} for n in ranked[:15]],'notice':'Historical heuristic only. Lottery draws are random; these rankings do not improve the mathematical odds of winning. Results are limited to saved, pre-target draw records.'}

@app.get('/api/predict')
def predict():
 try:
  return jsonify(analyze_prediction(request.args.get('game','pick3'),request.args.get('date',datetime.now().date().isoformat()),request.args.get('session','all'),request.args.get('method','balanced'),int(request.args.get('lookback','0'))))
 except (ValueError,TypeError) as e:return jsonify(error=str(e)),400

@app.post('/api/refresh')
def do_refresh():return jsonify(refresh())
@app.get('/api/status')
def status():return jsonify(STATE)
@app.get('/api/export')
def export():
 c=db();rows=[dict(r) for r in c.execute('SELECT * FROM draws ORDER BY date DESC')];c.close();return jsonify(rows)

if __name__=='__main__':
 if os.environ.get('SYNC_ON_START','1')=='1':
  threading.Thread(target=refresh,daemon=True).start()
 app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
