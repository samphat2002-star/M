"""APEX AI TRADING Telegram alert worker. Paper/analysis only; never places orders."""
from __future__ import annotations
import json, logging, os, time
from pathlib import Path
from datetime import datetime, timezone
from io import BytesIO
import requests
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'state'
STATE.mkdir(exist_ok=True)
logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'), format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('apex')
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN','').strip()
TWELVE_KEY = os.getenv('TWELVEDATA_API_KEY','').strip()
POLL_SECONDS = max(30, int(os.getenv('POLL_SECONDS','60')))
CAPITAL = float(os.getenv('PAPER_CAPITAL_USD','10'))
RISK_PCT = float(os.getenv('RISK_PER_TRADE_PCT','0.25'))
BASE = f'https://api.telegram.org/bot{TOKEN}' if TOKEN else ''
HTTP = requests.Session()
HTTP.headers.update({'User-Agent':'APEX-AI-TRADING/1.0'})


def read_json(name, default):
    p=STATE/name
    try: return json.loads(p.read_text())
    except Exception: return default

def write_json(name, data):
    (STATE/name).write_text(json.dumps(data, ensure_ascii=False, indent=2))

def tg(method, data=None, files=None, timeout=30):
    if not TOKEN: raise RuntimeError('ยังไม่ได้ตั้ง TELEGRAM_BOT_TOKEN')
    r=HTTP.post(f'{BASE}/{method}', data=data or {}, files=files, timeout=timeout)
    r.raise_for_status(); payload=r.json()
    if not payload.get('ok'): raise RuntimeError(str(payload))
    return payload.get('result')

def send_text(chat_id, text):
    return tg('sendMessage', {'chat_id':chat_id,'text':text,'disable_web_page_preview':True})

def send_photo(chat_id, img, caption):
    img.seek(0)
    return tg('sendPhoto', {'chat_id':chat_id,'caption':caption[:1024]}, {'photo':('apex_chart.png',img,'image/png')})

def get_btc():
    r=HTTP.get('https://api.binance.com/api/v3/klines', params={'symbol':'BTCUSDT','interval':'5m','limit':120}, timeout=15)
    r.raise_for_status(); rows=r.json()
    df=pd.DataFrame(rows, columns=['t','o','h','l','c','v','ct','qv','n','tb','tq','ig'])
    df['time']=pd.to_datetime(df['t'],unit='ms',utc=True)
    for c in ['o','h','l','c','v']: df[c]=pd.to_numeric(df[c])
    return df[['time','o','h','l','c','v']], 'Binance Spot BTCUSDT'

def get_xau():
    if not TWELVE_KEY: raise RuntimeError('ยังไม่ได้ตั้ง TWELVEDATA_API_KEY สำหรับ XAU/USD')
    r=HTTP.get('https://api.twelvedata.com/time_series', params={'symbol':'XAU/USD','interval':'5min','outputsize':120,'apikey':TWELVE_KEY,'format':'JSON'}, timeout=20)
    r.raise_for_status(); data=r.json()
    if 'values' not in data: raise RuntimeError(data.get('message', str(data)[:200]))
    df=pd.DataFrame(data['values']).rename(columns={'datetime':'time'})
    df['time']=pd.to_datetime(df['time'],utc=True)
    for c in ['open','high','low','close']: df[c]=pd.to_numeric(df[c])
    df['volume']=pd.to_numeric(df.get('volume',0), errors='coerce').fillna(0)
    df=df.sort_values('time')
    return df.rename(columns={'open':'o','high':'h','low':'l','close':'c','volume':'v'})[['time','o','h','l','c','v']], 'Twelve Data XAU/USD'

def enrich(df):
    x=df.copy()
    x['ema9']=x.c.ewm(span=9,adjust=False).mean(); x['ema21']=x.c.ewm(span=21,adjust=False).mean()
    delta=x.c.diff(); gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    rs=gain/loss.replace(0, float('nan')); rsi=100-(100/(1+rs))
    # Handle one-way/flat series explicitly instead of dropping every row as NaN.
    rsi=rsi.where(loss.ne(0), gain.gt(0).map({True:100.0, False:50.0}))
    rsi=rsi.where(gain.ne(0) | loss.ne(0), 50.0)
    x['rsi']=rsi
    prev=x.c.shift(1); tr=pd.concat([x.h-x.l,(x.h-prev).abs(),(x.l-prev).abs()],axis=1).max(axis=1)
    x['atr']=tr.ewm(alpha=1/14,adjust=False).mean()
    return x.dropna().reset_index(drop=True)

def analyze(df, symbol, source):
    x=enrich(df)
    if len(x)<30: raise RuntimeError('ข้อมูลแท่งเทียนไม่เพียงพอ')
    z=x.iloc[-1]; prev=x.iloc[-2]
    # A deliberately conservative, transparent baseline; not a trained predictive model.
    bull = z.ema9 > z.ema21 and z.c > z.ema9 and z.rsi >= 52 and z.rsi <= 72
    bear = z.ema9 < z.ema21 and z.c < z.ema9 and z.rsi <= 48 and z.rsi >= 28
    direction='BUY' if bull else ('SELL' if bear else 'WAIT')
    score=50
    if (z.ema9-z.ema21)*(1 if bull else -1 if bear else 0)>0: score+=15
    if direction=='BUY' and z.rsi>55 or direction=='SELL' and z.rsi<45: score+=10
    if direction!='WAIT' and z.c>prev.h and direction=='BUY': score+=10
    if direction!='WAIT' and z.c<prev.l and direction=='SELL': score+=10
    score=min(score,85) if direction!='WAIT' else 50
    atr=float(z.atr); price=float(z.c)
    # Scenario levels for chart/review only; broker contract specs and execution costs are unknown.
    if direction=='BUY': entry=price; sl=price-1.5*atr; tps=[price+3*atr,price+4.5*atr,price+6*atr]
    elif direction=='SELL': entry=price; sl=price+1.5*atr; tps=[price-3*atr,price-4.5*atr,price-6*atr]
    else: entry=sl=None; tps=[]
    return {'symbol':symbol,'source':source,'direction':direction,'score':score,'price':price,'rsi':float(z.rsi),'ema9':float(z.ema9),'ema21':float(z.ema21),'atr':atr,'entry':entry,'sl':sl,'tps':tps,'time':z.time.isoformat(),'df':x}

def fmt(p, symbol):
    return f'{p:,.2f}' if symbol=='XAUUSD' else f'{p:,.2f}'

def make_chart(a):
    df=a['df'].tail(65).copy(); fig,ax=plt.subplots(figsize=(11,6),dpi=150)
    fig.patch.set_facecolor('#0b1220'); ax.set_facecolor('#0b1220')
    xs=range(len(df))
    for i,row in enumerate(df.itertuples()):
        up=row.c>=row.o; color='#27c18a' if up else '#ef6464'
        ax.vlines(i,row.l,row.h,color=color,linewidth=1)
        low=min(row.o,row.c); height=max(abs(row.c-row.o),a['price']*0.00003)
        ax.add_patch(Rectangle((i-0.28,low),0.56,height,facecolor=color,edgecolor=color,linewidth=.5))
    ax.plot(list(xs),df.ema9,color='#f6c85f',linewidth=1.2,label='EMA 9')
    ax.plot(list(xs),df.ema21,color='#65a9ff',linewidth=1.2,label='EMA 21')
    if a['direction']!='WAIT':
        p=a['price']; atr=a['atr']; sign=1 if a['direction']=='BUY' else -1
        ax.annotate('AI '+a['direction'],xy=(len(df)-1,p),xytext=(len(df)-12,p+sign*atr*2.3),color='white',fontsize=10,fontweight='bold',arrowprops={'arrowstyle':'-|>','lw':2,'color':'#27c18a' if sign>0 else '#ef6464'})
        for label,val,col in [('ENTRY',a['entry'],'#f6c85f'),('SL',a['sl'],'#ef6464'),('TP1',a['tps'][0],'#27c18a'),('TP2',a['tps'][1],'#27c18a'),('TP3',a['tps'][2],'#27c18a')]:
            ax.axhline(val,color=col,linestyle='--',linewidth=.8,alpha=.85); ax.text(len(df)-1,val,label,color=col,fontsize=7,ha='right',va='bottom')
        # Dotted path is an illustrative ATR-based scenario, not a guaranteed forecast.
        ax.annotate('',xy=(len(df)+5,p+sign*atr*2),xytext=(len(df)-1,p),arrowprops={'arrowstyle':'->','linestyle':':','lw':2,'color':'#27c18a' if sign>0 else '#ef6464'})
    ax.set_title(f"APEX AI · {a['symbol']} · {a['direction']} · 5m",color='white',loc='left',fontsize=13,pad=14)
    ax.grid(alpha=.15,color='white'); ax.tick_params(colors='#cbd5e1',labelsize=7)
    for s in ax.spines.values(): s.set_color('#334155')
    ax.set_xlim(-1,len(df)+7); ax.legend(facecolor='#172033',labelcolor='white',fontsize=7,loc='upper left')
    ax.set_ylabel('Price',color='#cbd5e1'); fig.tight_layout()
    b=BytesIO(); fig.savefig(b,format='png',facecolor=fig.get_facecolor(),bbox_inches='tight'); plt.close(fig); b.seek(0); return b

def report(a):
    trend='ขาขึ้น' if a['direction']=='BUY' else ('ขาลง' if a['direction']=='SELL' else 'ยังไม่ชัดเจน')
    lines=[f"APEX AI TRADING | {a['symbol']}",f"สัญญาณ: {a['direction']} | Timeframe: 5 นาที",f"แนวโน้ม: {trend}",f"ราคาล่าสุด: {fmt(a['price'],a['symbol'])}",f"RSI(14): {a['rsi']:.1f}",f"AI Setup Score: {a['score']}/100 (ไม่ใช่เปอร์เซ็นต์ชนะ)",f"แหล่งข้อมูล: {a['source']}",f"เวลาแท่งล่าสุด: {a['time']}"]
    if a['direction']!='WAIT':
        lines += [f"Entry อ้างอิง: {fmt(a['entry'],a['symbol'])}",f"Stop Loss: {fmt(a['sl'],a['symbol'])}",f"TP1 / TP2 / TP3: {' / '.join(fmt(v,a['symbol']) for v in a['tps'])}","Risk:Reward ตามระยะราคาโดยประมาณ TP1 1:2 / TP2 1:3 / TP3 1:4 (ก่อนต้นทุนการเทรด)"]
    lines += ["\nเหตุผล: ใช้ EMA 9/21, RSI(14), ATR และแท่งเทียนล่าสุดเป็นตัวกรองเบื้องต้น", "ข้อจำกัด: เป็นระบบกฎเชิงเทคนิคเวอร์ชันทดลอง ไม่ใช่ AI ที่ผ่านการฝึกหรือรับประกันทิศทาง", "ทุนอ้างอิง: $10 | Risk 0.25% = $0.025 ต่อครั้ง", "โหมดวิเคราะห์/Paper เท่านั้น — ไม่ส่งคำสั่งซื้อขายเงินจริง", "ต้องตรวจสอบ spread, slippage, lot ขั้นต่ำ และ contract specs ของโบรกเกอร์ก่อนเทรดจริง"]
    return '\n'.join(lines)

def get_analyses():
    out=[]
    for symbol, fn in [('BTCUSD',get_btc),('XAUUSD',get_xau)]:
        try:
            df,source=fn(); out.append(analyze(df,symbol,source))
        except Exception as e:
            log.warning('%s feed error: %s',symbol,e)
            out.append({'symbol':symbol,'direction':'ERROR','error':str(e)})
    return out

def publish(a, chat_ids, force=False):
    if a['direction'] in ('ERROR',):
        if force:
            for cid in chat_ids: send_text(cid,f"APEX {a['symbol']}: ยังวิเคราะห์ไม่ได้\n{a['error']}\nตรวจสอบ API key/แหล่งข้อมูล")
        return
    key=f"{a['symbol']}:{a['direction']}:{a['time']}"
    seen=read_json('sent.json',{})
    if not force and (a['direction']=='WAIT' or seen.get(a['symbol'])==key): return
    caption=report(a)
    img=make_chart(a)
    for cid in chat_ids:
        try: send_photo(cid,img,caption)
        except Exception as e: log.exception('Telegram send failed: %s',e)
    if a['direction']!='WAIT': seen[a['symbol']]=key; write_json('sent.json',seen)

def handle_updates(offset):
    updates=tg('getUpdates',{'timeout':20,'offset':offset,'allowed_updates':'["message"]'},timeout=25)
    chats=set(read_json('chats.json',[]))
    for u in updates:
        offset=max(offset,u['update_id']+1); m=u.get('message',{}); chat=m.get('chat',{}); cid=str(chat.get('id',''))
        if not cid: continue
        msg=(m.get('text') or '').strip().lower()
        if msg.startswith('/start'):
            chats.add(cid); write_json('chats.json',sorted(chats))
            send_text(cid,'เชื่อมต่อ APEX AI TRADING สำเร็จแล้ว ✅\nคำสั่ง: /scan ตรวจตลาดตอนนี้ · /status สถานะระบบ · /help วิธีใช้งาน\nระบบจะส่งภาพกราฟเมื่อพบสัญญาณ BUY/SELL ที่ผ่านตัวกรอง\nโหมด Paper เท่านั้น ไม่มีการส่งคำสั่งซื้อขายจริง')
        elif msg.startswith('/help'):
            send_text(cid,'/start ลงทะเบียนรับแจ้งเตือน\n/scan วิเคราะห์และส่งกราฟล่าสุด\n/status ตรวจสถานะ\nแจ้งเตือนอัตโนมัติจะส่งเมื่อมีสัญญาณใหม่ ไม่ส่งซ้ำทุกนาที')
        elif msg.startswith('/status'):
            send_text(cid,f'APEX worker ทำงานอยู่\nรอบตรวจตลาด: ทุก {POLL_SECONDS} วินาที\nBTC feed: Binance Spot BTCUSDT\nXAU feed: Twelve Data XAU/USD '+('พร้อมตั้งค่า' if TWELVE_KEY else 'ยังไม่ได้ตั้ง API key')+'\nโหมด: Analysis/Paper only')
        elif msg.startswith('/scan'):
            send_text(cid,'กำลังตรวจข้อมูลตลาดและสร้างกราฟ...')
            for a in get_analyses(): publish(a,[cid],force=True)
    return offset

def main():
    if not TOKEN: raise SystemExit('ตั้งค่า TELEGRAM_BOT_TOKEN ใน Environment ก่อนเริ่ม')
    log.info('APEX Telegram worker starting; poll=%ss',POLL_SECONDS)
    offset=0; last_scan=0
    while True:
        try: offset=handle_updates(offset)
        except Exception as e: log.warning('Telegram polling error: %s',e); time.sleep(5)
        if time.time()-last_scan>=POLL_SECONDS:
            chats=read_json('chats.json',[])
            if chats:
                for a in get_analyses():
                    if a['direction']!='ERROR': publish(a,chats)
            last_scan=time.time()

if __name__=='__main__': main()
