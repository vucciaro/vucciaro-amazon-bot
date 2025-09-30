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
        self.timezone = pytz.timezone(os.getenv('TIMEZONE', 'Europe/Rome'))
        
        # Inizializza bot Telegram
        self.bot = Bot(token=self.telegram_token)
        
        logger.info("✅ Bot inizializzato correttamente")

    def get_keepa_deals(self, limit=5):
        """Cerca offerte usando la query Keepa corretta"""
        try:
            # Query ESATTA dal tuo screenshot Keepa
            query = {
                "page": 0,
                "domainId": "8",
                "excludeCategories": [],
                "includeCategories": [],
                "priceTypes": [0],
                "deltaPercentRange": [5, 90],
                "salesRankRange": [-1, -1],
                "currentRange": [100, 100000],
                "minRating": -1,
                "isLowest": False,
                "isLowest90": False,
                "isLowestOffer": False,
                "isOutOfStock": False,
                "titleSearch": "",
                "isRangeEnabled": True,
                "isFilterEnabled": True,
                "filterErotic": True,
                "singleVariation": True,
                "hasReviews": False,
                "isPrimeExclusive": False,
                "mustHaveAmazonOffer": False,
                "mustNotHaveAmazonOffer": False,
                "sortType": 4,
                "dateRange": 1,
                "warehouseConditions": [1, 2, 3, 4, 5],
                "deltaLastRange": [0, 2147483647]
            }
            
            params = {
                'key': self.keepa_api_key,
                'selection': json.dumps(query)
            }
            
            logger.info("🔍 Chiamata API Keepa in corso...")
            response = requests.get('https://api.keepa.com/deal', params=params, timeout=30)
            logger.info(f"📡 Status Keepa: {response.status_code}")
            logger.info(f"📦 Risposta: {response.text[:500]}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"📦 Risposta Keepa ricevuta")
                
                if 'deals' in data and 'dr' in data['deals']:
                    deals = data['deals']['dr']
                    logger.info(f"🎯 Trovati {len(deals)} deals")
                    return self.parse_deals(deals, limit)
                else:
                    logger.warning("⚠️ Nessun deal nella risposta")
                    return []
            else:
                logger.error(f"❌ Errore API Keepa: {response.status_code}")
                return []
                        
        except Exception as e:
            logger.error(f"❌ Errore get_keepa_deals: {e}")
            return []

    def parse_deals(self, deals, limit):
        """Processa i deals da Keepa"""
        products = []
        
        for deal in deals[:limit]:
            try:
                asin = deal.get('asin', '')
                title = deal.get('title', 'Prodotto Amazon')
                
                # Prezzo attuale in centesimi
                # Prezzo attuale - può essere numero o lista
                current = deal.get('current', 0)
                if isinstance(current, list):
                    # Se è lista, prendi l'ultimo valore
                    current_price = current[-1] / 100 if current and current[-1] else 0
                elif isinstance(current, (int, float)):
                    # Se è numero, usalo direttamente
                    current_price = current / 100 if current else 0
                else:
                    current_price = 0
                
                # Percentuale sconto
                delta = deal.get('deltaPercent', 0)
                if isinstance(delta, list):
                    delta = delta[-1] if delta else 0
                
                if current_price > 0 and asin:
                    affiliate_link = f"https://www.amazon.{self.amazon_domain}/dp/{asin}?tag={self.amazon_tag}"
                    
                    products.append({
                        'asin': asin,
                        'title': title,
                        'price': current_price,
                        'discount': delta,
                        'link': affiliate_link
                    })
                    
            except Exception as e:
                logger.error(f"❌ Errore parsing deal: {e}")
                continue
                
        logger.info(f"✅ Processati {len(products)} prodotti validi")
        return products

    def format_product_message(self, product):
        """Formatta il messaggio per Telegram"""
        title = product['title'][:100] + "..." if len(product['title']) > 100 else product['title']
        price = f"€{product['price']:.2f}"
        discount = int(product.get('discount', 0))
        
        # Emoji in base allo sconto
        if discount >= 50:
            emoji = "🔥"
        elif discount >= 30:
            emoji = "⚡"
        else:
            emoji = "💎"
        
        message = f"""{emoji} *OFFERTA AMAZON* -{discount}%

📦 {title}

💰 *Prezzo: {price}*

🛒 [ACQUISTA ORA]({product['link']})

#AmazonDeals #Offerte #Sconto{discount}"""
        
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
            
            logger.info(f"✅ Prodotto inviato: {product['asin']}")
            return True
            
        except TelegramError as e:
            logger.error(f"❌ Errore Telegram: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Errore generico: {e}")
            return False

    async def post_deals(self):
        """Pubblica deals sul canale"""
        logger.info("🔄 Cercando nuove offerte...")
        
        # Ottieni prodotti da Keepa
        products = self.get_keepa_deals(limit=3)
        
        if not products:
            logger.warning("⚠️ Nessun prodotto trovato")
            # Invia notifica che non ha trovato nulla
            try:
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text="⚠️ Nessuna offerta trovata in questo momento. Riprovo più tardi!"
                )
            except:
                pass
            return
        
        # Invia il primo prodotto
        product = products[0]
        success = await self.send_product_to_channel(product)
        
        if success:
            logger.info(f"✅ Post pubblicato con successo!")
        else:
            logger.error(f"❌ Errore pubblicazione post")

    async def run_scheduler(self):
        """Scheduler principale - LOOP INFINITO"""
        logger.info("🚀 Scheduler avviato! Bot attivo 24/7")
        
        last_post_time = None
        
        while True:  # ← LOOP INFINITO - il bot non si ferma MAI
            try:
                now = datetime.now(self.timezone)
                current_time = now.strftime("%H:%M")
                hour = now.hour
                
                # Log ogni ora per sapere che il bot è vivo
                if now.minute == 0:
                    logger.info(f"✅ Bot attivo - Ora: {current_time}")
                
                # Orario valido: dalle 8:00 alle 23:00
                if 8 <= hour < 23:
                    # Controlla se è ora di postare
                    if last_post_time is None:
                        # Primo post della giornata
                        await self.post_deals()
                        last_post_time = now
                    else:
                        # Calcola minuti dall'ultimo post
                        minutes_since_last = (now - last_post_time).total_seconds() / 60
                        
                        # Posta ogni 30 minuti
                        if minutes_since_last >= 30:
                            await self.post_deals()
                            last_post_time = now
                            logger.info(f"⏰ Prossimo post tra 30 minuti")
                
                # Pausa notturna (23:00 - 8:00)
                elif hour >= 23 or hour < 8:
                    if now.minute == 0:  # Log solo una volta all'ora
                        tomorrow_8am = now.replace(hour=8, minute=0, second=0, microsecond=0)
                        if hour < 8:
                            # Siamo già nella mattina presto
                            pass
                        else:
                            # Dopo le 23, domani alle 8
                            tomorrow_8am += timedelta(days=1)
                        logger.info(f"😴 Pausa notturna - Risveglio alle 08:00")
                        last_post_time = None  # Reset per nuovo giorno
                
                # Aspetta 60 secondi prima di ricontrollare
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"❌ Errore nel loop: {e}")
                # In caso di errore, aspetta 5 minuti e riprova
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
                text="🤖 Bot avviato correttamente! Inizio ricerca offerte..."
            )
            logger.info("✅ Canale Telegram OK")
        except Exception as e:
            logger.error(f"❌ Errore canale: {e}")
            return False
        
        # Test Keepa
        try:
            products = self.get_keepa_deals(limit=1)
            if products:
                logger.info(f"✅ Keepa API OK - Trovati {len(products)} prodotti")
            else:
                logger.warning("⚠️ Keepa API: nessun prodotto trovato (normale se non ci sono offerte)")
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
