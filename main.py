#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════════════════╗
║       VUCCIARO UNIVERSE - Sistema Telegram Offerte Amazon      ║
║              Bot Automatizzato 24/7 - 2 Canali                 ║
╚════════════════════════════════════════════════════════════════╝

Strategia API Keepa Ottimizzata:
- Browsing Deals API (5 token/request, max 150 deals)
- Filtri smart per categoria + sconto minimo
- Cache 6h per categoria (ottimizzazione token)
- Rotazione intelligente tra 2 canali: Tech e Moda
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
from dataclasses import dataclass

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

# Canali Telegram (SOLO 2 CANALI REALI)
CHANNELS = {
    'tech': os.getenv('TECH_CHANNEL_ID', '-1002956324651'),
    'moda': os.getenv('MODA_CHANNEL_ID', '-1003108272082')
}

# Configurazione pubblicazione
POST_INTERVAL_MINUTES = int(os.getenv('POST_INTERVAL_MINUTES', '20'))
START_HOUR = int(os.getenv('START_HOUR', '7'))
END_HOUR = int(os.getenv('END_HOUR', '23'))

# Filtri prodotti (abbassati per test iniziali)
MIN_DISCOUNT = int(os.getenv('MIN_DISCOUNT', '15'))
MIN_RATING = float(os.getenv('MIN_RATING', '3.5'))
MIN_REVIEWS = int(os.getenv('MIN_REVIEWS', '10'))
MIN_PRICE = int(os.getenv('MIN_PRICE', '500'))  # 5€ in centesimi
MAX_PRICE = int(os.getenv('MAX_PRICE', '40000'))  # 400€ in centesimi

# Categorie Keepa per canale (SOLO Tech e Moda)
CATEGORY_MAP = {
    'tech': [412609031, 1497228031, 473257031, 425916031],  # Elettronica, Cellulari, Accessori, Informatica
    'moda': [5515768031, 5515769031, 26039478031]  # Moda Donna, Moda Uomo, Abbigliamento Sport
}

# ═══════════════════════════════════════════════════════════════
# 💾 DATABASE - DEDUPLICA E CACHE
# ═══════════════════════════════════════════════════════════════

def init_database():
    """Inizializza SQLite per deduplica prodotti e cache"""
    conn = sqlite3.connect('vucciaro.db')
    c = conn.cursor()
    
    # Tabella prodotti pubblicati
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
    
    # Tabella cache Keepa (risparmio token)
    c.execute('''
        CREATE TABLE IF NOT EXISTS keepa_cache (
            category_id INTEGER PRIMARY KEY,
            channel TEXT NOT NULL,
            data TEXT NOT NULL,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Indici per performance
    c.execute('CREATE INDEX IF NOT EXISTS idx_posted_at ON posted_products(posted_at)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_cached_at ON keepa_cache(cached_at)')
    
    conn.commit()
    conn.close()
    logger.info("✅ Database inizializzato")

def is_product_posted(asin: str, hours: int = 48) -> bool:
    """Verifica se prodotto già pubblicato nelle ultime N ore"""
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
    """Registra prodotto come pubblicato"""
    conn = sqlite3.connect('vucciaro.db')
    c = conn.cursor()
    c.execute(
        'INSERT OR REPLACE INTO posted_products (asin, channel, title, price, discount) VALUES (?, ?, ?, ?, ?)',
        (asin, channel, title, price, discount)
    )
    conn.commit()
    conn.close()

def get_cached_deals(category_id: int, channel: str, max_age_hours: int = 6) -> Optional[List[Dict]]:
    """Recupera deals dalla cache se non scaduti"""
    conn = sqlite3.connect('vucciaro.db')
    c = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    
    c.execute(
        'SELECT data FROM keepa_cache WHERE category_id = ? AND channel = ? AND cached_at > ?',
        (category_id, channel, cutoff)
    )
    row = c.fetchone()
    conn.close()
    
    if row:
        logger.info(f"✅ Cache hit per categoria {category_id}")
        return json.loads(row[0])
    return None

def cache_deals(category_id: int, channel: str, deals: List[Dict]):
    """Salva deals in cache"""
    conn = sqlite3.connect('vucciaro.db')
    c = conn.cursor()
    c.execute(
        'INSERT OR REPLACE INTO keepa_cache (category_id, channel, data, cached_at) VALUES (?, ?, ?, ?)',
        (category_id, channel, json.dumps(deals), datetime.now())
    )
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════════════
# 🔌 KEEPA API CLIENT
# ═══════════════════════════════════════════════════════════════

class KeepaClient:
    """Client ottimizzato per Keepa API"""
    
    BASE_URL = "https://api.keepa.com"
    DOMAIN_IT = 8  # Amazon.it
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.token_count = 0
    
    def fetch_browsing_deals(self, category_ids: List[int], min_discount: int = 20) -> List[Dict]:
        """
        Fetch deals usando Browsing Deals API (5 token/request)
        Ritorna max 150 deals per categoria
        """
        query = {
            "page": 0,
            "domainId": self.DOMAIN_IT,
            "includeCategories": category_ids,
            "excludeCategories": [],
            "priceTypes": [0],  # Amazon price
            "deltaPercentRange": [min_discount, 100],  # Sconto minimo
            "currentRange": [MIN_PRICE, MAX_PRICE],  # Range prezzo
            "minRating": int(MIN_RATING * 10),  # Rating Amazon (4.0 = 40)
            "hasReviews": True,
            "isLowest": False,
            "isLowest90": True,  # Prezzo più basso negli ultimi 90gg
            "isOutOfStock": False,
            "filterErotic": True,
            "singleVariation": True,
            "sortType": 4,  # Sort by percent discount
            "dateRange": 1  # Last 12 hours
        }
        
        url = f"{self.BASE_URL}/deal"
        params = {
            "key": self.api_key,
            "selection": json.dumps(query)
        }
        
        try:
            logger.info(f"🔍 Keepa API: Browsing Deals (categorie: {category_ids})")
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            self.token_count += data.get('tokensConsumed', 5)
            
            deals = data.get('deals', {}).get('dr', [])
            logger.info(f"✅ Ricevuti {len(deals)} deals (Token usati: {self.token_count})")
            
            return self._parse_deals(deals)
            
        except Exception as e:
            logger.error(f"❌ Errore Keepa API: {e}")
            return []
    
    def _parse_deals(self, raw_deals: List[Dict]) -> List[Dict]:
        """Parse e normalizza deals da Keepa"""
        parsed = []
        skipped_reasons = {'no_price': 0, 'no_discount': 0, 'low_rating': 0, 'low_reviews': 0}
        
        for deal in raw_deals:
            try:
                # Calcola sconto
                current_price = deal.get('current', [None, None])[0]
                list_price = deal.get('current', [None, None])[1]
                
                if not current_price or not list_price or list_price <= current_price:
                    skipped_reasons['no_price'] += 1
                    continue
                
                discount_percent = int(((list_price - current_price) / list_price) * 100)
                
                if discount_percent < MIN_DISCOUNT:
                    skipped_reasons['no_discount'] += 1
                    continue
                
                # Converti rating (Amazon: 45 = 4.5 stelle)
                rating = deal.get('rating', 0) / 10.0 if deal.get('rating') else 0
                review_count = deal.get('reviewCount', 0)
                
                if rating < MIN_RATING:
                    skipped_reasons['low_rating'] += 1
                    continue
                    
                if review_count < MIN_REVIEWS:
                    skipped_reasons['low_reviews'] += 1
                    continue
                
                parsed.append({
                    'asin': deal.get('asin'),
                    'title': deal.get('title', '').strip(),
                    'current_price': current_price / 100,  # Converti in euro
                    'list_price': list_price / 100,
                    'discount_percent': discount_percent,
                    'rating': round(rating, 1),
                    'review_count': review_count,
                    'image_url': f"https://images-na.ssl-images-amazon.com/images/I/{deal.get('imagesCSV', '').split(',')[0]}" if deal.get('imagesCSV') else None,
                    'category_ids': deal.get('categoryIdHistory', [])
                })
                
            except Exception as e:
                logger.warning(f"⚠️ Errore parsing deal: {e}")
                continue
        
        # Log statistiche filtraggio
        logger.info(f"📊 Parsing completato: {len(parsed)} prodotti OK, scartati: {sum(skipped_reasons.values())}")
        logger.info(f"   - Nessun prezzo: {skipped_reasons['no_price']}")
        logger.info(f"   - Sconto basso: {skipped_reasons['no_discount']}")
        logger.info(f"   - Rating basso: {skipped_reasons['low_rating']}")
        logger.info(f"   - Poche recensioni: {skipped_reasons['low_reviews']}")
        
        return parsed

# ═══════════════════════════════════════════════════════════════
# 📱 TELEGRAM PUBLISHER
# ═══════════════════════════════════════════════════════════════

class TelegramPublisher:
    """Gestore pubblicazione messaggi Telegram"""
    
    EMOJI_MAP = {
        'tech': '🖥️',
        'moda': '👗'
    }
    
    def __init__(self, bot_token: str):
        self.bot = Bot(token=bot_token)
        self.amazon_tag = AMAZON_TAG
    
    def create_amazon_link(self, asin: str) -> str:
        """Crea link affiliato Amazon"""
        return f"https://www.amazon.it/dp/{asin}?tag={self.amazon_tag}"
    
    def format_message(self, product: Dict, channel_type: str) -> str:
        """
        Formatta messaggio Telegram con HTML
        Focus su: foto in primo piano, nome prodotto in grassetto, call-to-action chiara
        """
        emoji = self.EMOJI_MAP.get(channel_type, '🔥')
        
        # Tronca titolo se troppo lungo
        title = product['title']
        if len(title) > 80:
            title = title[:77] + '...'
        
        # Formatta prezzi
        old_price = f"{product['list_price']:.2f}".replace('.', ',')
        new_price = f"{product['current_price']:.2f}".replace('.', ',')
        
        # Template messaggio ottimizzato per visibilità
        message = f"{emoji} <b>OFFERTA: -{product['discount_percent']}%</b>\n\n"
        message += f"<b>{title}</b>\n\n"
        message += f"💰 <s>{old_price}€</s> → <b>{new_price}€</b>\n"
        message += f"⭐ {product['rating']}/5 ({product['review_count']} recensioni)\n\n"
        message += f"👉 <a href=\"{self.create_amazon_link(product['asin'])}\">VAI ALL'OFFERTA SU AMAZON</a>"
        
        return message
    
    def send_deal(self, product: Dict, channel_type: str) -> bool:
        """Pubblica deal su canale Telegram"""
        channel_id = CHANNELS.get(channel_type)
        if not channel_id:
            logger.error(f"❌ Canale {channel_type} non configurato")
            return False
        
        try:
            message = self.format_message(product, channel_type)
            
            # Invia con foto se disponibile
            if product.get('image_url'):
                self.bot.send_photo(
                    chat_id=channel_id,
                    photo=product['image_url'],
                    caption=message,
                    parse_mode=ParseMode.HTML
                )
            else:
                # Fallback senza foto
                self.bot.send_message(
                    chat_id=channel_id,
                    text=message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False
                )
            
            logger.info(f"✅ Pubblicato su {channel_id}: {product['title'][:50]}")
            return True
            
        except TelegramError as e:
            logger.error(f"❌ Errore pubblicazione Telegram: {e}")
            return False
    
    def send_startup_message(self):
        """Invia messaggio di test all'avvio su entrambi i canali"""
        logger.info("📨 Invio messaggi di startup...")
        
        for channel_type, channel_id in CHANNELS.items():
            try:
                emoji = self.EMOJI_MAP.get(channel_type, '🤖')
                message = f"{emoji} <b>BOT VUCCIARO ATTIVO</b>\n\n"
                message += f"✅ Sistema avviato con successo!\n"
                message += f"⏰ Pubblicazioni ogni {POST_INTERVAL_MINUTES} minuti\n"
                message += f"🕐 Orario: {START_HOUR}:00 - {END_HOUR}:00"
                
                self.bot.send_message(
                    chat_id=channel_id,
                    text=message,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"✅ Messaggio startup inviato su {channel_type}")
            except Exception as e:
                logger.error(f"❌ Errore invio startup su {channel_type}: {e}")

# ═══════════════════════════════════════════════════════════════
# 🎯 SISTEMA PRINCIPALE - ROTAZIONE INTELLIGENTE
# ═══════════════════════════════════════════════════════════════

class VucciaroSystem:
    """Sistema principale di gestione e pubblicazione"""
    
    def __init__(self):
        self.keepa = KeepaClient(KEEPA_API_KEY)
        self.telegram = TelegramPublisher(TELEGRAM_BOT_TOKEN)
        self.channel_rotation = list(CHANNELS.keys())
        random.shuffle(self.channel_rotation)
        self.current_channel_index = 0
        
    def get_next_channel(self) -> str:
        """Rotazione ciclica tra canali"""
        channel = self.channel_rotation[self.current_channel_index]
        self.current_channel_index = (self.current_channel_index + 1) % len(self.channel_rotation)
        return channel
    
    def fetch_deals_for_channel(self, channel: str) -> List[Dict]:
        """Recupera deals per canale (con cache)"""
        category_ids = CATEGORY_MAP.get(channel, [])
        if not category_ids:
            logger.warning(f"⚠️ Nessuna categoria per canale {channel}")
            return []
        
        # Prova cache prima
        for cat_id in category_ids:
            cached = get_cached_deals(cat_id, channel, max_age_hours=6)
            if cached:
                return cached
        
        # Altrimenti chiama API
        deals = self.keepa.fetch_browsing_deals(category_ids, min_discount=MIN_DISCOUNT)
        
        # Cache il risultato
        if deals and category_ids:
            cache_deals(category_ids[0], channel, deals)
        
        return deals
    
    def select_best_deal(self, deals: List[Dict]) -> Optional[Dict]:
        """Seleziona il deal migliore non ancora pubblicato"""
        # Ordina per: sconto + rating + recensioni
        def score(deal):
            return (
                deal['discount_percent'] * 0.5 +
                deal['rating'] * 5 +
                min(deal['review_count'] / 10, 50)
            )
        
        deals_sorted = sorted(deals, key=score, reverse=True)
        
        # Trova primo non pubblicato
        for deal in deals_sorted:
            if not is_product_posted(deal['asin'], hours=48):
                return deal
        
        return None
    
    def publish_next_deal(self):
        """Pubblica un deal sul canale successivo"""
        # Verifica orario
        now = datetime.now()
        if not (START_HOUR <= now.hour < END_HOUR):
            logger.info(f"⏸️ Fuori orario pubblicazione ({START_HOUR}-{END_HOUR})")
            return
        
        channel = self.get_next_channel()
        logger.info(f"🎯 Turno canale: {channel}")
        
        # Recupera deals
        deals = self.fetch_deals_for_channel(channel)
        
        if not deals:
            logger.warning(f"⚠️ Nessun deal disponibile per {channel}")
            return
        
        # Seleziona e pubblica
        deal = self.select_best_deal(deals)
        
        if not deal:
            logger.warning(f"⚠️ Tutti i deals già pubblicati per {channel}")
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
            logger.info(f"✅ Deal pubblicato: {deal['title'][:50]}")
        else:
            logger.error(f"❌ Pubblicazione fallita per {deal['asin']}")

# ═══════════════════════════════════════════════════════════════
# 🚀 MAIN - SCHEDULER E AVVIO
# ═══════════════════════════════════════════════════════════════

def main():
    """Entry point principale"""
    
    # Verifica variabili ambiente
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN mancante!")
        sys.exit(1)
    
    if not KEEPA_API_KEY:
        logger.error("❌ KEEPA_API_KEY mancante!")
        sys.exit(1)
    
    logger.info("=" * 70)
    logger.info("🌌 VUCCIARO UNIVERSE - Sistema Automatizzato Avviato")
    logger.info("=" * 70)
    logger.info(f"📱 Canali attivi: 2 (Tech + Moda)")
    logger.info(f"⏰ Pubblicazione ogni {POST_INTERVAL_MINUTES} minuti ({START_HOUR}:00-{END_HOUR}:00)")
    logger.info(f"💰 Filtri: sconto ≥{MIN_DISCOUNT}%, rating ≥{MIN_RATING}, recensioni ≥{MIN_REVIEWS}")
    logger.info("=" * 70)
    
    # Inizializza database
    init_database()
    
    # Inizializza sistema
    system = VucciaroSystem()
    
    # Invia messaggio di startup sui canali
    logger.info("📨 Invio messaggi di test sui canali...")
    system.telegram.send_startup_message()
    
    # Scheduler
    schedule.every(POST_INTERVAL_MINUTES).minutes.do(system.publish_next_deal)
    
    # Prima esecuzione immediata
    logger.info("🚀 Prima pubblicazione immediata...")
    system.publish_next_deal()
    
    # Loop principale
    logger.info("♻️ Scheduler attivo. Bot in esecuzione...")
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n⏹️ Bot arrestato dall'utente")
            break
        except Exception as e:
            logger.error(f"❌ Errore critico: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
