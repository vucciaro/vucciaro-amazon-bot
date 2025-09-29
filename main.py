#!/usr/bin/env python3
import os
import asyncio
import logging
import random
from datetime import datetime, timedelta
import pytz
from telegram import Bot
from telegram.error import TelegramError
import requests
import json
from dotenv import load_dotenv

# Carica variabili dal file .env
load_dotenv()

# Configurazione logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramKeepaBot:
    def __init__(self):
        # Variabili d'ambiente
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.channel_id = os.getenv('TELEGRAM_CHANNEL_ID')
        self.keepa_api_key = os.getenv('KEEPA_API_KEY')
        self.amazon_tag = os.getenv('AMAZON_ASSOC_TAG', 'vucciaro00-21')
        self.amazon_domain = os.getenv('AMAZON_DOMAIN', 'it')
        self.posts_per_day = int(os.getenv('POSTS_PER_DAY', '25'))
        self.minutes_between_posts = int(os.getenv('MINUTES_BETWEEN_POSTS', '30'))
        self.timezone = pytz.timezone(os.getenv('TIMEZONE', 'Europe/Rome'))
        
        # Inizializza bot Telegram
        self.bot = Bot(token=self.telegram_token)
        
        # Lista di categorie Amazon popolari
        self.categories = [
            412609031,     # Elettronica
            6198092031,    # Bellezza
            1571280031,    # Auto e Moto
            524015031,     # Casa e cucina
            635016031,     # Giardino e giardinaggio
            523997031,     # Giochi e giocattoli
            1443735031,    # Grandi elettrodomestici
            425916031,     # Informatica
            411663031,     # Libri
            5512286031,    # Moda
            524012031,     # Sport e tempo libero
        ]
        
        logger.info("Bot inizializzato correttamente")

    def get_wait_minutes(self):
        """Restituisce minuti di attesa in base all'ora"""
        now = datetime.now(self.timezone)
        hour = now.hour
        
        # Ore di punta: 9-13 e 18-22 = post ogni 10 minuti
        if (9 <= hour <= 13) or (18 <= hour <= 22):
            return 10
        # Ore normali: 14-17 = ogni 15 minuti  
        elif 14 <= hour <= 17:
            return 15
        # Ore basse: 8, 23 = ogni 30 minuti
        else:
            return 30

    def get_keepa_deals(self, limit=5):
        """Cerca in 3 categorie diverse per massima varietà"""
        all_products = []
        categories_to_try = random.sample(self.categories, min(3, len(self.categories)))
        
        for category in categories_to_try:
            try:
                query = {
                    'domainId': 8,
                    'includeCategories': [category],
                    'isLowest90': True,
                    'deltaPercentRange': [40, 99],
                    'minRating': 40,
                    'mustHaveAmazonOffer': True,
                    'page': 0
                }
                
                params = {
                    'key': self.keepa_api_key,
                    'selection': json.dumps(query)
                }
                
                response = requests.get('https://api.keepa.com/deal', params=params, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    if 'deals' in data and 'dr' in data['deals']:
                        deals = data['deals']['dr']
                        all_products.extend(self.parse_browsing_deals(deals))
                
                # Piccola pausa tra chiamate
                import time
                time.sleep(0.5)
                        
            except Exception as e:
                logger.error(f"Errore categoria {category}: {e}")
                continue
        
        # Mescola e prendi i migliori
        random.shuffle(all_products)
        return all_products[:limit * 3]  # Più prodotti per varietà

    def parse_keepa_products(self, data):
        """Processa i dati dei prodotti da Keepa"""
        products = []
        
        if 'products' not in data:
            return products
            
        for product in data['products'][:5]:  # Primi 5 prodotti
            try:
                asin = product.get('asin', '')
                title = product.get('title', 'Prodotto Amazon')
                
                # Prezzo attuale (in centesimi)
                current_price = None
                if 'csv' in product and len(product['csv']) > 1:
                    prices = product['csv'][1]  # Prezzo Amazon
                    if prices and len(prices) >= 2:
                        current_price = prices[-1] / 100  # Converti da centesimi
                
                if current_price and current_price > 0:
                    # Crea link affiliato
                    affiliate_link = f"https://www.amazon.{self.amazon_domain}/dp/{asin}?tag={self.amazon_tag}"
                    
                    products.append({
                        'asin': asin,
                        'title': title,
                        'price': current_price,
                        'link': affiliate_link
                    })
                    
            except Exception as e:
                logger.error(f"Errore parsing prodotto: {e}")
                continue
                
        return products

    def parse_browsing_deals(self, deals):
        """Processa i dati dei deals da Keepa"""
        products = []
        
        for deal in deals[:5]:
            try:
                asin = deal.get('asin', '')
                title = deal.get('title', 'Prodotto Amazon')
                current_price = deal.get('current', 0) / 100 if deal.get('current') else 0
                
                if current_price > 0:
                    affiliate_link = f"https://www.amazon.{self.amazon_domain}/dp/{asin}?tag={self.amazon_tag}"
                    
                    products.append({
                        'asin': asin,
                        'title': title,
                        'price': current_price,
                        'link': affiliate_link
                    })
                    
            except Exception as e:
                logger.error(f"Errore parsing deal: {e}")
                continue
                
        return products

    def format_product_message(self, product):
        """Formatta il messaggio per Telegram"""
        title = product['title'][:100] + "..." if len(product['title']) > 100 else product['title']
        price = f"€{product['price']:.2f}"
        
        # Emoji casuali per rendere più accattivante
        emojis = ["🔥", "⚡", "💥", "🎯", "✨", "🚀", "💎", "🎉"]
        emoji = random.choice(emojis)
        
        message = f"""{emoji} *OFFERTA AMAZON*

📦 {title}

💰 *Prezzo: {price}*

🛒 [ACQUISTA QUI]({product['link']})

#AmazonDeals #Offerte #Shopping"""
        
        return message

    async def send_product_to_channel(self, product):
        """Invia prodotto al canale Telegram"""
        try:
            message = self.format_product_message(product)
            
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode='Markdown',
                disable_web_page_preview=False
            )
            
            logger.info(f"Prodotto inviato: {product['asin']}")
            return True
            
        except TelegramError as e:
            logger.error(f"Errore invio Telegram: {e}")
            return False
        except Exception as e:
            logger.error(f"Errore generico invio: {e}")
            return False

    async def post_deals(self):
        """Pubblica deals sul canale"""
        logger.info("Cercando nuove offerte...")
        
        # Ottieni prodotti da Keepa
        products = self.get_keepa_deals(limit=3)
        
        if not products:
            logger.warning("Nessun prodotto trovato")
            return
        
        # Invia ogni prodotto
        for product in products:
            success = await self.send_product_to_channel(product)
            if success:
                # Aspetta tra un post e l'altro per evitare spam
                await asyncio.sleep(random.randint(30, 90))
        
        logger.info(f"Inviati {len(products)} prodotti")

    async def run_scheduler(self):
        """Scheduler principale"""
        logger.info("Scheduler avviato!")
        
        while True:
            try:
                now = datetime.now(self.timezone)
                
                if 8 <= now.hour <= 22:
                    await self.post_deals()
                    
                    # Attesa dinamica in base all'orario
                    wait_minutes = self.get_wait_minutes()
                    next_post = now + timedelta(minutes=wait_minutes)
                    logger.info(f"Prossimo post tra {wait_minutes} minuti: {next_post.strftime('%H:%M')}")
                    
                    await asyncio.sleep(wait_minutes * 60)
                else:
                    # Pausa notturna
                    tomorrow_8am = now.replace(hour=8, minute=0, second=0, microsecond=0)
                    if now.hour >= 8:
                        tomorrow_8am += timedelta(days=1)
                    
                    sleep_seconds = (tomorrow_8am - now).total_seconds()
                    logger.info(f"Pausa notturna fino alle 08:00")
                    await asyncio.sleep(sleep_seconds)
                        
            except Exception as e:
                logger.error(f"Errore scheduler: {e}")
                await asyncio.sleep(300)

    async def test_connection(self):
        """Testa le connessioni"""
        logger.info("🔄 Testando connessioni...")
        
        # Test bot Telegram
        try:
            me = await self.bot.get_me()
            logger.info(f"✅ Bot Telegram OK: @{me.username}")
        except Exception as e:
            logger.error(f"❌ Errore bot Telegram: {e}")
            return False
        
        # Test canale
        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text="🤖 Bot avviato correttamente!"
            )
            logger.info("✅ Canale Telegram OK")
        except Exception as e:
            logger.error(f"❌ Errore canale: {e}")
            return False
        
        # Test Keepa
        try:
            products = self.get_keepa_deals(limit=1)
            if products:
                logger.info("✅ Keepa API OK")
            else:
                logger.warning("⚠️ Keepa API: nessun prodotto trovato")
        except Exception as e:
            logger.error(f"❌ Errore Keepa API: {e}")
            return False
            
        return True

async def main():
    """Funzione principale"""
    logger.info("🚀 Avvio Bot Telegram-Keepa...")
    
    # Verifica variabili d'ambiente
    required_vars = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHANNEL_ID', 'KEEPA_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"❌ Variabili mancanti: {missing_vars}")
        return
    
    # Inizializza bot
    bot = TelegramKeepaBot()
    
    # Test connessioni
    if await bot.test_connection():
        logger.info("🎉 Tutti i test superati! Avvio scheduler...")
        await bot.run_scheduler()
    else:
        logger.error("❌ Test falliti. Controlla la configurazione.")

if __name__ == "__main__":
    asyncio.run(main()
