#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════════════════╗
║       VUCCIARO UNIVERSE - Sistema Telegram Offerte Amazon      ║
║          Bot Automatizzato 24/7 - Mix API Ottimizzato          ║
╚════════════════════════════════════════════════════════════════╝

Strategia API Keepa Ultra-Ottimizzata:
- 70% Lightning Deals API (1 token) - Offerte lampo real-time
- 30% Browsing Deals API (5 token) - Varietà categorie
- Copy con urgenza, scarcity e social proof
- Visual impattante con foto sempre in primo piano
"""

import os
import sys
import time
import json
import random
import logging
import sqlite3
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

# Telegram
try:
    from telegram import Bot, ParseMode
    from telegram.error import TelegramError
except ImportError:
    print("❌ Installa python-telegram-bot: pip install python-telegram-bot==13.15")
    sys.exit(1)

# Scheduling
try:
    import schedule
except ImportError:
    print("❌ Installa schedule: pip install schedule")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# 📋 CONFIGURAZIONE SISTEMA
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO'))
)
logger = logging.getLogger(__name__)

# Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
KEEPA_API_KEY = os.getenv('KEEPA_API_KEY')
AMAZON_TAG = os.getenv('AMAZON_TAG', 'vucciaro-21')

# Canali Telegram
CHANNELS = {
    'tech': os.getenv('TECH_CHANNEL_ID', '-1002956324651'),
    'moda': os.getenv('MODA_CHANNEL_ID', '-1003108272082')
}

# Configurazione pubblicazione
POST_INTERVAL_MINUTES = int(os.getenv('POST_INTERVAL_MINUTES', '20'))
START_HOUR = int(os.getenv('START_HOUR', '7'))
END_HOUR = int(os.getenv('END_HOUR', '23'))

# Mix API (70% Lightning, 30% Browsing)
LIGHTNING_PERCENTAGE = int(os.getenv('LIGHTNING_PERCENTAGE', '70'))

# Filtri prodotti (abbassati per test iniziali)
MIN_DISCOUNT = int(os.getenv('MIN_DISCOUNT', '15'))
MIN_RATING = float(os.getenv('MIN_RATING', '3.5'))
MIN_REVIEWS = int(os.getenv('MIN_REVIEWS', '10'))
MIN_PRICE = int(os.getenv('MIN_PRICE', '500'))  # 5€
MAX_PRICE = int(os.getenv('MAX_PRICE', '40000'))  # 400€

# Categorie Keepa
CATEGORY_MAP = {
    'tech': [412609031, 1497228031, 473257031, 425916031],
    'moda': [5515768031, 5515769031, 26039478031]
}

# ═══════════════════════════════════════════════════════════════
# 💾 DATABASE
# ═══════════════════════════════════════════════════════════════

def init_database():
    conn = sqlite3.connect('vucciaro.db')
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS posted_products (
            asin TEXT PRIMARY KEY,
            channel TEXT NOT NULL,
            posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            title TEXT,
            price INTEGER,
            discount INTEGER
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS keepa_cache (
            cache_key TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_posted_at ON posted_products(posted_at)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_cached_at ON keepa_cache(cached_at)')
    
    conn.commit()
    conn.close()
    logger.info("✅ Database inizializzato")

def is_product_posted(asin: str, hours: int = 48) -> bool:
    conn = sqlite3.connect('vucciaro.db')
    c = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=hours)
    
    c.execute(
        'SELECT 1 FROM posted_products WHERE asin = ? AND posted_at > ?',
        (asin, cutoff)
    )
    exists = c.fetchone() is not None
    conn.close()
    return exists

def mark_as_posted(asin: str, channel: str, title: str, price: int, discount: int):
    conn = sqlite3.connect('vucciaro.db')
    c = conn.cursor()
    c.execute(
        'INSERT OR REPLACE INTO posted_products (asin, channel, title, price, discount) VALUES (?, ?, ?, ?, ?)',
        (asin, channel, title, price, discount)
    )
    conn.commit()
    conn.close()

def get_cached_data(cache_key: str, max_age_hours: int = 1) -> Optional[List[Dict]]:
    conn = sqlite3.connect('vucciaro.db')
    c = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    
    c.execute(
        'SELECT data FROM keepa_cache WHERE cache_key = ? AND cached_at > ?',
        (cache_key, cutoff)
    )
    row = c.fetchone()
    conn.close()
    
    if row:
        logger.info(f"✅ Cache hit: {cache_key}")
        return json.loads(row[0])
    return None

def cache_data(cache_key: str, data: List[Dict]):
    conn = sqlite3.connect('vucciaro.db')
    c = conn.cursor()
    c.execute(
        'INSERT OR REPLACE INTO keepa_cache (cache_key, data, cached_at) VALUES (?, ?, ?)',
        (cache_key, json.dumps(data), datetime.now())
    )
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════════════
# 🔌 KEEPA API CLIENT - MIX OTTIMIZZATO
# ═══════════════════════════════════════════════════════════════

class KeepaClient:
    """Client con mix Lightning Deals (70%) + Browsing Deals (30%)"""
    
    BASE_URL = "https://api.keepa.com"
    DOMAIN_IT = 8
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.token_count = 0
        self.call_counter = 0  # Per decidere quale API usare
    
    def fetch_lightning_deals(self) -> List[Dict]:
        """Lightning Deals - 1 token, offerte lampo real-time"""
        
        url = f"{self.BASE_URL}/lightningdeal"
        params = {
            "key": self.api_key,
            "domainId": self.DOMAIN_IT
        }
        
        try:
            logger.info("⚡ Keepa API: Lightning Deals (1 token)")
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            self.token_count += data.get('tokensConsumed', 1)
            
            deals = data.get('lightningDeals', [])
            logger.info(f"✅ Ricevuti {len(deals)} lightning deals (Token usati: {self.token_count})")
            
            return self._parse_lightning_deals(deals)
            
        except Exception as e:
            logger.error(f"❌ Errore Lightning Deals API: {e}")
            return []
    
    def fetch_browsing_deals(self, category_ids: List[int]) -> List[Dict]:
        """Browsing Deals - 5 token, varietà categorie"""
        
        query = {
            "page": 0,
            "domainId": self.DOMAIN_IT,
            "includeCategories": category_ids,
            "excludeCategories": [],
            "priceTypes": [0],
            "deltaPercentRange": [MIN_DISCOUNT, 100],
            "currentRange": [MIN_PRICE, MAX_PRICE],
            "minRating": int(MIN_RATING * 10),
            "hasReviews": True,
            "isLowest90": True,
            "isOutOfStock": False,
            "filterErotic": True,
            "singleVariation": True,
            "sortType": 4,
            "dateRange": 1
        }
        
        url = f"{self.BASE_URL}/deal"
        params = {
            "key": self.api_key,
            "selection": json.dumps(query)
        }
        
        try:
            logger.info(f"🔍 Keepa API: Browsing Deals (5 token) - Categorie: {category_ids[:2]}")
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            self.token_count += data.get('tokensConsumed', 5)
            
            deals = data.get('deals', {}).get('dr', [])
            logger.info(f"✅ Ricevuti {len(deals)} browsing deals (Token usati: {self.token_count})")
            
            return self._parse_browsing_deals(deals)
            
        except Exception as e:
            logger.error(f"❌ Errore Browsing Deals API: {e}")
            return []
    
    def _parse_lightning_deals(self, raw_deals: List[Dict]) -> List[Dict]:
        """Parse Lightning Deals con info urgenza"""
        parsed = []
        now = int(time.time() * 1000)  # Milliseconds
        
        for deal in raw_deals:
            try:
                # Verifica deal attivo
                deal_state = deal.get('dealState', '')
                if deal_state not in ['AVAILABLE', 'WAITLIST']:
                    continue
                
                deal_price = deal.get('dealPrice', 0)
                current_price = deal.get('currentPrice', 0)
                
                if not deal_price or not current_price:
                    continue
                
                # Calcola sconto
                percent_off = deal.get('percentOff', 0)
                if percent_off < MIN_DISCOUNT:
                    continue
                
                # Rating e recensioni
                rating = deal.get('rating', 0) / 10.0 if deal.get('rating') else 0
                review_count = deal.get('totalReviews', 0)
                
                if rating < MIN_RATING or review_count < MIN_REVIEWS:
                    continue
                
                # Calcola urgenza
                end_time = deal.get('endTime', 0)
                hours_left = (end_time - now) / (1000 * 60 * 60) if end_time > now else 0
                percent_claimed = deal.get('percentClaimed', 0)
                
                parsed.append({
                    'asin': deal.get('asin'),
                    'title': deal.get('title', '').strip(),
                    'current_price': deal_price / 100,
                    'list_price': current_price / 100,
                    'discount_percent': int(percent_off),
                    'rating': round(rating, 1),
                    'review_count': review_count,
                    'image_url': deal.get('image'),
                    'is_lightning': True,
                    'hours_left': round(hours_left, 1),
                    'percent_claimed': percent_claimed,
                    'is_prime': deal.get('isPrimeEligible', False)
                })
                
            except Exception as e:
                logger.warning(f"⚠️ Errore parsing lightning deal: {e}")
                continue
        
        return parsed
    
    def _parse_browsing_deals(self, raw_deals: List[Dict]) -> List[Dict]:
        """Parse Browsing Deals standard"""
        parsed = []
        
        for deal in raw_deals:
            try:
                current_price = deal.get('current', [None, None])[0]
                list_price = deal.get('current', [None, None])[1]
                
                if not current_price or not list_price or list_price <= current_price:
                    continue
                
                discount_percent = int(((list_price - current_price) / list_price) * 100)
                
                if discount_percent < MIN_DISCOUNT:
                    continue
                
                rating = deal.get('rating', 0) / 10.0 if deal.get('rating') else 0
                review_count = deal.get('reviewCount', 0)
                
                if rating < MIN_RATING or review_count < MIN_REVIEWS:
                    continue
                
                parsed.append({
                    'asin': deal.get('asin'),
                    'title': deal.get('title', '').strip(),
                    'current_price': current_price / 100,
                    'list_price': list_price / 100,
                    'discount_percent': discount_percent,
                    'rating': round(rating, 1),
                    'review_count': review_count,
                    'image_url': f"https://images-na.ssl-images-amazon.com/images/I/{deal.get('imagesCSV', '').split(',')[0]}" if deal.get('imagesCSV') else None,
                    'is_lightning': False,
                    'hours_left': None,
                    'percent_claimed': None,
                    'is_prime': False
                })
                
            except Exception as e:
                logger.warning(f"⚠️ Errore parsing browsing deal: {e}")
                continue
        
        logger.info(f"📊 Parsing completato: {len(parsed)} prodotti validi")
        return parsed

# ═══════════════════════════════════════════════════════════════
# 📱 TELEGRAM PUBLISHER - COPY OTTIMIZZATO
# ═══════════════════════════════════════════════════════════════

class TelegramPublisher:
    """Publisher con copy ad alta conversione"""
    
    EMOJI_MAP = {
        'tech': '🖥️',
        'moda': '👗'
    }
    
    def __init__(self, bot_token: str):
        self.bot = Bot(token=bot_token)
        self.amazon_tag = AMAZON_TAG
    
    def create_amazon_link(self, asin: str) -> str:
        return f"https://www.amazon.it/dp/{asin}?tag={self.amazon_tag}"
    
    def format_message(self, product: Dict, channel_type: str) -> str:
        """
        Copy ottimizzato con:
        - Urgenza (per Lightning Deals)
        - Scarcity (% venduto)
        - Social proof (rating + recensioni)
        - Call to action forte
        """
        emoji = self.EMOJI_MAP.get(channel_type, '🔥')
        
        # Tronca titolo
        title = product['title']
        if len(title) > 75:
            title = title[:72] + '...'
        
        # Prezzi formattati
        old_price = f"{product['list_price']:.2f}".replace('.', ',')
        new_price = f"{product['current_price']:.2f}".replace('.', ',')
        
        # MESSAGGIO OTTIMIZZATO
        lines = []
        
        # Header con urgenza per Lightning Deals
        if product.get('is_lightning'):
            if product.get('hours_left') and product['hours_left'] < 6:
                lines.append(f"⚡ <b>OFFERTA LAMPO - SCADE TRA {int(product['hours_left'])}H!</b>")
            else:
                lines.append(f"⚡ <b>OFFERTA LAMPO ATTIVA!</b>")
        else:
            lines.append(f"🔥 <b>OFFERTA SPECIALE -{product['discount_percent']}%</b>")
        
        lines.append("")
        
        # Titolo prodotto in grassetto
        lines.append(f"<b>{title}</b>")
        lines.append("")
        
        # Prezzo prominente
        lines.append(f"💰 <s>{old_price}€</s> → <b>{new_price}€</b>")
        
        # Social proof
        stars = "⭐" * int(product['rating'])
        lines.append(f"{stars} {product['rating']}/5 ({product['review_count']} recensioni)")
        
        # Scarcity per Lightning Deals
        if product.get('is_lightning') and product.get('percent_claimed'):
            claimed = product['percent_claimed']
            if claimed > 50:
                lines.append(f"⚠️ <b>{claimed}% già venduto!</b>")
        
        # Badge Prime
        if product.get('is_prime'):
            lines.append("✅ Prime")
        
        lines.append("")
        
        # Call to action forte
        lines.append(f"👉 <a href=\"{self.create_amazon_link(product['asin'])}\"><b>APPROFITTA DELL'OFFERTA</b></a>")
        
        return "\n".join(lines)
    
    def send_deal(self, product: Dict, channel_type: str) -> bool:
        channel_id = CHANNELS.get(channel_type)
        if not channel_id:
            logger.error(f"❌ Canale {channel_type} non configurato")
            return False
        
        try:
            message = self.format_message(product, channel_type)
            
            # SEMPRE con foto (visual first!)
            if product.get('image_url'):
                self.bot.send_photo(
                    chat_id=channel_id,
                    photo=product['image_url'],
                    caption=message,
                    parse_mode=ParseMode.HTML
                )
            else:
                self.bot.send_message(
                    chat_id=channel_id,
                    text=message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False
                )
            
            logger.info(f"✅ Pubblicato su {channel_id}: {product['title'][:50]}")
            return True
            
        except TelegramError as e:
            logger.error(f"❌ Errore pubblicazione: {e}")
            return False
    
    def send_startup_message(self):
        """Messaggio di test all'avvio"""
        logger.info("📨 Invio messaggi startup...")
        
        for channel_type, channel_id in CHANNELS.items():
            try:
                emoji = self.EMOJI_MAP.get(channel_type, '🤖')
                message = f"{emoji} <b>BOT VUCCIARO ATTIVO</b>\n\n"
                message += f"✅ Sistema avviato con successo!\n"
                message += f"⚡ Mix ottimizzato: 70% Lightning + 30% Browsing\n"
                message += f"⏰ Post ogni {POST_INTERVAL_MINUTES} minuti ({START_HOUR}:00-{END_HOUR}:00)\n"
                message += f"🎯 Filtri: sconto ≥{MIN_DISCOUNT}%, rating ≥{MIN_RATING}"
                
                self.bot.send_message(
                    chat_id=channel_id,
                    text=message,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"✅ Startup inviato su {channel_type}")
            except Exception as e:
                logger.error(f"❌ Errore startup su {channel_type}: {e}")

# ═══════════════════════════════════════════════════════════════
# 🎯 SISTEMA PRINCIPALE
# ═══════════════════════════════════════════════════════════════

class VucciaroSystem:
    """Sistema con mix intelligente Lightning + Browsing"""
    
    def __init__(self):
        self.keepa = KeepaClient(KEEPA_API_KEY)
        self.telegram = TelegramPublisher(TELEGRAM_BOT_TOKEN)
        self.channel_rotation = list(CHANNELS.keys())
        random.shuffle(self.channel_rotation)
        self.current_channel_index = 0
        
    def get_next_channel(self) -> str:
        channel = self.channel_rotation[self.current_channel_index]
        self.current_channel_index = (self.current_channel_index + 1) % len(self.channel_rotation)
        return channel
    
    def fetch_deals_for_channel(self, channel: str) -> List[Dict]:
        """Mix 70% Lightning + 30% Browsing"""
        
        # Decide quale API usare
        use_lightning = random.randint(1, 100) <= LIGHTNING_PERCENTAGE
        
        if use_lightning:
            # Lightning Deals - 1 token
            cache_key = "lightning_deals"
            cached = get_cached_data(cache_key, max_age_hours=0.5)  # Cache 30 min
            
            if cached:
                return cached
            
            deals = self.keepa.fetch_lightning_deals()
            
            if deals:
                cache_data(cache_key, deals)
            
            return deals
        else:
            # Browsing Deals - 5 token
            category_ids = CATEGORY_MAP.get(channel, [])
            if not category_ids:
                return []
            
            cache_key = f"browsing_{channel}"
            cached = get_cached_data(cache_key, max_age_hours=2)  # Cache 2h
            
            if cached:
                return cached
            
            deals = self.keepa.fetch_browsing_deals(category_ids)
            
            if deals:
                cache_data(cache_key, deals)
            
            return deals
    
    def select_best_deal(self, deals: List[Dict]) -> Optional[Dict]:
        """Seleziona il deal migliore"""
        
        def score(deal):
            s = deal['discount_percent'] * 0.4
            s += deal['rating'] * 5
            s += min(deal['review_count'] / 10, 50)
            
            # Bonus per Lightning Deals
            if deal.get('is_lightning'):
                s += 20
                
                # Bonus urgenza
                if deal.get('hours_left') and deal['hours_left'] < 3:
                    s += 30
            
            return s
        
        deals_sorted = sorted(deals, key=score, reverse=True)
        
        # Trova primo non pubblicato
        for deal in deals_sorted:
            if not is_product_posted(deal['asin'], hours=48):
                return deal
        
        return None
    
    def publish_next_deal(self):
        """Pubblica prossimo deal"""
        
        now = datetime.now()
        if not (START_HOUR <= now.hour < END_HOUR):
            logger.info(f"⏸️ Fuori orario ({START_HOUR}-{END_HOUR})")
            return
        
        channel = self.get_next_channel()
        logger.info(f"🎯 Turno: {channel}")
        
        deals = self.fetch_deals_for_channel(channel)
        
        if not deals:
            logger.warning(f"⚠️ Nessun deal per {channel}")
            return
        
        deal = self.select_best_deal(deals)
        
        if not deal:
            logger.warning(f"⚠️ Tutti i deal già pubblicati")
            return
        
        # Pubblica
        if self.telegram.send_deal(deal, channel):
            mark_as_posted(
                deal['asin'],
                channel,
                deal['title'],
                int(deal['current_price'] * 100),
                deal['discount_percent']
            )
            
            deal_type = "⚡ Lightning" if deal.get('is_lightning') else "🔍 Browsing"
            logger.info(f"✅ Pubblicato {deal_type}: {deal['title'][:40]}")

# ═══════════════════════════════════════════════════════════════
# 🚀 MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    if not TELEGRAM_BOT_TOKEN or not KEEPA_API_KEY:
        logger.error("❌ Variabili mancanti!")
        sys.exit(1)
    
    logger.info("=" * 70)
    logger.info("🌌 VUCCIARO UNIVERSE - Sistema Mix Ottimizzato")
    logger.info("=" * 70)
    logger.info(f"📱 Canali: Tech + Moda")
    logger.info(f"⚡ Mix: {LIGHTNING_PERCENTAGE}% Lightning + {100-LIGHTNING_PERCENTAGE}% Browsing")
    logger.info(f"⏰ Post ogni {POST_INTERVAL_MINUTES}min ({START_HOUR}:00-{END_HOUR}:00)")
    logger.info(f"💰 Filtri: ≥{MIN_DISCOUNT}%, ≥{MIN_RATING}⭐, ≥{MIN_REVIEWS} rec.")
    logger.info("=" * 70)
    
    init_database()
    system = VucciaroSystem()
    
    # Messaggio startup
    system.telegram.send_startup_message()
    
    # Scheduler
    schedule.every(POST_INTERVAL_MINUTES).minutes.do(system.publish_next_deal)
    
    # Prima esecuzione
    logger.info("🚀 Prima pubblicazione...")
    system.publish_next_deal()
    
    # Loop
    logger.info("♻️ Bot attivo!")
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n⏹️ Bot arrestato")
            break
        except Exception as e:
            logger.error(f"❌ Errore: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
