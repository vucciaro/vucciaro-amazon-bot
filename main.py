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

logging.basicConfig(format=’%(asctime)s - %(levelname)s - %(message)s’, level=logging.INFO)
logger = logging.getLogger(**name**)

# Config

BOT_TOKEN = os.getenv(‘TELEGRAM_BOT_TOKEN’)
TECH_CH = os.getenv(‘TECH_CHANNEL_ID’)
MODA_CH = os.getenv(‘MODA_CHANNEL_ID’)
KEEPA_KEY = os.getenv(‘KEEPA_API_KEY’)
KEEPA_DOM = int(os.getenv(‘KEEPA_DOMAIN’, ‘8’))
AMZ_TAG = os.getenv(‘AMAZON_TAG’, ‘vucciaro-21’)
INTERVAL = int(os.getenv(‘POST_INTERVAL_MINUTES’, ‘30’))
START_H = int(os.getenv(‘START_HOUR’, ‘8’))
END_H = int(os.getenv(‘END_HOUR’, ‘22’))
MIN_DISC_T = int(os.getenv(‘MIN_DISCOUNT_TECH’, ‘15’))
MIN_DISC_M = int(os.getenv(‘MIN_DISCOUNT_MODA’, ‘20’))
MIN_RAT = float(os.getenv(‘MIN_RATING’, ‘4.0’))
MIN_REV = int(os.getenv(‘MIN_REVIEWS’, ‘20’))
TECH_CATS = os.getenv(‘TECH_CATEGORIES’, ‘412609031,1497228031,460002031,412603031’).split(’,’)
MODA_CATS = os.getenv(‘MODA_CATEGORIES’, ‘5515768031,5515769031,26039478031,12710833031’).split(’,’)

def init_db():
c = sqlite3.connect(‘deals.db’)
c.execute(‘CREATE TABLE IF NOT EXISTS posts (asin TEXT PRIMARY KEY, ch TEXT, at TIMESTAMP, t TEXT, p INT)’)
c.commit()
c.close()
logger.info(“✅ DB initialized”)

def is_posted(asin):
c = sqlite3.connect(‘deals.db’)
r = c.execute(‘SELECT asin FROM posts WHERE asin=? AND at>?’, (asin, datetime.now()-timedelta(hours=48))).fetchone()
c.close()
return r is not None

def mark(asin, ch, title, price):
c = sqlite3.connect(‘deals.db’)
c.execute(‘INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?)’, (asin, ch, datetime.now(), title, price))
c.commit()
c.close()

def get_products(cat, mind):
“”“Product Finder API - Keepa”””
url = f’https://api.keepa.com/product’

```
params = {
    'key': KEEPA_KEY,
    'domain': KEEPA_DOM,
    'selection': json.dumps({
        'lastOfferdeal': 1,
        'includeCategories': [int(cat)],
        'deltaPercent90_AMAZON_gte': mind,
        'current_RATING_gte': int(MIN_RAT * 10),
        'current_COUNT_REVIEWS_gte': MIN_REV,
        'current_AMAZON_lte': 50000,  # Max 500€
        'current_AMAZON_gte': 500,     # Min 5€
    }),
    'stats': 90,
    'history': 0
}

try:
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    products = data.get('products', [])
    logger.info(f"📦 Keepa: {len(products)} products from cat {cat}")
    return products
except Exception as e:
    logger.error(f"❌ Keepa error: {e}")
    return []
```

def parse(p):
try:
asin = p.get(‘asin’, ‘’)
title = p.get(‘title’, ‘’)

```
    # Prezzi (csv array)
    csv = p.get('csv', [])
    if not csv or len(csv) < 18:
        return None
    
    # csv[0] = Amazon price history
    prices = csv[0] if isinstance(csv[0], list) else []
    if not prices or len(prices) < 2:
        return None
    
    # Ultimo prezzo (in centesimi)
    cur = prices[-1]
    if cur == -1 or cur is None:
        return None
    
    # Calcola media 90gg per sconto
    recent_prices = [p for p in prices[-90:] if p != -1 and p is not None]
    if not recent_prices:
        return None
    
    avg = sum(recent_prices) / len(recent_prices)
    disc = int(((avg - cur) / avg) * 100) if avg > 0 else 0
    
    # Rating e recensioni (csv[16] e csv[17])
    rat = csv[16][-1] / 10 if len(csv) > 16 and csv[16] and csv[16][-1] != -1 else 0
    rev = csv[17][-1] if len(csv) > 17 and csv[17] and csv[17][-1] != -1 else 0
    
    if rat < MIN_RAT or rev < MIN_REV or disc < 10:
        return None
    
    # Immagine
    imgs = p.get('imagesCSV', '').split(',') if p.get('imagesCSV') else []
    img = f"https://images-na.ssl-images-amazon.com/images/I/{imgs[0]}" if imgs else None
    
    return {
        'asin': asin,
        'title': title,
        'cur': cur / 100,
        'orig': avg / 100,
        'disc': disc,
        'rat': rat,
        'rev': int(rev),
        'img': img,
        'url': f"https://www.amazon.it/dp/{asin}?tag={AMZ_TAG}",
        'light': False  # Product Finder non ha lightning deals
    }
except Exception as e:
    logger.error(f"Parse error: {e}")
    return None
```

def fmt(p, ch):
e = ‘🖥️’ if ch==‘tech’ else ‘👗’
de = ‘💎’ if p[‘disc’]>=50 else ‘🔥’ if p[‘disc’]>=30 else ‘💰’
b = []
if p[‘rev’]>1000: b.append(‘🏆 BEST’)
bg = ’ ‘.join(b)+’ ’ if b else ‘’
msg = f”{de} {bg}*-{p[‘disc’]}%*\n\n{e} *{p[‘title’][:80]}*\n\n💶 ~{p[‘orig’]:.2f}€~ → *{p[‘cur’]:.2f}€*\n\n⭐️ {p[‘rat’]:.1f}/5 ({p[‘rev’]:,} rec)\n\n[➡️ VAI ALL’OFFERTA]({p['url']})”
return msg

def send(bot, cid, p, ch):
try:
msg = fmt(p, ch)
if p[‘img’]:
bot.send_photo(cid, p[‘img’], caption=msg, parse_mode=‘Markdown’)
else:
bot.send_message(cid, msg, parse_mode=‘Markdown’)
return True
except Exception as e:
logger.error(f”❌ Send error: {e}”)
return False

def post(bot, cid, ch, cats, mind):
random.shuffle(cats)
attempts = 0
max_attempts = len(cats) * 2

```
for cat in cats:
    if attempts >= max_attempts:
        break
    attempts += 1
    
    logger.info(f"🔍 Searching cat {cat} (min {mind}%)")
    prods = get_products(cat, mind)
    
    if not prods:
        logger.warning(f"⚠️ No products in cat {cat}")
        continue
    
    valid = []
    for prod in prods:
        parsed = parse(prod)
        if parsed and not is_posted(parsed['asin']):
            valid.append(parsed)
    
    if not valid:
        logger.warning(f"⚠️ No valid products after filters")
        continue
    
    # Ordina per score
    valid.sort(key=lambda x: x['disc'] * min(x['rev'] / 100, 10), reverse=True)
    p = valid[0]
    
    if send(bot, cid, p, ch):
        mark(p['asin'], ch, p['title'], int(p['cur'] * 100))
        logger.info(f"✅ POSTED {ch}: {p['title'][:50]} (-{p['disc']}%)")
        return True
    else:
        continue

logger.error(f"❌ NO PRODUCTS FOUND for {ch} after {attempts} attempts")
return False
```

def main():
logger.info(“🚀 Starting Vucciaro Bot…”)
init_db()

```
try:
    bot = Bot(BOT_TOKEN)
    info = bot.get_me()
    logger.info(f"✅ Bot connected: @{info.username}")
except Exception as e:
    logger.error(f"❌ Bot connection error: {e}")
    return

last = None
logger.info(f"⏰ Posting every {INTERVAL}min from {START_H}:00 to {END_H}:00")

while True:
    try:
        h = datetime.now().hour
        
        if not (START_H <= h < END_H):
            logger.info(f"⏸️ Outside posting hours (now: {h}:00)")
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
        
        logger.info(f"⏳ Waiting {INTERVAL} minutes...")
        time.sleep(INTERVAL * 60)
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped manually")
        break
    except Exception as e:
        logger.error(f"❌ Main loop error: {e}")
        time.sleep(60)
```

if **name** == ‘**main**’:
main()
