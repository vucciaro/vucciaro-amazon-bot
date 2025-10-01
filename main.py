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
        """Cerca prodotti scontati usando Keepa search"""
        try:
            # Ricerca prodotti con sconto significativo
            params = {
                'key': self.keepa_api_key,
                'domain': 8,  # Amazon.it
                'type': 'product',
                'term': '',  # Vuoto per cercare tutto
                'stats': 365,  # Statistiche ultimo anno
                'history': 1,  # Include storico prezzi
                'rating': 1,  # Include rating
                'update': 0,
                'to_update': False
            }
            
            logger.info("🔍 Chiamata API Keepa search in corso...")
            # Prima ottieni alcuni ASIN popolari
            response = requests.get('https://api.keepa.com/bestsellers', params={
                'key': self.keepa_api_key,
                'domain': 8,
                'category': '412609031'  # Elettronica
            }, timeout=30)
            
            logger.info(f"📡 Status Keepa: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"📦 Risposta Keepa ricevuta")
                
                if 'bestSellersList' in data and data['bestSellersList']:
                    # Estrai ASIN dai bestseller
                    asins = []
                    for item in data['bestSellersList']['asinList'][:limit * 2]:
                        if isinstance(item, str):
                            asins.append(item)
                    
                    if asins:
                        # Ora cerca info dettagliate sui prodotti
                        return self.get_product_details(asins[:limit])
                    
                logger.warning("⚠️ Nessun bestseller trovato")
                return []
            else:
                logger.error(f"❌ Errore API Keepa: {response.status_code}")
                return []
                        
        except Exception as e:
            logger.error(f"❌ Errore get_keepa_deals: {e}")
            return []
    
    def get_product_details(self, asins):
        """Ottieni dettagli prodotti da ASIN"""
        try:
            params = {
                'key': self.keepa_api_key,
                'domain': 8,
                'asin': ','.join(asins),
                'stats': 90,  # Stats ultimi 90 giorni
                'history': 1
            }
            
            response = requests.get('https://api.keepa.com/product', params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if 'products' in data:
                    return self.parse_products(data['products'], len(asins))
            
            return []
        except Exception as e:
            logger.error(f"❌ Errore get_product_details: {e}")
            return []
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"📦 Risposta Keepa ricevuta: {len(data.get('products', []))} prodotti")
                
                if 'products' in data and data['products']:
                    products = data['products']
                    logger.info(f"🎯 Trovati {len(products)} prodotti")
                    return self.parse_products(products, limit)
                else:
                    logger.warning("⚠️ Nessun prodotto nella risposta")
                    return []
            else:
                logger.error(f"❌ Errore API Keepa: {response.status_code}")
                logger.error(f"❌ Risposta: {response.text}")
                return []
                        
        except Exception as e:
            logger.error(f"❌ Errore get_keepa_deals: {e}")
            return []

    def parse_products(self, products, limit):
        """Processa i prodotti da Keepa"""
        parsed_products = []
        
        for product in products:
            try:
                asin = product.get('asin', '')
                title = product.get('title', 'Prodotto Amazon')
                
                # Estrai prezzo corrente dal CSV
                # Index 0 = Amazon price, Index 1 = New price
                csv = product.get('csv', [])
                current_price = 0
                
                if csv and len(csv) > 0:
                    # Prova prima il prezzo Amazon (index 0)
                    if csv[0] and len(csv[0]) > 1:
                        current_price = csv[0][-1]  # Ultimo valore
                    # Se non c'è, prova New price (index 1)  
                    elif len(csv) > 1 and csv[1] and len(csv[1]) > 1:
                        current_price = csv[1][-1]
                    
                    # Converti da centesimi a euro
                    if current_price > 0:
                        current_price = current_price / 100
                
                # Calcola sconto basato su statistiche
                stats = product.get('stats', {})
                avg30 = stats.get('avg30', [0, 0])  # [Amazon price avg, New price avg]
                
                discount = 0
                if current_price > 0:
                    # Usa il prezzo medio degli ultimi 30 giorni
                    avg_price = avg30[0] if avg30[0] > 0 else avg30[1] if len(avg30) > 1 else 0
                    if avg_price > 0:
                        avg_price = avg_price / 100
                        discount = int(((avg_price - current_price) / avg_price) * 100)
                
                # Aggiungi solo se c'è un prezzo valido
                if current_price > 0 and asin:
                    affiliate_link = f"https://www.amazon.{self.amazon_domain}/dp/{asin}?tag={self.amazon_tag}"
                    
                    parsed_products.append({
                        'asin': asin,
                        'title': title[:100],  # Limita lunghezza titolo
                        'price': current_price,
                        'discount': max(0, discount),  # Assicura che non sia negativo
                        'link': affiliate_link
                    })
                    
            except Exception as e:
                logger.error(f"❌ Errore parsing prodotto: {e}")
                continue
        
        # Ordina per sconto (se c'è) o per prezzo
        if parsed_products:
            parsed_products.sort(key=lambda x: x['discount'] if x['discount'] > 0 else -x['price'], reverse=True)
        
        best_products = parsed_products[:limit]
        logger.info(f"✅ Processati {len(best_products)} prodotti validi")
        return best_products

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
