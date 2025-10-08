"""
🌌 VUCCIARO UNIVERSE - BOT TELEGRAM OFFERTE AMAZON
═══════════════════════════════════════════════════════════

✅ 2 CANALI:
- @VucciaroTech (Tecnologia)
- @VucciaroModa (Moda & Style)

✅ ENDPOINT KEEPA CORRETTI:
- Lightning Deals: GET /lightningdeal
- Browsing Deals: POST /deal

✅ FUNZIONALITÀ:
- Rotazione automatica tra i 2 canali
- Pubblicazione ogni 20 minuti (07:00-23:00)
- Deduplica prodotti con SQLite
- Gestione errori e retry
"""

import os
import sys
import time
import random
import logging
import sqlite3
from datetime import datetime, time as dt_time
from typing import Dict, List, Optional
import requests
from telegram import Bot
from telegram.error import TelegramError

# ═══════════════════════════════════════════════════════════════
# 🔧 CONFIGURAZIONE
# ═══════════════════════════════════════════════════════════════

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variabili ambiente
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
KEEPA_API_KEY = os.getenv('KEEPA_API_KEY')
AMAZON_TAG = os.getenv('AMAZON_TAG', 'vucciaro-21')

# Validazione
if not TELEGRAM_BOT_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN mancante!")
    sys.exit(1)

if not KEEPA_API_KEY:
    logger.error("❌ KEEPA_API_KEY mancante!")
    sys.exit(1)

# Costanti Keepa
KEEPA_DOMAIN_IT = 8  # Amazon.it
KEEPA_BASE_URL = "https://api.keepa.com"  # HTTPS non HTTP!

# ═══════════════════════════════════════════════════════════════
# 📺 CONFIGURAZIONE CANALI (SOLO 2)
# ═══════════════════════════════════════════════════════════════

CHANNELS = {
    'tech': {
        'id': '@VucciaroTech',
        'name': '🖥️ Tech & Gadget',
        'categories': [560798, 412609011, 460139031, 3370831],  # Elettronica, Informatica, Audio, Foto
        'emoji': ['⚡', '💻', '📱', '🎧', '⌚', '🔌'],
        'min_discount': 20
    },
    'moda': {
        'id': '@VucciaroModa',
        'name': '👗 Moda & Style',
        'categories': [1571275031, 1571274031, 1571285031],  # Abbigliamento, Scarpe, Accessori
        'emoji': ['✨', '👗', '👠', '👜', '💄', '🕶️'],
        'min_discount': 25
    }
}

# ═══════════════════════════════════════════════════════════════
# 🗄️ DATABASE
# ═══════════════════════════════════════════════════════════════

def init_database():
    """Inizializza database SQLite per deduplica"""
    conn = sqlite3.connect('vucciaro.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS published_products (
            asin TEXT PRIMARY KEY,
            channel TEXT,
            published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("✅ Database inizializzato")

def is_product_published(asin: str) -> bool:
    """Verifica se prodotto già pubblicato"""
    conn = sqlite3.connect('vucciaro.db')
    c = conn.cursor()
    c.execute('SELECT asin FROM published_products WHERE asin = ?', (asin,))
    result = c.fetchone()
    conn.close()
    return result is not None

def mark_product_published(asin: str, channel: str):
    """Marca prodotto come pubblicato"""
    conn = sqlite3.connect('vucciaro.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO published_products (asin, channel) VALUES (?, ?)', 
              (asin, channel))
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════════════
# 🔌 KEEPA API CLIENT
# ═══════════════════════════════════════════════════════════════

class KeepaAPI:
    """Client Keepa API con endpoint corretti"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = KEEPA_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'VucciaroBot/1.0'
        })
    
    def _call_api(self, endpoint: str, params: dict = None, method: str = 'GET') -> dict:
        """Chiamata API generica con retry"""
        params = params or {}
        params['key'] = self.api_key
        
        url = f"{self.base_url}/{endpoint}"
        
        for attempt in range(3):
            try:
                if method == 'POST':
                    response = self.session.post(url, json=params, timeout=30)
                else:
                    response = self.session.get(url, params=params, timeout=30)
                
                # Rate limit
                if response.status_code == 429:
                    logger.warning("⏳ Rate limit Keepa, attendo 60s...")
                    time.sleep(60)
                    continue
                
                # Altri errori HTTP
                if response.status_code != 200:
                    logger.error(f"❌ Keepa API {response.status_code}: {response.text[:200]}")
                    return {}
                
                return response.json()
                
            except requests.exceptions.Timeout:
                logger.warning(f"⏱️ Timeout tentativo {attempt+1}/3")
                time.sleep(5)
            except requests.exceptions.RequestException as e:
                logger.error(f"❌ Errore connessione: {e}")
                time.sleep(5)
        
        return {}
    
    def get_lightning_deals(self) -> List[Dict]:
        """
        ⚡ LIGHTNING DEALS
        GET /lightningdeal?key=XXX&domainId=8
        """
        logger.info("⚡ Recupero Lightning Deals...")
        
        params = {
            'domainId': KEEPA_DOMAIN_IT
        }
        
        data = self._call_api('lightningdeal', params, method='GET')
        
        if not data or 'deals' not in data:
            logger.warning("Nessun Lightning Deal disponibile")
            return []
        
        deals = data.get('deals', [])
        logger.info(f"⚡ Lightning Deals trovati: {len(deals)}")
        return deals
    
    def get_browsing_deals(self, categories: List[int], min_discount: int = 20) -> List[Dict]:
        """
        🔍 BROWSING DEALS
        POST /deal con JSON query
        """
        logger.info(f"🔍 Recupero Browsing Deals per {len(categories)} categorie...")
        
        query = {
            'domainId': KEEPA_DOMAIN_IT,
            'page': 0,
            'excludeCategories': [],
            'includeCategories': categories,
            'priceTypes': [0],  # Amazon price
            'deltaRange': [500, 100000],  # 5€ - 1000€
            'deltaPercentRange': [min_discount, 100],
            'salesRankRange': [0, 50000],
            'currentRange': [500, 100000],
            'minRating': 35,  # 3.5 stelle
            'isLowest': False,
            'isLowest90': False,
            'isLowestOffer': False,
            'isOutOfStock': False,
            'titleSearch': None,
            'isRangeEnabled': True,
            'isFilterEnabled': False,
            'filterErotic': True,
            'singleVariation': True,
            'hasReviews': True,
            'sortType': 4,
            'dateRange': 1,
            'warehouseConditions': [1, 2, 3, 4, 5]
        }
        
        data = self._call_api('deal', query, method='POST')
        
        if not data or 'dr' not in data:
            logger.warning("Nessuna offerta trovata")
            return []
        
        deals = data.get('dr', [])
        logger.info(f"🔍 Browsing Deals trovati: {len(deals)}")
        return deals

# ═══════════════════════════════════════════════════════════════
# 📦 PRODUCT PROCESSOR
# ═══════════════════════════════════════════════════════════════

class ProductProcessor:
    """Processa e valida prodotti"""
    
    @staticmethod
    def extract_from_lightning_deal(deal: Dict) -> Optional[Dict]:
        """Estrae info da Lightning Deal"""
        try:
            # Controllo stato
            if deal.get('dealState') != 'AVAILABLE':
                return None
            
            return {
                'asin': deal.get('asin'),
                'title': deal.get('title', 'Prodotto in offerta'),
                'image': deal.get('image'),
                'current_price': deal.get('dealPrice', 0) / 100,  # Keepa usa centesimi
                'original_price': deal.get('currentPrice', 0) / 100,
                'rating': deal.get('rating', 0) / 10,
                'reviews': deal.get('totalReviews', 0),
                'discount': deal.get('percentOff', 0),
                'is_lightning': True
            }
        except Exception as e:
            logger.error(f"❌ Errore parsing Lightning Deal: {e}")
            return None
    
    @staticmethod
    def extract_from_browsing_deal(deal: Dict) -> Optional[Dict]:
        """Estrae info da Browsing Deal"""
        try:
            # Prezzi da CSV array (formato Keepa)
            current = deal.get('current', [None])[0]
            avg90 = deal.get('avg90', [None])[0]
            
            if not current or not avg90:
                return None
            
            current_price = current / 100
            original_price = avg90 / 100
            discount = round(((original_price - current_price) / original_price) * 100)
            
            # Immagine
            images = deal.get('imagesCSV', '')
            image = images.split(',')[0] if images else None
            
            return {
                'asin': deal.get('asin'),
                'title': deal.get('title', 'Prodotto in offerta'),
                'image': image,
                'current_price': current_price,
                'original_price': original_price,
                'rating': deal.get('rating', 0) / 10,
                'reviews': deal.get('reviewCount', 0),
                'discount': discount,
                'is_lightning': False
            }
        except Exception as e:
            logger.error(f"❌ Errore parsing Browsing Deal: {e}")
            return None
    
    @staticmethod
    def is_valid_product(product: Dict, min_discount: int) -> bool:
        """Valida prodotto"""
        if not product or not product.get('asin'):
            return False
        
        # Prezzi validi
        if not product.get('current_price') or product['current_price'] <= 0:
            return False
        
        # Sconto minimo
        if product.get('discount', 0) < min_discount:
            return False
        
        # Rating minimo 3.0
        if product.get('rating', 0) < 3.0:
            return False
        
        # Range prezzo 5€ - 1000€
        price = product['current_price']
        if price < 5 or price > 1000:
            return False
        
        return True

# ═══════════════════════════════════════════════════════════════
# 📢 TELEGRAM PUBLISHER
# ═══════════════════════════════════════════════════════════════

class TelegramPublisher:
    """Pubblica prodotti su Telegram"""
    
    def __init__(self, bot_token: str):
        self.bot = Bot(token=bot_token)
    
    def format_message(self, product: Dict, channel_emoji: List[str]) -> str:
        """Formatta messaggio Telegram"""
        emoji = random.choice(channel_emoji)
        title = product['title'][:120] + "..." if len(product['title']) > 120 else product['title']
        
        discount_emoji = "🔥" if product['discount'] >= 50 else "⚡"
        
        message = f"{emoji} **{discount_emoji} -{product['discount']}% | {title}**\n\n"
        message += f"💰 **Prezzo:** ~~{product['original_price']:.2f}€~~ → **{product['current_price']:.2f}€**\n"
        
        if product.get('rating'):
            stars = "⭐" * int(product['rating'])
            message += f"{stars} {product['rating']:.1f}/5"
            if product.get('reviews'):
                message += f" ({product['reviews']} recensioni)\n"
            else:
                message += "\n"
        
        if product.get('is_lightning'):
            message += f"\n⚡ **OFFERTA LAMPO** - Scade tra poco!\n"
        
        message += f"\n👉 [Acquista Ora](https://www.amazon.it/dp/{product['asin']}?tag={AMAZON_TAG})"
        
        return message
    
    def publish_product(self, product: Dict, channel_id: str, channel_emoji: List[str]) -> bool:
        """Pubblica prodotto su canale"""
        try:
            message = self.format_message(product, channel_emoji)
            
            # Prepara immagine
            photo = product.get('image')
            if photo and not photo.startswith('http'):
                photo = f"https://images-na.ssl-images-amazon.com/images/I/{photo}"
            
            # Invia messaggio
            if photo:
                self.bot.send_photo(
                    chat_id=channel_id,
                    photo=photo,
                    caption=message,
                    parse_mode='Markdown'
                )
            else:
                self.bot.send_message(
                    chat_id=channel_id,
                    text=message,
                    parse_mode='Markdown',
                    disable_web_page_preview=False
                )
            
            logger.info(f"✅ Pubblicato su {channel_id}: {product['title'][:50]}")
            return True
            
        except TelegramError as e:
            logger.error(f"❌ Errore Telegram: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Errore pubblicazione: {e}")
            return False

# ═══════════════════════════════════════════════════════════════
# 🎯 MAIN BOT LOGIC
# ═══════════════════════════════════════════════════════════════

class VucciaroBot:
    """Bot principale"""
    
    def __init__(self):
        self.keepa = KeepaAPI(KEEPA_API_KEY)
        self.publisher = TelegramPublisher(TELEGRAM_BOT_TOKEN)
        self.processor = ProductProcessor()
        self.channel_rotation = list(CHANNELS.keys())
        random.shuffle(self.channel_rotation)
        self.current_channel_index = 0
    
    def is_active_hours(self) -> bool:
        """Verifica orario attivo (07:00-23:00)"""
        now = datetime.now().time()
        return dt_time(7, 0) <= now <= dt_time(23, 0)
    
    def get_next_channel(self) -> Dict:
        """Rotazione canali"""
        channel_key = self.channel_rotation[self.current_channel_index]
        self.current_channel_index = (self.current_channel_index + 1) % len(self.channel_rotation)
        return CHANNELS[channel_key]
    
    def find_and_publish_deal(self):
        """Trova e pubblica offerta"""
        if not self.is_active_hours():
            logger.info("⏸️ Fuori orario attivo (07:00-23:00)")
            return
        
        channel = self.get_next_channel()
        logger.info(f"\n{'='*60}")
        logger.info(f"🎯 Canale attivo: {channel['name']} ({channel['id']})")
        logger.info(f"{'='*60}")
        
        product = None
        
        # 1. Prova Lightning Deals
        lightning_deals = self.keepa.get_lightning_deals()
        for deal in lightning_deals:
            p = self.processor.extract_from_lightning_deal(deal)
            if p and self.processor.is_valid_product(p, channel['min_discount']) and not is_product_published(p['asin']):
                product = p
                logger.info("⚡ Trovato Lightning Deal valido!")
                break
        
        # 2. Se no Lightning, prova Browsing Deals
        if not product:
            logger.info("🔍 Nessun Lightning Deal, provo Browsing Deals...")
            browsing_deals = self.keepa.get_browsing_deals(
                channel['categories'],
                channel['min_discount']
            )
            
            for deal in browsing_deals:
                p = self.processor.extract_from_browsing_deal(deal)
                if p and self.processor.is_valid_product(p, channel['min_discount']) and not is_product_published(p['asin']):
                    product = p
                    logger.info("🔍 Trovato Browsing Deal valido!")
                    break
        
        # 3. Pubblica
        if product:
            success = self.publisher.publish_product(
                product,
                channel['id'],
                channel['emoji']
            )
            
            if success:
                mark_product_published(product['asin'], channel['id'])
                logger.info(f"✅ Prodotto pubblicato: {product['asin']}")
            else:
                logger.error("❌ Pubblicazione fallita")
        else:
            logger.warning("⚠️ Nessun prodotto valido trovato")
    
    def run(self):
        """Loop principale"""
        logger.info("🚀 Vucciaro Bot avviato!")
        logger.info(f"⏰ Orario attivo: 07:00-23:00")
        logger.info(f"⏱️ Frequenza: ogni 20 minuti")
        logger.info(f"📺 Canali: {len(CHANNELS)}\n")
        
        while True:
            try:
                self.find_and_publish_deal()
            except Exception as e:
                logger.error(f"❌ Errore nel ciclo principale: {e}")
            
            logger.info("⏱️ Attendo 20 minuti...\n")
            time.sleep(1200)  # 20 minuti

# ═══════════════════════════════════════════════════════════════
# 🎬 MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    init_database()
    bot = VucciaroBot()
    bot.run()
