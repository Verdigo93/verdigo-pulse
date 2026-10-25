#!/usr/bin/env python3
"""Verdigo Pulse v1.4: real upcoming events, explicit source health, no fake data."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.parse import urlparse, parse_qs, urlencode, quote
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
import json, time, threading, os, re, hashlib, xml.etree.ElementTree as ET, email.utils, html

ROOT=Path(__file__).resolve().parent
PORT=int(os.environ.get('PORT','8790'))
CACHE={}; LOCK=threading.Lock()
LEAGUES={'4328':'Premier League','4335':'La Liga','4332':'Serie A','4331':'Bundesliga','4334':'Ligue 1','4480':'UEFA Champions League','4481':'UEFA Europa League'}

def get_json(url,timeout=10):
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; VerdigoPulse/1.1; event-calendar)','Accept':'application/json'})
    with urlopen(req,timeout=timeout) as r:
        return json.load(r)

def when_utc(date,timepart='00:00:00'):
    if not date:return None
    s=str(date).strip()
    try:
        if re.search(r'(Z|[+-]\d\d:\d\d)$',s):d=datetime.fromisoformat(s.replace('Z','+00:00'))
        elif 'T' in s:d=datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        else:d=datetime.fromisoformat(s+'T'+str(timepart or '00:00:00')[:8]).replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except (ValueError,TypeError):return None

def sports(league,name,start,end):
    # Public/free TheSportsDB endpoint; 1 future match per league on free tier.
    url='https://www.thesportsdb.com/api/v1/json/123/eventsnextleague.php?'+urlencode({'id':league})
    data=get_json(url)
    result=[]
    for e in (data.get('events') or []):
        d=when_utc(e.get('strTimestamp') or e.get('dateEvent'),e.get('strTime'))
        if not d or not start<=d<=end:continue
        home=e.get('strHomeTeam');away=e.get('strAwayTeam')
        if not home or not away:continue
        if e.get('intHomeScore') not in (None,'') or e.get('intAwayScore') not in (None,''):continue
        result.append({'id':'tsdb-'+str(e.get('idEvent')),'category':'football','title':f'{home} vs {away}',
                       'start':d.isoformat(),'datePrecision':'exact','source':'TheSportsDB','sourceType':'thirdPartySchedule',
                       'context':name,'url':'https://www.thesportsdb.com/event/'+str(e.get('idEvent')),
                       'home':home,'away':away,'resolutionType':'match',
                       'sourceNote':'Third-party schedule. Confirm kickoff and settlement source before publishing.'})
    return result

def formula_one(start,end):
    data=get_json(f'https://api.jolpi.ca/ergast/f1/{start.year}.json?limit=100')
    races=((data.get('MRData') or {}).get('RaceTable') or {}).get('Races') or []
    result=[]
    for r in races:
        d=when_utc(r.get('date'),r.get('time','00:00:00'))
        if not d or not start<=d<=end:continue
        name=r.get('raceName','Formula 1 Grand Prix')
        result.append({'id':'f1-'+str(r.get('round'))+'-'+str(start.year),'title':name,'category':'sports',
                       'start':d.isoformat(),'datePrecision':'exact','source':'Jolpica F1 calendar',
                       'sourceType':'thirdPartySchedule','context':'Formula 1','url':r.get('url','https://www.formula1.com/'),
                       'resolutionType':'other','sourceNote':'Race scheduled per F1 data feed; verify with official calendar.'})
    return result

def launches(start,end):
    # Launch Library 2: independent source; launches can slip and dates may be tentative.
    url='https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit=35&mode=detailed'
    data=get_json(url,timeout=12)
    result=[]
    for e in data.get('results',[]):
        d=when_utc(e.get('net'))
        if not d or not start<=d<=end:continue
        name=e.get('name') or 'Scheduled launch'
        result.append({'id':'launch-'+str(e.get('id')),'title':name,'category':'space','start':d.isoformat(),
                       'datePrecision':'tentative','source':'Launch Library 2','sourceType':'thirdPartySchedule',
                       'context':'Space launch', 'url':e.get('url') or 'https://nextspaceflight.com/launches/',
                       'resolutionType':'other','sourceNote':'NET (no earlier than) launch time; subject to change.'})
    return result


# Curated news discovery only. Headlines are NOT confirmed future events.
FEEDS={
'crypto':[
 ('CoinDesk','https://www.coindesk.com/arc/outboundfeeds/rss/'),('Decrypt','https://decrypt.co/feed'),
 ('Cointelegraph','https://cointelegraph.com/rss'),('Bitcoin Magazine','https://bitcoinmagazine.com/.rss/full/'),
 ('Ethereum Blog','https://blog.ethereum.org/feed.xml'),('Solana News','https://solana.com/news/rss.xml')],
'football': [('BBC Football','https://feeds.bbci.co.uk/sport/football/rss.xml'),('ESPN Soccer','https://www.espn.com/espn/rss/soccer/news')],
'sports': [('BBC Sport','https://feeds.bbci.co.uk/sport/rss.xml'),('ESPN','https://www.espn.com/espn/rss/news')],
'politics':[
 ('UN News','https://news.un.org/feed/subscribe/en/news/all/rss.xml'),('BBC World','https://feeds.bbci.co.uk/news/world/rss.xml'),
 ('European Parliament','https://www.europarl.europa.eu/rss/doc/agendas-plenary/en.xml'),
 ('European Commission','https://ec.europa.eu/commission/presscorner/api/rss?language=en'),
 ('Council of EU','https://www.consilium.europa.eu/en/press/press-releases/rss/')],
'finance': [('ECB','https://www.ecb.europa.eu/rss/press.html'),('IMF','https://www.imf.org/en/News/RSS'),('CNBC Economy','https://www.cnbc.com/id/20910258/device/rss/rss.html'),('Federal Reserve','https://www.federalreserve.gov/feeds/press_all.xml')],
'ai': [('OpenAI News','https://openai.com/news/rss.xml'),('Google AI','https://blog.google/technology/ai/rss/'),('Hugging Face','https://huggingface.co/blog/feed.xml'),('MIT Technology Review','https://www.technologyreview.com/feed/')],
'gaming': [('Xbox Wire','https://news.xbox.com/en-us/feed/'),('Nintendo Life','https://www.nintendolife.com/feeds/latest'),('PlayStation Blog','https://blog.playstation.com/feed/'),('IGN','https://feeds.ign.com/ign/all'),('Gematsu','https://www.gematsu.com/feed'),('PC Gamer','https://www.pcgamer.com/rss/')],
}


# Google News search RSS: forward-looking headlines and announced future actions.
# These remain RESEARCH LEADS, never confirmed scheduled events.
DISCOVERY_QUERIES={
 'crypto':['crypto token unlock upcoming October November 2026','blockchain upgrade mainnet launch scheduled upcoming','crypto airdrop listing launch date announced'],
 'politics':['upcoming parliament vote summit meeting next week','election debate scheduled October November 2026'],
 'gaming':['video game releases next week October November 2026','gaming showcase livestream announced release date 2026'],
 'ai':['AI conference keynote launch scheduled November 2026','artificial intelligence model product announcement upcoming'],
 'finance':['economic data release CPI interest rate decision next week','central bank rate announcement scheduled 2026'],
 'football':['football fixtures next week upcoming tournament 2026'],
 'sports':['upcoming sports finals races tournament October November 2026']
}
for _category,_queries in DISCOVERY_QUERIES.items():
    for _i,_q in enumerate(_queries,1):
        FEEDS.setdefault(_category,[]).append((f'Google News discovery {_i}', 'https://news.google.com/rss/search?'+urlencode({'q':_q,'hl':'en-US','gl':'US','ceid':'US:en'})))


def openliga(start,end):
    yr=start.year if start.month>=7 else start.year-1
    rows=get_json(f'https://api.openligadb.de/getmatchdata/bl1/{yr}',timeout=10)
    out=[]
    for e in rows if isinstance(rows,list) else []:
        d=when_utc(e.get('matchDateTimeUTC') or e.get('matchDateTime'))
        if not d or not start<=d<=end or e.get('matchIsFinished'):continue
        home=(e.get('team1') or {}).get('teamName');away=(e.get('team2') or {}).get('teamName')
        if not home or not away:continue
        ident=e.get('matchID')
        out.append({'id':'openliga-'+str(ident),'category':'football','title':home+' vs '+away,'start':d.isoformat(),'datePrecision':'exact','source':'OpenLigaDB','sourceType':'thirdPartySchedule','context':'Bundesliga','url':f'https://www.openligadb.de/','home':home,'away':away,'resolutionType':'match','sourceNote':'Independently maintained match schedule; confirm with Bundesliga official site.'})
    return out


# Verified institutional calendars (a news RSS publication date is never a future event).
class TableCells(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=None; self.cell=None
    def handle_starttag(self, tag, attrs):
        if tag=='tr': self.row=[]
        elif tag in ('td','th') and self.row is not None: self.cell=[]
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(' '.join(self.cell).split())); self.cell=None
        if tag=='tr' and self.row is not None:
            self.rows.append(self.row); self.row=None

def ecb_calendar(start,end):
    url='https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html'
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 VerdigoPulse/1.3','Accept':'text/html'})
    with urlopen(req,timeout=11) as resp: raw=resp.read(1500000).decode('utf-8','replace')
    parser=TableCells();parser.feed(raw)
    out=[];seen=set()
    for row in parser.rows:
        # ECB publishes dd/mm/yyyy in the first cell, sometimes with whitespace.
        date=next((re.search(r'\b(\d{2})/(\d{2})/(20\d{2})\b',v) for v in row if re.search(r'\b\d{2}/\d{2}/20\d{2}\b',v)),None)
        if not date:continue
        day,mon,year=map(int,date.groups());d=datetime(year,mon,day,12,tzinfo=timezone.utc)
        if not start.date()<=d.date()<=end.date():continue
        title=' '.join(x for x in row if not re.fullmatch(r'\s*\d{2}/\d{2}/20\d{2}\s*',x)).strip()
        if not title or 'meeting' not in title.lower() and 'press conference' not in title.lower():continue
        k=(d.date(),title)
        if k in seen:continue
        seen.add(k)
        out.append({'id':'ecb-'+hashlib.sha256((str(k)).encode()).hexdigest()[:14], 'title':title[:180], 'category':'finance','start':d.isoformat(),'datePrecision':'date', 'source':'European Central Bank','sourceType':'officialCalendar','context':'ECB · monetary policy','url':url,'resolutionType':'announcement', 'sourceNote':'Official ECB meeting calendar. Exact hour is not supplied; date only.'})
    if not parser.rows:raise ValueError('ECB calendar table not found')
    return out

def bls_calendar(start,end):
    url='https://www.bls.gov/schedule/news_release/bls.ics'
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 VerdigoPulse/1.3','Accept':'text/calendar'})
    with urlopen(req,timeout=11) as resp:raw=resp.read(1500000).decode('utf-8-sig','replace')
    if 'BEGIN:VCALENDAR' not in raw:raise ValueError('Invalid BLS calendar')
    # Join folded iCalendar property lines per RFC 5545.
    raw=re.sub(r'\r?\n[ \t]','',raw)
    out=[]
    for block in raw.split('BEGIN:VEVENT')[1:]:
        b=block.split('END:VEVENT')[0]
        sm=re.search(r'(?m)^SUMMARY[^:]*:(.+)$',b);dm=re.search(r'(?m)^DTSTART[^:]*:(\d{8})',b)
        if not sm or not dm:continue
        dateval=dm.group(1);d=datetime.strptime(dateval,'%Y%m%d').replace(hour=12,tzinfo=timezone.utc)
        if not start.date()<=d.date()<=end.date():continue
        title=sm.group(1).strip().replace('\\,',',').replace('\\;',';')
        out.append({'id':'bls-'+hashlib.sha256((title+dateval).encode()).hexdigest()[:14], 'title':title[:180],'category':'finance','start':d.isoformat(),'datePrecision':'date','source':'U.S. Bureau of Labor Statistics','sourceType':'officialCalendar','context':'US economic releases','url':'https://www.bls.gov/schedule/news_release/', 'resolutionType':'announcement','sourceNote':'Official BLS release date. Exact publication hour not represented.'})
    return out

def parse_feed(category,source,url,cutoff):
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 VerdigoPulse/1.2','Accept':'application/rss+xml, application/atom+xml, application/xml, text/xml'})
    with urlopen(req,timeout=7) as resp: raw=resp.read(1024*1024)
    root=ET.fromstring(raw)
    items=root.findall('.//item') or root.findall('{http://www.w3.org/2005/Atom}entry')
    results=[]
    def val(el,tag):
        z=el.find(tag)
        return (z.text or '').strip() if z is not None else ''
    for e in items[:35]:
        title=html.unescape(re.sub('<[^>]+>','',val(e,'title') or val(e,'{http://www.w3.org/2005/Atom}title'))).strip()
        link=val(e,'link')
        if not link:
            ln=e.find('{http://www.w3.org/2005/Atom}link');link=ln.get('href','') if ln is not None else ''
        pub=val(e,'pubDate') or val(e,'{http://www.w3.org/2005/Atom}published') or val(e,'{http://www.w3.org/2005/Atom}updated')
        try:
            dt=email.utils.parsedate_to_datetime(pub) if ',' in pub or 'GMT' in pub else datetime.fromisoformat(pub.replace('Z','+00:00'))
            if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
            dt=dt.astimezone(timezone.utc)
        except (ValueError,TypeError,IndexError):continue
        if dt<cutoff or dt>datetime.now(timezone.utc)+timedelta(hours=1) or not title or not link.startswith('http'):continue
        results.append({'id':'feed-'+hashlib.sha256(link.encode()).hexdigest()[:16], 'category':category,'title':title[:240], 'published':dt.isoformat(),'source':source,'url':link})
        if len(results)>=12:break
    return results

MONTHS={m.lower():i for i,m in enumerate(('January','February','March','April','May','June','July','August','September','October','November','December'),1)}
def date_mentioned(title,now):
    # An explicit future calendar date in the headline is a RESEARCH LEAD only,
    # never a verified upcoming event. Avoid invented dates and past-year ambiguity.
    pats=[r'\b('+ '|'.join(MONTHS) +r')\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?\b',
          r'\b(\d{1,2})\s+('+ '|'.join(MONTHS) +r')(?:\s+(20\d{2}))?\b']
    for idx,pat in enumerate(pats):
        for m in re.finditer(pat,title,re.I):
            month=int(MONTHS[(m.group(1) if idx==0 else m.group(2)).lower()]);day=int(m.group(2) if idx==0 else m.group(1));y=m.group(3)
            years=[int(y)] if y else [now.year,now.year+1]
            for yr in years:
                try:d=datetime(yr,month,day,tzinfo=timezone.utc)
                except ValueError:continue
                if now.date()<=d.date()<=(now+timedelta(days=30)).date():return d.isoformat()
    return None


def discovery():
    cutoff=datetime.now(timezone.utc)-timedelta(days=14)
    tasks=[(category,name,url) for category,feeds in FEEDS.items() for name,url in feeds]
    leads=[];statuses=[]
    with ThreadPoolExecutor(max_workers=16) as pool:
        fs=[(cat,name,pool.submit(parse_feed,cat,name,url,cutoff)) for cat,name,url in tasks]
        for cat,name,f in fs:
            try:
                rows=f.result(timeout=10);leads+=rows
                statuses.append({'name':name,'category':cat,'status':'ok','count':len(rows)})
            except Exception as exc:
                statuses.append({'name':name,'category':cat,'status':'error','reason':type(exc).__name__,'count':0})
    leads=sorted({x['id']:x for x in leads}.values(),key=lambda x:x['published'],reverse=True)
    now=datetime.now(timezone.utc)
    for item in leads:
        item['mentionedFutureDate']=date_mentioned(item['title'],now)
        item['candidateOnly']=bool(item['mentionedFutureDate'])
    return leads, statuses

def build(days):
    now=datetime.now(timezone.utc);end=now+timedelta(days=days)
    tasks=[('Football · '+name, sports,(lid,name,now,end)) for lid,name in LEAGUES.items()]
    tasks += [('OpenLigaDB Bundesliga',openliga,(now,end)),('Formula 1',formula_one,(now,end)),('Space launches',launches,(now,end)),('ECB official calendar',ecb_calendar,(now,end)),('US BLS official release calendar',bls_calendar,(now,end))]
    events=[];statuses=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[(name,pool.submit(fn,*args)) for name,fn,args in tasks]
        for name,f in futures:
            try:
                rows=f.result(timeout=17)
                events.extend(rows)
                statuses.append({'name':name,'status':'ok','count':len(rows)})
            except Exception as exc:
                statuses.append({'name':name,'status':'error','count':0,'reason':type(exc).__name__})
    unique={e['id']:e for e in events}
    records=sorted(unique.values(),key=lambda e:e['start'])
    return {'events':records,'generated':now.isoformat(),'days':days,'sourceStatuses':statuses,
            'sourcesOnline':sum(x['status']=='ok' for x in statuses),
            'sourcesFailed':sum(x['status']=='error' for x in statuses),
            'notice':'No news articles are treated as upcoming events. Events use dated schedules only.'}

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT),**kw)
    def do_GET(self):
        p=urlparse(self.path)
        if p.path not in ('/api/events','/api/leads'):return super().do_GET()
        if p.path=='/api/leads':
            force=parse_qs(p.query).get('refresh',['0'])[0]=='1'
            with LOCK:
                entry=CACHE.get('leads')
                data=entry['data'] if entry and entry['expires']>time.time() and not force else None
            if data is None:
                leads,status=discovery()
                data={'leads':leads,'sourceStatuses':status,'generated':datetime.now(timezone.utc).isoformat(),'candidateCount':sum(bool(x.get('candidateOnly')) for x in leads)}
                with LOCK:CACHE['leads']={'data':data,'expires':time.time()+900}
            payload=json.dumps(data,ensure_ascii=False).encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            return
        try:days=int(parse_qs(p.query).get('days',['7'])[0]);days=days if days in (1,7,30) else 7
        except ValueError:days=7
        force=parse_qs(p.query).get('refresh',['0'])[0]=='1'
        with LOCK:
            entry=CACHE.get(days)
            data=entry['data'] if entry and entry['expires']>time.time() and not force else None
        if data is None:
            data=build(days)
            with LOCK:CACHE[days]={'data':data,'expires':time.time()+360}
        payload=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(payload)))
        self.end_headers();self.wfile.write(payload)

if __name__=='__main__':
    print(f'VERDIGO PULSE v2.0: http://localhost:{PORT}',flush=True)
    print('Keep this window open. Press Ctrl+C to stop.',flush=True)
    ThreadingHTTPServer((os.environ.get('HOST', '0.0.0.0'),PORT),Handler).serve_forever()
