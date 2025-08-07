import os
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# ==== API KEYS ====
ETHERSCAN_API_KEY = "GYU78JKH6V2IM7PHNTFFT3H4VU8NW9KC2R"
CRYPTOPANIC_API_KEY = "15840a09ec6bff979ba9e92500e2d35eb61f0c65"

# ==== API URLs ====
COINGECKO = "https://api.coingecko.com/api/v3"
FEAR_GREED = "https://api.alternative.me/fng/"
ETHERSCAN_API = "https://api.etherscan.io/api"
BSCSCAN_API = "https://api.bscscan.com/api"
CRYPTOPANIC_API = "https://cryptopanic.com/api/v1/posts/"

# ==== LOGGING ====
logging.basicConfig(level=logging.INFO)

# ==== HELPER ====
def fmt_money(val):
    if val >= 1_000_000_000:
        return f"${val/1_000_000_000:.1f}B"
    elif val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    else:
        return f"${val:,.0f}"

def get_coingecko(symbol):
    search = requests.get(f"{COINGECKO}/search?query={symbol}").json()
    if not search['coins']:
        return None
    coin_id = search['coins'][0]['id']
    data = requests.get(f"{COINGECKO}/coins/{coin_id}").json()
    return data

def get_support_resistance(coin_id):
    try:
        data = requests.get(f"{COINGECKO}/coins/{coin_id}/market_chart?vs_currency=usd&days=90").json()
        prices = [p[1] for p in data.get("prices", [])]
        if not prices:
            return None, None
        return min(prices), max(prices)
    except:
        return None, None

def get_holders(address, chain="eth"):
    try:
        if chain == "eth":
            url = f"{ETHERSCAN_API}?module=token&action=tokenholderlist&contractaddress={address}&apikey={ETHERSCAN_API_KEY}"
        else:
            url = f"{BSCSCAN_API}?module=token&action=tokenholderlist&contractaddress={address}&apikey={ETHERSCAN_API_KEY}"
        data = requests.get(url, timeout=10).json()
        return len(data.get("result", []))
    except:
        return None

def get_sentiment_from_cryptopanic(symbol):
    try:
        r = requests.get(CRYPTOPANIC_API, params={
            "auth_token": CRYPTOPANIC_API_KEY,
            "currencies": symbol,
            "filter": "important"
        }).json()
        posts = r.get("results", [])
        if not posts:
            return None
        positive = sum(1 for p in posts if p.get("votes", {}).get("positive", 0) > p.get("votes", {}).get("negative", 0))
        negative = sum(1 for p in posts if p.get("votes", {}).get("negative", 0) > p.get("votes", {}).get("positive", 0))
        return positive, negative
    except:
        return None

def get_certik_audit(symbol):
    try:
        url = f"https://skynet.certik.com/projects/{symbol.lower()}"
        html = requests.get(url, timeout=10).text
        soup = BeautifulSoup(html, "html.parser")
        score_elem = soup.find("div", {"class": "score"})
        score = int(score_elem.text.strip()) if score_elem else None
        audit_status = "Audit Completed" if "Audit Completed" in html else "No Audit"
        return score, audit_status
    except:
        return None, "No Audit"

# ==== SCORING ====
def generate_checklist(symbol, cg_data, support, resistance):
    market_cap = cg_data['market_data']['market_cap']['usd']
    volume_24h = cg_data['market_data']['total_volume']['usd']
    high_24h = cg_data['market_data']['high_24h']['usd']
    low_24h = cg_data['market_data']['low_24h']['usd']
    price = cg_data['market_data']['current_price']['usd']
    ratio = (volume_24h / market_cap) * 100 if market_cap > 0 else 0
    volatility = ((high_24h - low_24h) / price) * 100

    skor = {}

    # Fundamental
    genesis = cg_data.get("genesis_date", "")
    if genesis:
        age_years = (datetime.now() - datetime.strptime(genesis, "%Y-%m-%d")).days / 365
        skor['Fundamental'] = 15 if age_years > 3 else 10 if age_years > 1 else 6
    else:
        skor['Fundamental'] = 8

    # Use Case
    categories = cg_data.get('categories', [])
    skor['UseCase'] = 10 if len(categories) > 3 else 8 if categories else 5

    # Tokenomics
    max_supply = cg_data['market_data']['max_supply']
    skor['Tokenomics'] = 10 if max_supply else 7

    # Adopsi
    contract_address = cg_data.get("platforms", {}).get("ethereum") or cg_data.get("platforms", {}).get("binance-smart-chain")
    if contract_address:
        holders = get_holders(contract_address, "bsc" if "binance" in str(cg_data["platforms"]).lower() else "eth")
        skor['Adopsi'] = 10 if holders and holders > 1_000_000 else 8 if holders and holders > 100_000 else 5
    else:
        skor['Adopsi'] = 8

    # Keamanan
    certik_score, audit_status = get_certik_audit(cg_data['id'])
    if audit_status == "Audit Completed":
        skor['Keamanan'] = 10 if certik_score and certik_score >= 80 else 8 if certik_score and certik_score >= 60 else 6
    else:
        skor['Keamanan'] = 5

    # Likuiditas
    skor['Likuiditas'] = 15 if ratio >= 3 else 10 if ratio >= 1 else 8

    # Volatilitas
    skor['Volatilitas'] = 10 if volatility <= 3 else 8 if volatility <= 7 else 5

    # Support/Resistance
    skor['SupportResistance'] = 5 if support and resistance else 3

    # Sentimen
    sent_data = get_sentiment_from_cryptopanic(symbol)
    if sent_data:
        positive, negative = sent_data
        skor['Sentimen'] = 4 if positive > negative else 2
    else:
        skor['Sentimen'] = 3

    # Kompetisi
    rank = cg_data.get('market_cap_rank', 0)
    skor['Kompetisi'] = 4 if rank <= 10 else 3

    # MarketCap Ratio
    skor['MarketCapRatio'] = 5 if ratio >= 3 else 3

    total_skor = sum(skor.values())

    if total_skor >= 80:
        kategori = "🟢 **Layak Investasi Jangka Panjang**"
        alasan = "Proyek ini memiliki fundamental, adopsi, dan likuiditas yang sangat kuat, cocok untuk strategi hold jangka panjang."
    elif total_skor >= 60:
        kategori = "🟡 **Layak Trading Jangka Pendek**"
        alasan = "Beberapa faktor seperti adopsi, likuiditas, keamanan, atau sentimen pasar belum maksimal."
    else:
        kategori = "🔴 **Risiko Tinggi**"
        alasan = "Proyek ini memiliki kelemahan signifikan pada fundamental, likuiditas, atau keamanan."

    output = f"""
✅ Checklist Penilaian {symbol.upper()} ({cg_data['name']})
📅 Tanggal: {datetime.now().strftime("%d/%m/%Y")}

🛠️ Fundamental: ({skor['Fundamental']}/15)
💡 Use Case & Utility: ({skor['UseCase']}/10)
📊 Tokenomics: ({skor['Tokenomics']}/10)
🌍 Adopsi & Kemitraan: ({skor['Adopsi']}/10)
🛡️ Keamanan & Audit: ({skor['Keamanan']}/10)
💱 Likuiditas: ({skor['Likuiditas']}/15)
📉 Volatilitas: {volatility:.2f}% ({skor['Volatilitas']}/10)
📈 Support: ${support:,.2f} / Resistance: ${resistance:,.2f} ({skor['SupportResistance']}/5)
📰 Sentimen Pasar: ({skor['Sentimen']}/5)
⚔️ Kompetisi: ({skor['Kompetisi']}/5)
🏦 Market Cap: {fmt_money(market_cap)} ({skor['MarketCapRatio']}/5)
🔄 Volume/Market Cap Ratio: {ratio:.2f}%

🏆 **Skor Akhir: {total_skor}/100**
{kategori}
💬 {alasan}
"""
    return output, skor, volatility, market_cap, volume_24h, ratio

# ==== HANDLERS ====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Masukkan simbol crypto (contoh: BTC, ETH, SOL)")

async def handle_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = update.message.text.strip().upper()
    cg_data = get_coingecko(symbol)
    if not cg_data:
        await update.message.reply_text("❌ Data tidak ditemukan.")
        return

    support, resistance = get_support_resistance(cg_data['id'])
    checklist, skor, volatility, market_cap, volume_24h, ratio = generate_checklist(symbol, cg_data, support, resistance)

    context.user_data.update({
        'last_symbol': symbol,
        'cg_data': cg_data,
        'skor': skor,
        'support': support,
        'resistance': resistance,
        'volatility': volatility,
        'market_cap': market_cap,
        'volume_24h': volume_24h,
        'ratio': ratio
    })

    keyboard = [[InlineKeyboardButton("📄 Lihat Penjelasan", callback_data="explain")]]
    await update.message.reply_text(checklist, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "explain":
        s = context.user_data['skor']
        cg_data = context.user_data['cg_data']
        support = context.user_data['support']
        resistance = context.user_data['resistance']
        volatility = context.user_data['volatility']
        ratio = context.user_data['ratio']

        penjelasan = f"""
📄 Penjelasan Penilaian {context.user_data['last_symbol'].upper()} ({cg_data['name']})
1. Fundamental ({s['Fundamental']}/15) → Berdasarkan umur proyek sejak {cg_data.get('genesis_date','-')}.
2. Use Case ({s['UseCase']}/10) → {', '.join(cg_data.get('categories', ['Tidak ada data']))}.
3. Tokenomics ({s['Tokenomics']}/10) → {"Supply terbatas" if cg_data['market_data']['max_supply'] else "Inflasi"}.
4. Adopsi ({s['Adopsi']}/10) → Berdasarkan jumlah holder dari blockchain explorer.
5. Keamanan ({s['Keamanan']}/10) → Berdasarkan audit CertiK.
6. Likuiditas ({s['Likuiditas']}/15) → Volume/MarketCap ratio = {ratio:.2f}%.
7. Volatilitas ({s['Volatilitas']}/10) → Range harga 24 jam sekitar {volatility:.2f}%.
8. Support/Resistance ({s['SupportResistance']}/5) → Support: ${support:,.2f}, Resistance: ${resistance:,.2f}.
9. Sentimen ({s['Sentimen']}/5) → Berdasarkan berita CryptoPanic.
10. Kompetisi ({s['Kompetisi']}/5) → Berdasarkan ranking market cap.
11. Market Cap Ratio ({s['MarketCapRatio']}/5) → Aktivitas perdagangan sehat.
"""
        await query.message.reply_text(penjelasan)

# ==== MAIN ====
if __name__ == "__main__":
    TELEGRAM_TOKEN = "8489768256:AAGWojLLhCXrvAFkFdQpCBfk4FMqerrV6z4"
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_symbol))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.run_polling()
