# 🌌 Vucciaro Universe Bot

Sistema automatizzato per pubblicazione offerte Amazon su Telegram.

## 🎯 Strategia API Mix

- **60% Lightning Deals** - Offerte lampo Amazon validate
- **30% Browsing Deals** - Offerte filtrate per categoria
- **10% Best Sellers** - Prodotti più venduti

## 📊 Configurazione

### Posting
- **Frequenza**: 1 post ogni 40 minuti per canale
- **Orario**: 07:00 - 23:00
- **Canali**: @VucciaroTech + @VucciaroModa
- **Totale**: ~24 post/giorno per canale = 48 post/giorno totali

### Filtri Qualità

**Tech:**
- Sconto minimo: 15%
- Rating: ≥4.0 stelle
- Recensioni: ≥20
- Prezzo max: €500

**Moda:**
- Sconto minimo: 20%
- Rating: ≥4.0 stelle  
- Recensioni: ≥15
- Prezzo max: €300

## 🚀 Deploy su Railway

Railway è già collegato e fa auto-deploy ad ogni push!

### Variabili Environment (già configurate)

✅ Telegram, Keepa, Amazon, Schedule, Filtri

### Monitoraggio

Vai su Railway → View Logs per vedere:
