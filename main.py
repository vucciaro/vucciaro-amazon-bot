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
            1,    # Elettronica
            2,    # Casa e giardino 
            3,    # Abbigliamento, scarpe e borse
            4,    # Sport e tempo libero
            5,    # Bellezza
            6,    # Salute e cura della persona
            7,    # Giocattoli
            8,    # Automotive
            9,    # Fai da te
            10,   # Alimentari
        ]
        
        logger.info("Bot inizializzato correttamente")

    def get_keepa_deals(self, limit=5):
        """Ottieni deals da Keepa API"""
        try:
            category = random.choice(self.categories)
            
            # URL API Keepa per ottenere prodotti in offerta
            url = "https://api.keepa.com/product"
            
            params = {
                'key': self.keepa_api_key,
                'domain': '5' if self.amazon_domain == 'it' else '1',  # 5=IT, 1=US
                'category': category,
                'range': '30',  # Ultimi 30 giorni
                'current': '1',  # Solo prodotti attualmente disponibili
                'out': '0',     # Formato output
                'limit': limit
            }
            
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return self.parse_keepa_products(data)
            else:
                logger.error(f"Errore Keepa API: {response.status_code}")
                return []
                        
        except Exception as e:
            logger.error(f"Errore durante il recupero deals: {e}")
            return []

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
            message = await self.format_product_message(product)
            
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
            message = self.format_product_message(product)
            success = await self.send_product_to_channel(product)
            if success:
                # Aspetta tra un post e l'altro per evitare spam
                await asyncio.sleep(random.randint(30, 90))
        
        logger.info(f"Inviati {len(products)} prodotti")

    async def run_scheduler(self):
        """Scheduler principale che gestisce i post"""
        logger.info("Scheduler avviato!")
        
        while True:
            try:
                now = datetime.now(self.timezone)
                
                # Posta solo durante il giorno (8-22)
                if 8 <= now.hour <= 22:
                    await self.post_deals()
                    
                    # Calcola prossimo post
                    next_post = now + timedelta(minutes=self.minutes_between_posts)
                    logger.info(f"Prossimo post: {next_post.strftime('%H:%M')}")
                    
                    # Aspetta fino al prossimo post
                    await asyncio.sleep(self.minutes_between_posts * 60)
                else:
                    # Durante la notte aspetta fino alle 8:00
                    tomorrow_8am = now.replace(hour=8, minute=0, second=0, microsecond=0)
                    if now.hour >= 8:
                        tomorrow_8am += timedelta(days=1)
                    
                    sleep_seconds = (tomorrow_8am - now).total_seconds()
                    logger.info(f"Pausa notturna. Riprendo alle 08:00 ({sleep_seconds/3600:.1f} ore)")
                    await asyncio.sleep(sleep_seconds)
                    
            except Exception as e:
                logger.error(f"Errore nello scheduler: {e}")
                # Aspetta 5 minuti prima di riprovare
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
    asyncio.run(main())
