#!/usr/bin/env python3
import os
import time
import random
import logging
import requests
from datetime import datetime, timedelta
from telegram import Bot
from telegram.error import TelegramError
import sqlite3

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TECH_CH = os.getenv('TECH_CHANNEL_ID')
MODA_CH = os.getenv('MODA_CHANNEL_ID')
KEEPA_KEY = os.getenv('KEEPA_API_KEY')
KEEPA_DOM = int(os.getenv('KEEPA_DOMAIN', '8'))
AMZ_TAG = os.getenv('AMAZON_TAG', 'vucciaro-21')
INTERVAL = int(os.getenv('POST_INTERVAL_MINUTES', '30'))
START_H = int(os.getenv('START_HOUR', '8'))
END_H = int(os.getenv('END_HOUR', '22'))
MIN_DISC_T = int(os.getenv('MIN_DISCOUNT_TECH', '15'))
MIN_DISC_M = int(os.getenv('MIN_DISCOUNT_MODA', '20'))
MIN_RAT = float(os.getenv('MIN_RATING', '4.0'))
MIN_REV = int(os.getenv('MIN_REVIEWS', '20'))
TECH_CATS = os.getenv('TECH_CATEGORIES', '412609031,1497228031,460002031,412603031').split(',')
MODA_CATS = os.getenv('MODA_CATEGORIES', '5515768031,5515769031,26039478031,12710833031').split(',')

def init_db():
    c = sqlite3.connect('deals.db')
    c.execute('CREATE TABLE IF NOT EXISTS posts (asin TEXT PRIMARY KEY, ch TEXT, at TIMESTAMP, t TEXT, p INT)')
    c.commit()
    c.close()

def is_posted(asin):
    c = sqlite3.connect('deals.db')
    r = c.execute('SELECT asin FROM posts WHERE asin=? AND at>?', (asin, datetime.now()-timedelta(hours=48))).fetchone()
    c.close()
    return r is not None

def mark(asin, ch, title, price):
    c = sqlite3.connect('deals.db')
    c.execute('INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?)', (asin, ch, datetime.now(), title, price))
    c.commit()
    c.close()

def get_deals(cat, mind):
    try:
        r = requests.post('https://api.keepa.com/deal', json={
            'key': KEEPA_KEY, 'domain': KEEPA_DOM, 'category': cat, 'page': 0,
            'deltaPercentRange': [mind, 100], 'currentRange': [500, 500000],
            'minRating': int(MIN_RAT*10), 'sortType': 4, 'dateRange': 1,
            'hasReviews': True, 'singleVariation': True, 'filterErotic': True
        }, timeout=30)
        return r.json().get('deals', {}).get('dr', [])
    except:
        return []

def parse(p):
    try:
        asin = p.get('asin', '')
        title = p.get('title', '')
        cur = p.get('current', [None])[0]
        if not cur or cur == -1: return None
        avg = p.get('avg90', [None])[0] or cur*1.25
        disc = int(((avg-cur)/avg)*100) if avg>0 else 0
        csv = p.get('csv', [[]])[0]
        rat = csv[16]/10 if len(csv)>16 else 0
        rev = csv[17] if len(csv)>17 else 0
        if rat<MIN_RAT or rev<MIN_REV: return None
        imgs = p.get('imagesCSV', '').split(',')
        img = f"https://images-na.ssl-images-amazon.com/images/I/{imgs[0]}" if imgs else None
        return {
            'asin': asin, 'title': title, 'cur': cur/100, 'orig': avg/100,
            'disc': disc, 'rat': rat, 'rev': rev, 'img': img,
            'url': f"https://www.amazon.it/dp/{asin}?tag={AMZ_TAG}",
            'light': p.get('lightningDealInfo') is not None
        }
    except:
        return None
def fmt(p, ch):
    e = '🖥️' if ch=='tech' else '👗'
    de = '💎' if p['disc']>=50 else '🔥' if p['disc']>=30 else '💰'
    b = []
    if p['light']: b.append('⚡ LAMPO')
    if p['rev']>1000: b.append('🏆 BEST')
    bg = ' '.join(b)+' ' if b else ''
    msg = f"{de} {bg}*-{p['disc']}%*\n\n{e} *{p['title'][:80]}*\n\n💶 ~~{p['orig']:.2f}€~~ → *{p['cur']:.2f}€*\n\n⭐️ {p['rat']:.1f}/5 ({p['rev']:,} rec)\n\n[➡️ VAI ALL'OFFERTA]({p['url']})"
    if p['light']: msg += "\n\n⏰ _Offerta a tempo!_"
    return msg

def send(bot, cid, p, ch):
    try:
        msg = fmt(p, ch)
        if p['img']:
            bot.send_photo(cid, p['img'], caption=msg, parse_mode='Markdown')
        else:
            bot.send_message(cid, msg, parse_mode='Markdown')
        return True
    except Exception as e:
        logger.error(f"Send fail: {e}")
        return False

def post(bot, cid, ch, cats, mind):
    random.shuffle(cats)
    for cat in cats:
        prods = get_deals(cat, mind)
        if not prods: continue
        valid = [parse(p) for p in prods]
        valid = [p for p in valid if p and not is_posted(p['asin'])]
        if not valid: continue
        valid.sort(key=lambda x: x['disc']*min(x['rev']/100, 10), reverse=True)
        p = valid[0]
        if send(bot, cid, p, ch):
            mark(p['asin'], ch, p['title'], int(p['cur']*100))
            logger.info(f"✅ {ch}: {p['title'][:40]}")
            return True
    logger.warning(f"❌ No products: {ch}")
    return False

def main():
    logger.info("🚀 Starting...")
    init_db()
    bot = Bot(BOT_TOKEN)
    try:
        info = bot.get_me()
        logger.info(f"✅ Bot: @{info.username}")
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
        return
    
    last = None
    logger.info(f"⏰ Every {INTERVAL}min, {START_H}:00-{END_H}:00")
    
    while True:
        try:
            h = datetime.now().hour
            if not (START_H <= h < END_H):
                time.sleep(300)
                continue
            
            if last != 'tech':
                logger.info("📱 Posting TECH...")
                post(bot, TECH_CH, 'tech', TECH_CATS, MIN_DISC_T)
                last = 'tech'
            else:
                logger.info("👗 Posting MODA...")
                post(bot, MODA_CH, 'moda', MODA_CATS, MIN_DISC_M)
                last = 'moda'
            
            logger.info(f"⏳ Wait {INTERVAL}min...")
            time.sleep(INTERVAL * 60)
            
        except KeyboardInterrupt:
            logger.info("🛑 Stopped")
            break
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            time.sleep(60)

if __name__ == '__main__':
    main()
