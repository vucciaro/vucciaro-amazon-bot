# 🌌 VUCCIARO UNIVERSE

Sistema automatizzato di pubblicazione offerte Amazon su Telegram

## 🎯 CANALI ATTIVI

1. **🖥️ @VucciaroTech** → Elettronica, smartphone, informatica
2. **👗 @VucciaroModa** → Moda donna, moda uomo, accessori

## 🚀 INSTALLAZIONE RAPIDA

### 1. Clona questo repository
```bash
git clone https://github.com/tuo-username/vucciaro-bot
cd vucciaro-bot
```

### 2. Configura le variabili su Railway

Vai su Railway → Variables e aggiungi:

```
TELEGRAM_BOT_TOKEN=8085826306:AAFh9r0BfIOqZSZQpPFPPmmzMS85K08nR2A
KEEPA_API_KEY=la_tua_key
AMAZON_TAG=vucciaro-21
TECH_CHANNEL_ID=-1002956324651
MODA_CHANNEL_ID=-1003108272082
POST_INTERVAL_MINUTES=20
START_HOUR=7
END_HOUR=23
MIN_DISCOUNT=20
MIN_RATING=4.0
MIN_REVIEWS=20
LOG_LEVEL=INFO
```

### 3. Deploy

Railway farà il deploy automaticamente! Verifica i logs per confermare.

## ⚙️ COME FUNZIONA

- **Rotazione**: Il bot alterna tra Tech e Moda ogni 20 minuti
- **Orario**: Pubblica dalle 07:00 alle 23:00
- **Filtri**: Solo prodotti con sconto ≥20%, rating ≥4.0, recensioni ≥20
- **Deduplica**: Nessun prodotto viene ripubblicato entro 48h
- **Cache**: Le offerte Keepa sono salvate per 6h (risparmio token)

## 📊 STATISTICHE

- **48 post/giorno** (24 per canale)
- **~200 token Keepa/giorno** (<1% del limite)
- **Consumo ottimizzato** grazie alla cache

## 🛠️ PERSONALIZZAZIONE

Modifica le variabili su Railway per cambiare:
- Frequenza post: `POST_INTERVAL_MINUTES`
- Orari: `START_HOUR` e `END_HOUR`
- Filtri: `MIN_DISCOUNT`, `MIN_RATING`, `MIN_REVIEWS`

## 📞 SUPPORTO

Per problemi o domande, consulta i logs Railway o apri una issue su GitHub.

---

**Made with ❤️ by Vucciaro Universe**
