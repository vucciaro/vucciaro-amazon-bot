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

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramKeepaBot:
    def __init__(self):
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.channel_id = os.getenv('TELEGRAM_CHANNEL_ID')
        self.keepa_api_key = os.getenv('KEEPA_API_KEY')
        self.amazon_tag = os.getenv('AMAZON_ASSOC_TAG', 'vucciaro00-21')
        self.amazon_domain = os.getenv('AMAZON_DOMAIN', 'it')
        self.timezone = pytz.timezone(os.getenv('TIMEZONE', 'Europe/Rome'))
        
        self.bot = Bot(token=self.telegram_token)
        
        self.data_dir = '/data' if os.path.exists('/data') else '.'
        self.published_asins = set()
        self.published_asins_file = os.path.join(self.data_dir, 'published_asins.json')
        self.load_published_asins()
        
        self.categories = [
            {'id': '77028031', 'name': 'Abbigliamento'},
            {'id': '4635183031', 'name': 'Scarpe e Borse'},
            {'id': '412609031', 'name': 'Elettronica'},
            {'id': '460049031', 'name': 'Informatica'},
            {'id': '50500031', 'name': 'Sport'},
            {'id': '524015031', 'name': 'Casa e Cucina'},
            {'id': '51571031', 'name': 'Bellezza'}
        ]
        self.current_category_index = 0
        self.use_lightning_deals = False
        
        logger.info(f"Bot inizializzato | Storage: {self.data_dir}")

    def load_published_asins(self):
        try:
            if os.path.exists(self.published_asins_file):
                with open(self.published_asins_file, 'r') as f:
                    data = json.load(f)
                    self.published_asins = set(data[-200:])
                    logger.info(f"Caricati {len(self.published_asins)} ASIN pubblicati")
            else:
                self.published_asins = set()
                logger.info("Nessun ASIN precedente")
        except Exception as e:
            logger.error(f"Errore caricamento ASIN: {e}")
            self.published_asins = set()
    
    def save_published_asins(self):
        try:
            with open(self.published_asins_file, 'w') as f:
                json.dump(list(self.published_asins), f)
            logger.info(f"Salvati {len(self.published_asins)} ASIN")
        except Exception as e:
            logger.error(f"Errore salvataggio ASIN: {e}")

    def get_next_category(self):
        category = self.categories[self.current_category_index]
        self.current_category_index = (self.current_category_index + 1) % len(self.categories)
        return category

    def get_lightning_deals(self, limit=10):
        try:
            logger.info("Ricerca Lightning Deals...")
            
            response = requests.get(
                'https://api.keepa.com/lightningdeal',
                params={
                    'key': self.keepa_api_key,
                    'domain': 8,
                    'state': 'AVAILABLE'
                },
                timeout=30
            )
            
            logger.info(f"Status Lightning: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                if 'lightningDeals' in data and data['lightningDeals']:
                    deals = data['lightningDeals']
                    logger.info(f"Trovati {len(deals)} Lightning Deals")
                    
                    asins = []
                    for deal in deals[:limit * 2]:
                        if 'asin' in deal:
                            asins.append(deal['asin'])
                    
                    if asins:
                        new_asins = [asin for asin in asins if asin not in self.published_asins]
                        
                        if not new_asins:
                            logger.info("Reset Lightning pubblicati")
                            self.published_asins.clear()
                            self.save_published_asins()
                            new_asins = asins
                        
                        random.shuffle(new_asins)
                        logger.info(f"{len(new_asins[:limit])} Lightning nuovi")
                        
                        products = self.get_product_details(new_asins[:limit])
                        for p in products:
                            p['is_lightning'] = True
                        return products
                
                logger.warning("Nessun Lightning Deal")
                return []
            else:
                logger.error(f"Errore Lightning: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Errore get_lightning_deals: {e}")
            return []

    def get_keepa_deals(self, limit=10):
        try:
            if self.use_lightning_deals:
                self.use_lightning_deals = False
                lightning = self.get_lightning_deals(limit)
                if lightning:
                    return lightning
            else:
                self.use_lightning_deals = True
            
            category = self.get_next_category()
            logger.info(f"Ricerca deals in: {category['name']}")
            
            query = {
                "page": 0,
                "domainId": 8,
                "includeCategories": [int(category['id'])],
                "priceTypes": [0],
                "deltaPercentRange": [10, 100],
                "minRating": 30,
                "dateRange": 0
            }
            
            response = requests.post(
                'https://api.keepa.com/deal',
                params={'key': self.keepa_api_key},
                json=query,
                timeout=30
            )
            
            logger.info(f"Status Keepa: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                if 'dr' in data and data['dr']:
                    deals = data['dr']
                    logger.info(f"Trovati {len(deals)} deals in {category['name']}")
                    
                    asins = []
                    for deal in deals[:limit * 2]:
                        if 'asin' in deal:
                            asins.append(deal['asin'])
                    
                    if asins:
                        new_asins = [asin for asin in asins if asin not in self.published_asins]
                        
                        if not new_asins:
                            logger.info("Reset deals pubblicati")
                            self.published_asins.clear()
                            self.save_published_asins()
                            new_asins = asins
                        
                        random.shuffle(new_asins)
                        
                        logger.info(f"{len(new_asins[:limit])} prodotti nuovi da {len(asins)}")
                        
                        return self.get_product_details(new_asins[:limit])
                
                logger.warning(f"Nessun deal in {category['name']}")
                return []
            else:
                logger.error(f"Errore API Keepa: {response.status_code}")
                if response.text:
                    logger.error(f"Response: {response.text}")
                return []
                        
        except Exception as e:
            logger.error(f"Errore get_keepa_deals: {e}")
            return []
    
    def get_product_details(self, asins):
        try:
            params = {
                'key': self.keepa_api_key,
                'domain': 8,
                'asin': ','.join(asins),
                'stats': 90,
                'history': 1
            }
            
            response = requests.get('https://api.keepa.com/product', params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if 'products' in data:
                    return self.parse_products(data['products'], len(asins))
            
            return []
        except Exception as e:
            logger.error(f"Errore get_product_details: {e}")
            return []

    def parse_products(self, products, limit):
        parsed_products = []
        
        for product in products:
            try:
                asin = product.get('asin', '')
                title = product.get('title', 'Prodotto Amazon')
                
                csv = product.get('csv', [])
                current_price = 0
                
                if csv and len(csv) > 0:
                    if csv[0] and len(csv[0]) > 1:
                        current_price = csv[0][-1]
                    elif len(csv) > 1 and csv[1] and len(csv[1]) > 1:
                        current_price = csv[1][-1]
                    
                    if current_price > 0:
                        current_price = current_price / 100
                
                stats = product.get('stats', {})
                avg30 = stats.get('avg30', [0, 0])
                
                discount = 0
                if current_price > 0:
                    avg_price = avg30[0] if avg30[0] > 0 else avg30[1] if len(avg30) > 1 else 0
                    if avg_price > 0:
                        avg_price = avg_price / 100
                        discount = int(((avg_price - current_price) / avg_price) * 100)
                
                if current_price > 0 and asin and discount >= 5:
                    affiliate_link = f"https://www.amazon.{self.amazon_domain}/dp/{asin}?tag={self.amazon_tag}"
                    
                    parsed_products.append({
                        'asin': asin,
                        'title': title[:100],
                        'price': current_price,
                        'discount': max(0, discount),
                        'link': affiliate_link,
                        'is_lightning': False
                    })
                    
            except Exception as e:
                logger.error(f"Errore parsing prodotto: {e}")
                continue
        
        if parsed_products:
            parsed_products.sort(key=lambda x: x['discount'], reverse=True)
        
        best_products = parsed_products[:limit]
        logger.info(f"Processati {len(best_products)} prodotti validi")
        return best_products

    def format_product_message(self, product):
        title = product['title'][:100] + "..." if len(product['title']) > 100 else product['title']
        price = f"€{product['price']:.2f}"
        discount = int(product.get('discount', 0))
        is_lightning = product.get('is_lightning', False)
        
        if discount >= 50:
            emoji = "🔥"
        elif discount >= 30:
            emoji = "⚡"
        else:
            emoji = "💎"
        
        if is_lightning:
            urgency_messages = [
                "⏰ OFFERTA LAMPO - Termina tra poche ore!",
                "🚨 ATTENZIONE: Scorte limitate!",
                "⚡ SOLO PER OGGI - Disponibilità limitata!",
                "🔥 ULTIMI PEZZI - Affrettati!",
                "⏳ TEMPO LIMITATO - Non perdere l'occasione!"
            ]
            urgency = random.choice(urgency_messages)
            
            message = f"""{emoji} *OFFERTA LAMPO AMAZON* -{discount}%

{urgency}

📦 {title}

💰 *Prezzo: {price}*

🔥 [**ACQUISTA ORA**]({product['link']}) 🔥

#LightningDeal #OffertaLampo #Sconto{discount}"""
        else:
            message = f"""{emoji} *OFFERTA AMAZON* -{discount}%

📦 {title}

💰 *Prezzo: {price}*

🔥 [**ACQUISTA ORA**]({product['link']}) 🔥

#AmazonDeals #Offerte #Sconto{discount}"""
        
        return message

    async def send_product_to_channel(self, product):
        try:
            message = self.format_product_message(product)
            
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode='Markdown',
                disable_web_page_preview=False
            )
            
            self.published_asins.add(product['asin'])
            self.save_published_asins()
            
            deal_type = "Lightning" if product.get('is_lightning') else "Deal"
            logger.info(f"{deal_type} inviato: {product['asin']} | Tot: {len(self.published_asins)}")
            return True
            
        except TelegramError as e:
            logger.error(f"Errore Telegram: {e}")
            return False
        except Exception as e:
            logger.error(f"Errore generico: {e}")
            return False

    async def post_deals(self):
        logger.info("Cercando nuove offerte...")
        
        products = self.get_keepa_deals(limit=5)
        
        if not products:
            logger.warning("Nessun prodotto trovato")
            return
        
        product = products[0]
        success = await self.send_product_to_channel(product)
        
        if success:
            logger.info(f"Post pubblicato con successo!")
        else:
            logger.error(f"Errore pubblicazione post")

    def get_post_interval(self, hour):
        if (10 <= hour < 13) or (18 <= hour < 21):
            return 15
        else:
            return 30

    async def run_scheduler(self):
        logger.info("Scheduler avviato! Bot attivo 24/7")
        logger.info("Timing: 15 min (10-13, 18-21) | 30 min (altre ore)")
        logger.info("Lightning Deals + Browsing Deals attivi")
        
        last_post_time = None
        
        while True:
            try:
                now = datetime.now(self.timezone)
                current_time = now.strftime("%H:%M")
                hour = now.hour
                
                if now.minute == 0:
                    interval = self.get_post_interval(hour)
                    logger.info(f"Bot attivo - Ora: {current_time} | Intervallo: {interval} min")
                
                if 0 <= hour < 24:
                    post_interval = self.get_post_interval(hour)
                    
                    if last_post_time is None:
                        await self.post_deals()
                        last_post_time = now
                        logger.info(f"Prossimo post tra {post_interval} minuti")
                    else:
                        minutes_since_last = (now - last_post_time).total_seconds() / 60
                        
                        if minutes_since_last >= post_interval:
                            await self.post_deals()
                            last_post_time = now
                            next_interval = self.get_post_interval((now + timedelta(minutes=post_interval)).hour)
                            logger.info(f"Prossimo post tra {next_interval} minuti")
                
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Errore nel loop: {e}")
                await asyncio.sleep(300)

    async def test_connection(self):
        logger.info("Testando connessioni...")
        
        try:
            me = await self.bot.get_me()
            logger.info(f"Bot Telegram OK: @{me.username}")
        except Exception as e:
            logger.error(f"Errore bot Telegram: {e}")
            return False
        
        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text="Bot POTENZIATO avviato!\nLightning Deals + 7 categorie attive"
            )
            logger.info("Canale Telegram OK")
        except Exception as e:
            logger.error(f"Errore canale: {e}")
            return False
        
        try:
            products = self.get_keepa_deals(limit=1)
            if products:
                logger.info(f"Keepa API OK - Trovati {len(products)} prodotti")
            else:
                logger.warning("Keepa API: nessun prodotto")
        except Exception as e:
            logger.error(f"Errore Keepa API: {e}")
            return False
            
        return True

async def main():
    logger.info("Avvio Bot Telegram-Keepa POTENZIATO...")
    
    required_vars = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHANNEL_ID', 'KEEPA_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Variabili mancanti: {missing_vars}")
        return
    
    bot = TelegramKeepaBot()
    
    if await bot.test_connection():
        logger.info("Tutti i test superati! Avvio scheduler...")
        await bot.run_scheduler()
    else:
        logger.error("Test falliti. Controlla la configurazione.")

if __name__ == "__main__":
    asyncio.run(main())
