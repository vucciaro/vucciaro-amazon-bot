#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vucciaro Universe Bot - Sistema Automatizzato Offerte Amazon
Mix API: Lightning Deals (60%) + Browsing Deals (30%) + Best Sellers (10%)
"""

import os
import sys
import time
import json
import random
import logging
import hashlib
import sqlite3
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

import schedule
from telegram import Bot, ParseMode
from telegram.error import TelegramError

# ═══════════════════════════════════════════════════════════════
# 🔧 CONFIGURAZIONE
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO'))
)
logger = logging.getLogger(__name__)

# Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TECH_CHANNEL_ID = os.getenv('TECH_CHANNEL_ID')
MODA_CHANNEL_ID = os.getenv('MODA_CHANNEL_ID')

KEEPA_API_KEY = os.getenv('KEEPA_API_KEY')
KEEPA_DOMAIN = int(os.getenv('KEEPA_DOMAIN', '8'))
AMAZON_TAG = os.getenv('AMAZON_TAG', 'vucciaro-21')

POST_INTERVAL = int(os.getenv('POST_INTERVAL_MINUTES', '40'))
START_HOUR = int(os.getenv('START_HOUR', '7'))
END_HOUR = int(os.getenv('END_HOUR', '23'))

# Filtri Tech
TECH_MIN_DISCOUNT = int(os.getenv('TECH_MIN_DISCOUNT', '15'))
TECH_MIN_RATING = int(os.getenv('TECH_MIN_RATING', '40'))
TECH_MIN_REVIEWS = int(os.getenv('TECH_MIN_REVIEWS', '20'))
TECH_MAX_PRICE = int(os.getenv('TECH_MAX_PRICE', '50000'))
TECH_CATEGORIES = [int(c.strip()) for c in os.getenv('TECH_CATEGORIES', '').split(',') if c.strip()]

# Filtri Moda
MODA_MIN_DISCOUNT = int(os.getenv('MODA_MIN_DISCOUNT', '20'))
MODA_MIN_RATING = int(os.getenv('MODA_MIN_RATING', '40'))
MODA_MIN_REVIEWS = int(os.getenv('MODA_MIN_REVIEWS', '15'))
MODA_MAX_PRICE = int(os.getenv('MODA_MAX_PRICE', '30000'))
MODA_CATEGORIES = [int(c.strip()) for c in os.getenv('MODA_CATEGORIES', '').split(',') if c.strip()]

# Strategia API Mix
USE_LIGHTNING = os.getenv('USE_LIGHTNING_DEALS', 'true').lower() == 'true'
USE_BROWSING = os.getenv('USE_BROWSING_DEALS', 'true').lower() == 'true'
USE_BESTSELLERS = os.getenv('USE_BEST_SELLERS', 'true').lower() == 'true'

LIGHTNING_RATIO = float(os.getenv('LIGHTNING_DEALS_RATIO', '0.6'))
BROWSING_RATIO = float(os.getenv('BROWSING_DEALS_RATIO', '0.3'))
BESTSELLERS_RATIO = float(os.getenv('BEST_SELLERS_RATIO', '0.1'))

# Database
DATABASE_FILE = os.getenv('DATABASE_FILE', 'deals.db')
DEDUP_DAYS = int(os.getenv('DEDUP_DAYS', '30'))

# Keepa API Base
KEEPA_API_BASE = "https://api.keepa.com"

# ═══════════════════════════════════════════════════════════════
# 🗄️ DATABASE
# ═══════════════════════════════════════════════════════════════

def init_database():
    """Inizializza database SQLite per deduplica"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS posted_products (
            asin TEXT PRIMARY KEY,
            channel TEXT NOT NULL,
            posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            title TEXT,
            price INTEGER,
            discount INTEGER
        )
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_posted_at 
        ON posted_products(posted_at)
    ''')
    
    conn.commit()
    conn.close()
    logger.info("✅ Database inizializzato")

def cleanup_old_products():
    """Rimuove prodotti più vecchi di DEDUP_DAYS"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cutoff_date = datetime.now() - timedelta(days=DEDUP_DAYS)
    cursor.execute(
        'DELETE FROM posted_products WHERE posted_at < ?',
        (cutoff_date,)
    )
    
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    if deleted > 0:
        logger.info(f"🗑️ Rimossi {deleted} prodotti vecchi")

def is_product_posted(asin: str, channel: str) -> bool:
    """Controlla se prodotto già pubblicato"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute(
        'SELECT 1 FROM posted_products WHERE asin = ? AND channel = ?',
        (asin, channel)
    )
    
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def mark_product_posted(asin: str, channel: str, title: str, price: int, discount: int):
    """Marca prodotto come pubblicato"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO posted_products (asin, channel, title, price, discount)
        VALUES (?, ?, ?, ?, ?)
    ''', (asin, channel, title, price, discount))
    
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════════════
# 🔌 KEEPA API CLIENT
# ═══════════════════════════════════════════════════════════════

class KeepaClient:
    """Client per Keepa API con strategia multi-endpoint"""
    
    def __init__(self):
        self.api_key = KEEPA_API_KEY
        self.domain = KEEPA_DOMAIN
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'VucciaroBot/1.0',
            'Accept': 'application/json'
        })
    
    def _call_api(self, endpoint: str, params: Dict) -> Optional[Dict]:
        """Chiamata API generica"""
        params['key'] = self.api_key
        params['domain'] = self.domain
        
        url = f"{KEEPA_API_BASE}/{endpoint}"
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Keepa API error ({endpoint}): {e}")
            return None
    
    def get_lightning_deals(self, state: str = 'AVAILABLE') -> List[Dict]:
        """Recupera Lightning Deals attivi"""
        data = self._call_api('deal', {'state': state})
        
        if not data or 'deals' not in data:
            return []
        
        deals = data['deals'].get('dr', [])
        logger.info(f"⚡ Lightning Deals trovati: {len(deals)}")
        return deals
    
    def get_browsing_deals(self, categories: List[int], filters: Dict) -> List[Dict]:
        """Recupera deals da Browsing Deals API"""
        query = {
            'page': 0,
            'domainId': self.domain,
            'includeCategories': categories,
            'deltaPercentRange': [filters['min_discount'], 100],
            'currentRange': [500, filters['max_price']],
            'minRating': filters['min_rating'],
            'filterErotic': True,
            'singleVariation': True,
            'sortType': 4,
            'dateRange': 1
        }
        
        data = self._call_api('deal', {'dealQuery': json.dumps(query)})
        
        if not data or 'dr' not in data:
            return []
        
        deals = data['dr']
        logger.info(f"🔍 Browsing Deals trovati: {len(deals)}")
        return deals
    
    def get_best_sellers(self, category: int) -> List[str]:
        """Recupera Best Sellers per categoria"""
        data = self._call_api('bestsellers', {'category': category})
        
        if not data or 'bestSellersList' not in data:
            return []
        
        asins = data['bestSellersList'].get('asinList', [])
        logger.info(f"🏆 Best Sellers trovati: {len(asins)}")
        return asins[:20]  # Primi 20
    
    def get_product_details(self, asin: str) -> Optional[Dict]:
        """Recupera dettagli prodotto"""
        data = self._call_api('product', {'asin': asin, 'stats': 1})
        
        if not data or 'products' not in data or not data['products']:
            return None
        
        return data['products'][0]

# ═══════════════════════════════════════════════════════════════
# 📦 PRODUCT PROCESSOR
# ═══════════════════════════════════════════════════════════════

class ProductProcessor:
    """Processa e valida prodotti"""
    
    @staticmethod
    def extract_from_lightning_deal(deal: Dict) -> Optional[Dict]:
        """Estrae info da Lightning Deal"""
        try:
            return {
                'asin': deal.get('asin'),
                'title': deal.get('title', 'Prodotto in offerta'),
                'image': deal.get('image'),
                'current_price': deal.get('dealPrice', 0),
                'original_price': deal.get('currentPrice', 0),
                'rating': deal.get('rating', 0),
                'reviews': deal.get('totalReviews', 0),
                'discount': deal.get('percentOff', 0),
                'is_lightning': True,
                'end_time': deal.get('endTime')
            }
        except Exception as e:
            logger.error(f"❌ Error parsing lightning deal: {e}")
            return None
    
    @staticmethod
    def extract_from_product(product: Dict) -> Optional[Dict]:
        """Estrae info da Product Object"""
        try:
            stats = product.get('stats', {})
            current = stats.get('current', [])
            
            if not current or len(current) < 1:
                return None
            
            current_price = current[0] if current[0] != -1 else None
            
            # Calcola sconto se possibile
            csv = product.get('csv', [])
            discount = 0
            original_price = current_price
            
            if csv and len(csv) > 0:
                # csv[0] = AMAZON price history
                amazon_history = csv[0]
                if amazon_history:
                    # Trova prezzo più alto recente
                    max_price = max([p for p in amazon_history if p > 0], default=current_price)
                    if max_price and current_price and max_price > current_price:
                        discount = int(((max_price - current_price) / max_price) * 100)
                        original_price = max_price
            
            return {
                'asin': product.get('asin'),
                'title': product.get('title', 'Prodotto'),
                'image': product.get('imagesCSV', '').split(',')[0] if product.get('imagesCSV') else None,
                'current_price': current_price,
                'original_price': original_price,
                'rating': product.get('rating', 0) if 'rating' in product else stats.get('current', [])[16] if len(stats.get('current', [])) > 16 else 0,
                'reviews': product.get('reviewCount', 0),
                'discount': discount,
                'is_lightning': False
            }
        except Exception as e:
            logger.error(f"❌ Error parsing product: {e}")
            return None
    
    @staticmethod
    def validate_product(product: Dict, filters: Dict) -> bool:
        """Valida prodotto contro filtri"""
        try:
            # Prezzo valido
            if not product['current_price'] or product['current_price'] <= 0:
                return False
            
            # Entro range prezzo
            if product['current_price'] > filters['max_price']:
                return False
            
            # Sconto minimo (eccetto lightning deals urgenti)
            if not product.get('is_lightning', False):
                if product['discount'] < filters['min_discount']:
                    return False
            
            # Rating minimo
            if product['rating'] < filters['min_rating']:
                return False
            
            # Recensioni minime
            if product['reviews'] < filters['min_reviews']:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Validation error: {e}")
            return False

# ═══════════════════════════════════════════════════════════════
# 📱 TELEGRAM SENDER
# ═══════════════════════════════════════════════════════════════

class TelegramSender:
    """Gestisce invio messaggi Telegram"""
    
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    def format_message(self, product: Dict) -> str:
        """Formatta messaggio Telegram"""
        # Emoji basato su sconto
        if product['discount'] >= 50:
            emoji = "🔥"
        elif product['discount'] >= 30:
            emoji = "⚡"
        else:
            emoji = "💰"
        
        # Prezzo formattato
        current = f"€{product['current_price']/100:.2f}"
        original = f"€{product['original_price']/100:.2f}" if product['original_price'] != product['current_price'] else None
        
        # Rating
        rating_stars = "⭐" * (product['rating'] // 10)
        rating_text = f"{product['rating']/10:.1f}/5"
        
        # Link Amazon
        link = f"https://www.amazon.it/dp/{product['asin']}?tag={AMAZON_TAG}"
        
        # Titolo troncato
        title = product['title'][:80] + "..." if len(product['title']) > 80 else product['title']
        
        # Lightning deal badge
        lightning_badge = " ⚡ OFFERTA LAMPO" if product.get('is_lightning') else ""
        
        # Costruisci messaggio
        parts = [
            f"{emoji} <b>-{product['discount']}%</b>{lightning_badge}\n",
            f"{title}\n"
        ]
        
        if original:
            parts.append(f"💵 <s>{original}</s> → <b>{current}</b>\n")
        else:
            parts.append(f"💵 <b>{current}</b>\n")
        
        parts.append(f"{rating_stars} {rating_text} ({product['reviews']} recensioni)\n")
        parts.append(f"\n👉 <a href='{link}'>VAI ALL'OFFERTA</a>")
        
        return "".join(parts)
    
    def send_to_channel(self, channel_id: str, product: Dict) -> bool:
        """Invia prodotto a canale"""
        try:
            message = self.format_message(product)
            
            self.bot.send_message(
                chat_id=channel_id,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False
            )
            
            logger.info(f"✅ Pubblicato su {channel_id}: {product['asin']}")
            return True
            
        except TelegramError as e:
            logger.error(f"❌ Telegram error: {e}")
            return False

# ═══════════════════════════════════════════════════════════════
# 🎯 ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════

class VucciaroOrchestrator:
    """Orchestratore principale"""
    
    def __init__(self):
        self.keepa = KeepaClient()
        self.processor = ProductProcessor()
        self.sender = TelegramSender()
        self.post_counter = {'tech': 0, 'moda': 0}
        
    def select_api_strategy(self) -> str:
        """Seleziona API da usare basato su ratio"""
        rand = random.random()
        
        if rand < LIGHTNING_RATIO and USE_LIGHTNING:
            return 'lightning'
        elif rand < (LIGHTNING_RATIO + BROWSING_RATIO) and USE_BROWSING:
            return 'browsing'
        elif USE_BESTSELLERS:
            return 'bestsellers'
        else:
            return 'browsing'  # fallback
    
    def fetch_products(self, channel_type: str) -> List[Dict]:
        """Recupera prodotti per canale"""
        strategy = self.select_api_strategy()
        
        if channel_type == 'tech':
            categories = TECH_CATEGORIES
            filters = {
                'min_discount': TECH_MIN_DISCOUNT,
                'min_rating': TECH_MIN_RATING,
                'min_reviews': TECH_MIN_REVIEWS,
                'max_price': TECH_MAX_PRICE
            }
        else:  # moda
            categories = MODA_CATEGORIES
            filters = {
                'min_discount': MODA_MIN_DISCOUNT,
                'min_rating': MODA_MIN_RATING,
                'min_reviews': MODA_MIN_REVIEWS,
                'max_price': MODA_MAX_PRICE
            }
        
        logger.info(f"🎲 Strategia selezionata per {channel_type}: {strategy}")
        
        products = []
        
        if strategy == 'lightning':
            deals = self.keepa.get_lightning_deals()
            products = [self.processor.extract_from_lightning_deal(d) for d in deals]
            
        elif strategy == 'browsing':
            deals = self.keepa.get_browsing_deals(categories, filters)
            # Browsing deals returns product ASINs, need to fetch details
            for deal in deals[:10]:  # Limit to 10
                if 'asin' in deal:
                    product_data = self.keepa.get_product_details(deal['asin'])
                    if product_data:
                        products.append(self.processor.extract_from_product(product_data))
                        
        elif strategy == 'bestsellers':
            # Prendi categoria random
            category = random.choice(categories)
            asins = self.keepa.get_best_sellers(category)
            for asin in asins[:5]:  # Limit to 5
                product_data = self.keepa.get_product_details(asin)
                if product_data:
                    products.append(self.processor.extract_from_product(product_data))
        
        # Filtra None
        products = [p for p in products if p is not None]
        
        # Valida e filtra
        valid_products = [
            p for p in products 
            if self.processor.validate_product(p, filters)
        ]
        
        logger.info(f"📦 Prodotti validi per {channel_type}: {len(valid_products)}")
        return valid_products
    
    def post_to_channel(self, channel_type: str):
        """Pubblica su canale specifico"""
        logger.info(f"\n{'='*60}")
        logger.info(f"🚀 Inizio posting per {channel_type.upper()}")
        logger.info(f"{'='*60}")
        
        channel_id = TECH_CHANNEL_ID if channel_type == 'tech' else MODA_CHANNEL_ID
        
        # Fetch prodotti
        products = self.fetch_products(channel_type)
        
        if not products:
            logger.warning(f"⚠️ Nessun prodotto trovato per {channel_type}")
            return
        
        # Filtra già pubblicati
        new_products = [
            p for p in products
            if not is_product_posted(p['asin'], channel_id)
        ]
        
        if not new_products:
            logger.warning(f"⚠️ Tutti i prodotti già pubblicati per {channel_type}")
            return
        
        # Ordina per sconto
        new_products.sort(key=lambda x: x['discount'], reverse=True)
        
        # Prendi il migliore
        product = new_products[0]
        
        # Invia
        if self.sender.send_to_channel(channel_id, product):
            mark_product_posted(
                product['asin'],
                channel_id,
                product['title'],
                product['current_price'],
                product['discount']
            )
            self.post_counter[channel_type] += 1
            logger.info(f"✅ Post #{self.post_counter[channel_type]} completato per {channel_type}")

# ═══════════════════════════════════════════════════════════════
# 🕐 SCHEDULER
# ═══════════════════════════════════════════════════════════════

def is_posting_time() -> bool:
    """Verifica se è orario di posting"""
    now = datetime.now()
    return START_HOUR <= now.hour < END_HOUR

def run_tech_post():
    """Job per Tech"""
    if is_posting_time():
        orchestrator.post_to_channel('tech')
    else:
        logger.info("⏸️ Fuori orario posting - Tech saltato")

def run_moda_post():
    """Job per Moda"""
    if is_posting_time():
        orchestrator.post_to_channel('moda')
    else:
        logger.info("⏸️ Fuori orario posting - Moda saltato")

def run_cleanup():
    """Job pulizia database"""
    cleanup_old_products()

# ═══════════════════════════════════════════════════════════════
# 🚀 MAIN
# ═══════════════════════════════════════════════════════════════

orchestrator = None

def main():
    """Entry point"""
    global orchestrator
    
    logger.info("="*60)
    logger.info("🌌 VUCCIARO UNIVERSE BOT")
    logger.info("="*60)
    
    # Validazione config
    if not all([TELEGRAM_BOT_TOKEN, KEEPA_API_KEY, TECH_CHANNEL_ID, MODA_CHANNEL_ID]):
        logger.error("❌ Variabili ambiente mancanti!")
        sys.exit(1)
    
    # Init
    init_database()
    orchestrator = VucciaroOrchestrator()
    
    logger.info(f"\n📊 CONFIGURAZIONE:")
    logger.info(f"   Intervallo posting: {POST_INTERVAL} minuti")
    logger.info(f"   Orario: {START_HOUR}:00 - {END_HOUR}:00")
    logger.info(f"   Canali: Tech + Moda")
    logger.info(f"   Mix API: Lightning {LIGHTNING_RATIO*100:.0f}% | Browsing {BROWSING_RATIO*100:.0f}% | BestSellers {BESTSELLERS_RATIO*100:.0f}%")
    
    # Schedule jobs con offset per alternare
    schedule.every(POST_INTERVAL).minutes.do(run_tech_post)
    schedule.every(POST_INTERVAL).minutes.do(run_moda_post).tag('moda')
    
    # Offset Moda di 20 minuti
    schedule.get_jobs('moda')[0].next_run = datetime.now() + timedelta(minutes=20)
    
    # Cleanup giornaliero
    schedule.every().day.at("03:00").do(run_cleanup)
    
    logger.info(f"\n✅ Bot avviato! Post ogni {POST_INTERVAL} min (alternati)\n")
    
    # Main loop
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except KeyboardInterrupt:
            logger.info("\n👋 Bot fermato dall'utente")
            break
        except Exception as e:
            logger.error(f"❌ Errore critico: {e}")
            time.sleep(300)  # Aspetta 5 min prima di riprovare

if __name__ == "__main__":
    main()
