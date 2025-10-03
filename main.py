#!/usr/bin/env python3
import os
import asyncio
import logging
import random
import json
from datetime import datetime, timedelta
from pathlib import Path
import pytz
from telegram import Bot
from telegram.error import TelegramError
import requests
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
        
        # Categorie Amazon.it da usare insieme
        self.categories = [
            {'id': '77028031', 'name': 'Abbigliamento'},
            {'id': '4635183031', 'name': 'Scarpe e Borse'},
            {'id': '51571031', 'name': 'Bellezza'}
        ]
        
        # Rotazione pagine per variare risultati
        self.current_page = 0
        
        # Tracking ASIN pubblicati
        self.storage_dir = Path('/data') if Path('/data').exists() else Path('.')
        self.published_file = self.storage_dir / 'published_asins.json'
        self.published_asins = self.load_published_asins()
        
        # Tracking Lightning Deals
        self.use_lightning = True
        
        logger.info("Bot inizializzato - Browsing Deals + Lightning Deals")

    def load_published_asins(self):
        """Carica ASIN già pubblicati"""
        try:
            if self.published_file.exists():
                with open(self.published_file, 'r') as f:
                    data = json.load(f)
                    logger.info(f"Caricati {len(data)} ASIN gia pubblicati")
                    return set(data)
        except Exception as e:
            logger.error(f"Errore caricamento ASIN: {e}")
        
        logger.info("Nessun ASIN precedente, inizio da zero")
        return set()

    def save_published_asins(self):
        """Salva ASIN pubblicati"""
        try:
            with open(self.published_file, 'w') as f:
                json.dump(list(self.published_asins), f)
            logger.info(f"Salvati {len(self.published_asins)} ASIN")
        except Exception as e:
            logger.error(f"Errore salvataggio ASIN: {e}")

    def get_lightning_deals(self, limit=5):
        """Ottieni Lightning Deals da Keepa"""
        try:
            params = {
                'key': self.keepa_api_key,
                'domain': 8,
                'state': 'AVAILABLE'
            }
            
            logger.info("Chiamata Lightning Deals API...")
            response = requests.get('https://api.keepa.com/lightningdeal', params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'lightningDeals' in data and data['lightningDeals']:
                    deals = data['lightningDeals']
                    logger.info(f"Trovati {len(deals)} Lightning Deals")
                    
                    # Filtra ASIN non pubblicati
                    new_deals = [d for d in deals if d.get('asin') not in self.published_asins]
                    
                    if not new_deals:
                        logger.info("Tutti Lightning pubblicati! Reset...")
                        self.published_asins.clear()
                        self.save_published_asins()
                        new_deals = deals
                    
                    # Prendi primi ASIN
                    asins = [d['asin'] for d in new_deals[:limit * 2]]
                    random.shuffle(asins)
                    
                    products = self.get_product_details(asins[:limit])
                    # Marca come Lightning
                    for p in products:
                        p['is_lightning'] = True
                    return products
                
                logger.warning("Nessun Lightning Deal disponibile")
                return []
            else:
                logger.error(f"Errore Lightning API: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Errore Lightning Deals: {e}")
            return []

    def get_keepa_deals(self, limit=10):
        """Cerca prodotti scontati usando Keepa Browsing Deals API"""
        try:
            logger.info(f"Ricerca deals (pagina {self.current_page})")
            
            # Query Browsing Deals API con 3 categorie
            query = {
                "page": self.current_page,
                "domainId": 8,
                "includeCategories": [77028031, 4635183031, 51571031],
                "excludeCategories": [],
                "priceTypes": [0],
                "deltaPercentRange": [10, 100],
                "currentRange": [300, 150000],
                "minRating": 30,
                "isLowest90": False,
                "isRangeEnabled": True,
                "isFilterEnabled": True,
                "filterErotic": True,
                "singleVariation": True,
                "mustHaveAmazonOffer": True,
                "sortType": 4,
                "dateRange": 1
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
                    logger.info(f"Trovati {len(deals)} deals (pagina {self.current_page})")
                    
                    # Ruota pagina per la prossima volta (0-4)
                    self.current_page = (self.current_page + 1) % 5
                    
                    return self.parse_deals(deals, limit)
                else:
                    logger.warning("Nessun deal trovato")
                    return []
            else:
                logger.error(f"Errore Keepa API: {response.status_code}")
                return []
                        
        except Exception as e:
            logger.error(f"Errore get_keepa_deals: {e}")
            return []

    def parse_deals(self, deals, limit):
        """Processa i deals da Keepa"""
        products = []
        
        # Filtra deals già pubblicati
        new_deals = [d for d in deals if d.get('asin') not in self.published_asins]
        
        if not new_deals:
            logger.info("Tutti i deals gia pubblicati! Reset...")
            self.published_asins.clear()
            self.save_published_asins()
            new_deals = deals
        
        logger.info(f"{len(new_deals)} deals nuovi da {len(deals)} totali")
        
        for deal in new_deals[:limit]:
            try:
                asin = deal.get('asin', '')
                title = deal.get('title', 'Prodotto Amazon')
                
                # FIX: current è un array [prezzo_centesimi, timestamp]
                current = deal.get('current')
                current_price = 0
                
                if current:
                    if isinstance(current, list) and len(current) > 0:
                        current_price = current[0] / 100
                    elif isinstance(current, (int, float)):
                        current_price = current / 100
                
                # Sconto percentuale
                delta = deal.get('deltaPercent', 0)
                
                if current_price > 0 and asin:
                    affiliate_link = f"https://www.amazon.{self.amazon_domain}/dp/{asin}?tag={self.amazon_tag}"
                    
                    products.append({
                        'asin': asin,
                        'title': title[:100],
                        'price': current_price,
                        'discount': delta,
                        'link': affiliate_link,
                        'is_lightning': False
                    })
                    
            except Exception as e:
                logger.error(f"Errore parsing deal: {e}")
                continue
        
        # Randomizza per varietà
        random.shuffle(products)
        logger.info(f"Processati {len(products)} prodotti validi")
        return products

    def get_product_details(self, asins):
        """Ottieni dettagli prodotti da ASIN"""
        try:
            params = {
                'key': self.keepa_api_key,
                'domain': 8,
                'asin': ','.join(asins),
                'stats': 90
            }
            
            response = requests.get('https://api.keepa.com/product', params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if 'products' in data:
                    products = []
                    for product in data['products']:
                        try:
                            asin = product.get('asin', '')
                            title = product.get('title', 'Prodotto Amazon')
                            
                            # Estrai prezzo
                            csv = product.get('csv', [])
                            current_price = 0
                            
                            if csv and len(csv) > 0:
                                if csv[0] and len(csv[0]) > 1:
                                    current_price = csv[0][-1] / 100
                                elif len(csv) > 1 and csv[1] and len(csv[1]) > 1:
                                    current_price = csv[1][-1] / 100
                            
                            # Calcola sconto
                            stats = product.get('stats', {})
                            avg30 = stats.get('avg30', [0, 0])
                            discount = 0
                            if current_price > 0 and avg30[0] > 0:
                                avg_price = avg30[0] / 100
                                discount = int(((avg_price - current_price) / avg_price) * 100)
                            
                            if current_price > 0:
                                affiliate_link = f"https://www.amazon.{self.amazon_domain}/dp/{asin}?tag={self.amazon_tag}"
                                products.append({
                                    'asin': asin,
                                    'title': title[:100],
                                    'price': current_price,
                                    'discount': max(0, discount),
                                    'link': affiliate_link,
                                    'is_lightning': False
                                })
                        except:
                            continue
                    
                    return products
            
            return []
        except Exception as e:
            logger.error(f"Errore get_product_details: {e}")
            return []

    def format_product_message(self, product):
        """Formatta il messaggio per Telegram"""
        title = product['title'][:100] + "..." if len(product['title']) > 100 else product['title']
        # Escapa caratteri Markdown
        title = title.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace('`', '\\`')
        
        price = f"€{product['price']:.2f}"
        discount = int(product.get('discount', 0))
        is_lightning = product.get('is_lightning', False)
        
        # Emoji in base allo sconto
        if discount >= 50:
            emoji = "🔥"
        elif discount >= 30:
            emoji = "⚡"
        else:
            emoji = "💎"
        
        # Header diverso per Lightning Deals
        if is_lightning:
            urgency_msgs = [
                "⏰ OFFERTA LAMPO - Termina tra poche ore!",
                "🚨 ATTENZIONE: Scorte limitate!",
                "⚡ SOLO PER OGGI - Disponibilita limitata!",
                "🔥 ULTIMI PEZZI - Affrettati!",
                "⏳ TEMPO LIMITATO - Non perdere l'occasione!"
            ]
            urgency = random.choice(urgency_msgs)
            header = f"⚡ *OFFERTA LAMPO AMAZON* -{discount}%\n\n{urgency}"
            hashtags = f"#LightningDeal #OffertaLampo #Sconto{discount}"
        else:
            header = f"{emoji} *OFFERTA AMAZON* -{discount}%"
            hashtags = f"#AmazonDeals #Offerte #Sconto{discount}"
        
        message = f"""{header}

📦 {title}

💰 *Prezzo: {price}*

🛒 [ACQUISTA SUBITO]({product['link']})

{hashtags}"""
        
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
            
            # Aggiungi ASIN ai pubblicati
            self.published_asins.add(product['asin'])
            self.save_published_asins()
            
            logger.info(f"Prodotto inviato: {product['asin']} | Tot pubblicati: {len(self.published_asins)}")
            return True
            
        except TelegramError as e:
            logger.error(f"Errore Telegram: {e}")
            return False
        except Exception as e:
            logger.error(f"Errore generico: {e}")
            return False

    async def post_deals(self):
        """Pubblica deals sul canale"""
        logger.info("Cercando nuove offerte...")
        
        # Alterna tra Lightning Deals e Browsing Deals
        if self.use_lightning:
            logger.info("Tento Lightning Deals...")
            products = self.get_lightning_deals(limit=3)
            if not products:
                logger.info("Fallback a Browsing Deals...")
                products = self.get_keepa_deals(limit=5)
        else:
            products = self.get_keepa_deals(limit=5)
        
        # Alterna per il prossimo giro
        self.use_lightning = not self.use_lightning
        
        if not products:
            logger.warning("Nessun prodotto trovato")
            try:
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text="⚠️ Nessuna offerta trovata in questo momento. Riprovo piu tardi!"
                )
            except:
                pass
            return
        
        # Invia il primo prodotto
        product = products[0]
        success = await self.send_product_to_channel(product)
        
        if success:
            logger.info("Post pubblicato con successo!")
        else:
            logger.error("Errore pubblicazione post")

    async def run_scheduler(self):
        """Scheduler principale - LOOP INFINITO"""
        logger.info("Scheduler avviato! Bot attivo 24/7")
        
        last_post_time = None
        
        while True:
            try:
                now = datetime.now(self.timezone)
                current_time = now.strftime("%H:%M")
                hour = now.hour
                
                # Log ogni ora
                if now.minute == 0:
                    logger.info(f"Bot attivo - Ora: {current_time}")
                
                # Orario valido: 8:00 - 23:00
                if 8 <= hour < 23:
                    if last_post_time is None:
                        await self.post_deals()
                        last_post_time = now
                    else:
                        minutes_since_last = (now - last_post_time).total_seconds() / 60
                        
                        # Intervallo 10 minuti per TEST
                        interval = 10
                        
                        if minutes_since_last >= interval:
                            await self.post_deals()
                            last_post_time = now
                            logger.info(f"Prossimo post tra {interval} minuti")
                
                # Pausa notturna
                elif hour >= 23 or hour < 8:
                    if now.minute == 0:
                        logger.info("Pausa notturna - Risveglio alle 08:00")
                        last_post_time = None
                
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Errore nel loop: {e}")
                await asyncio.sleep(300)

    async def test_connection(self):
        """Testa le connessioni"""
        logger.info("Testando connessioni...")
        
        # Test bot Telegram
        try:
            me = await self.bot.get_me()
            logger.info(f"Bot Telegram OK: @{me.username}")
        except Exception as e:
            logger.error(f"Errore bot Telegram: {e}")
            return False
        
        # Test canale
        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text="🤖 Bot avviato! Intervallo TEST: 10 minuti\n💰 Range: €3-1500 | 3 categorie"
            )
            logger.info("Canale Telegram OK")
        except Exception as e:
            logger.error(f"Errore canale: {e}")
            return False
        
        # Test Keepa
        try:
            products = self.get_keepa_deals(limit=1)
            if products:
                logger.info(f"Keepa API OK - Trovati {len(products)} prodotti")
            else:
                logger.warning("Keepa API: nessun prodotto trovato (normale se non ci sono offerte)")
        except Exception as e:
            logger.error(f"Errore Keepa API: {e}")
            return False
            
        return True

async def main():
    """Funzione principale"""
    logger.info("Avvio Bot Telegram-Keepa...")
    
    # Verifica variabili d'ambiente
    required_vars = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHANNEL_ID', 'KEEPA_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Variabili mancanti: {missing_vars}")
        return
    
    # Inizializza bot
    bot = TelegramKeepaBot()
    
    # Test connessioni
    if await bot.test_connection():
        logger.info("Tutti i test superati! Avvio scheduler...")
        await bot.run_scheduler()
    else:
        logger.error("Test falliti. Controlla la configurazione.")

if __name__ == "__main__":
    asyncio.run(main())
