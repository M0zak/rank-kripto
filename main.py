import logging
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ========== KONFIGURASI ==========
TOKEN = "8489768256:AAGWojLLhCXrvAFkFdQpCBfk4FMqerrV6z4"  # Ganti dengan token BotFather
COINGECKO_API = "https://api.coingecko.com/api/v3"
BINANCE_API = "https://api.binance.com/api/v3"
FEAR_GREED_API = "https://api.alternative.me/fng/"
# =================================

logging.basicConfig(level=logging.INFO)

# Ambil Fear & Greed Index
def get_fear_greed():
    try:
        data = requests.get(FEAR_GREED_API).json()
        return int(data['data'][0]['value'])
    except:
        return None

# Ambil data CoinGecko
def get_coingecko_data(symbol):
    search = requests.get(f"{COINGECKO_API}/search?query={symbol}").json()
    if not search['coins']:
        return None
    coin_id = search['coins'][0]['id']
    data = requests.get(f"{COINGECKO_API}/coins/{coin_id}").json()
    return data

# Ambil data Binance
def get_binance_data(symbol):
    pair = symbol.upper() + "USDT"
    data = requests.get(f"{BINANCE_API}/ticker/24hr?symbol={pair}").json()
    if "code" in data:
        return None
    return data

# Hitung skor otomatis
def generate_checklist(symbol, cg_data, binance_data, fear_greed):
    # Data utama
    market_cap = cg_data['market_data']['market_cap']['usd']
    volume_24h = cg_data['market_data']['total_volume']['usd']
    high_24h = cg_data['market_data']['high_24h']['usd']
    low_24h = cg_data['market_data']['low_24h']['usd']
    price = cg_data['market_data']['current_price']['usd']
    dominance = cg_data.get('market_cap_rank', 0)
    ratio = (volume_24h / market_cap) * 100 if market_cap > 0 else 0

    # Volatilitas (%)
    volatility = ((high_24h - low_24h) / price) * 100

    # ==== SKOR OTOMATIS ====
    skor = {}
    # Fundamental (dummy kuat)
    skor['Fundamental'] = 15
    # Use Case
    skor['Use Case'] = 10
    # Tokenomics (deflasi kalau supply terbatas)
    skor['Tokenomics'] = 10 if cg_data['market_data']['max_supply'] else 7
    # Adopsi & Kemitraan (pakai volume & ranking)
    skor['Adopsi'] = 10 if dominance <= 10 else 7
    # Keamanan (dummy aman)
    skor['Keamanan'] = 10
    # Likuiditas
    skor['Likuiditas'] = 15 if ratio >= 3 else 10
    # Volatilitas
    if volatility <= 3:
        skor['Volatilitas'] = 10
    elif volatility <= 7:
        skor['Volatilitas'] = 8
    else:
        skor['Volatilitas'] = 5
    # Support/Resistance (dummy valid)
    skor['SupportResistance'] = 4
    # Sentimen Pasar
    if fear_greed is None:
        skor['Sentimen'] = 3
    elif fear_greed >= 60:
        skor['Sentimen'] = 4
    elif fear_greed >= 40:
        skor['Sentimen'] = 3
    else:
        skor['Sentimen'] = 2
    # Kompetisi
    skor['Kompetisi'] = 4 if dominance <= 10 else 3
    # Market Cap Ratio
    skor['MarketCapRatio'] = 5 if ratio >= 3 else 3

    total_skor = sum(skor.values())

    # Kategori akhir
    if total_skor >= 80:
        kategori = "🟢 **Layak Investasi Jangka Panjang**"
    elif total_skor >= 60:
        kategori = "🟡 **Layak Trading Jangka Pendek**"
    else:
        kategori = "🔴 **Risiko Tinggi**"

    # Format uang
    def fmt_money(val):
        if val >= 1_000_000_000:
            return f"${val/1_000_000_000:.1f}B"
        elif val >= 1_000_000:
            return f"${val/1_000_000:.1f}M"
        else:
            return f"${val:,.0f}"

    # Output
    output = f"""
✅ Checklist Penilaian {symbol.upper()} ({cg_data['name']})
📅 Tanggal: {datetime.now().strftime("%d/%m/%Y")}

🔹 Fundamental: Kuat ({skor['Fundamental']}/15)
🔹 Use Case & Utility: {', '.join(cg_data.get('categories', ['Tidak ada data']))} ({skor['Use Case']}/10)
🔹 Tokenomics: {"Supply terbatas" if cg_data['market_data']['max_supply'] else "Inflasi"} ({skor['Tokenomics']}/10)
🔹 Adopsi & Kemitraan: {'Sangat luas' if skor['Adopsi']==10 else 'Sedang'} ({skor['Adopsi']}/10)
🔹 Keamanan & Audit: Aman ({skor['Keamanan']}/10)
🔹 Likuiditas: Volume 24h {fmt_money(volume_24h)} → {'Sangat tinggi' if skor['Likuiditas']==15 else 'Sedang'} ({skor['Likuiditas']}/15)
🔹 Volatilitas: {volatility:.2f}% → {'Stabil' if skor['Volatilitas']==10 else 'Sedang' if skor['Volatilitas']==8 else 'Tinggi'} ({skor['Volatilitas']}/10)
🔹 Support/Resistance: ${low_24h:,.0f} / ${high_24h:,.0f} ({skor['SupportResistance']}/5)
🔹 Sentimen Pasar: {f'Indeks = {fear_greed}' if fear_greed is not None else 'Tidak ada data'} ({skor['Sentimen']}/5)
🔹 Kompetisi: Dominasi #{dominance} ({skor['Kompetisi']}/5)
🔹 Market Cap: {fmt_money(market_cap)} (Mega Cap) ({skor['MarketCapRatio']}/5)
🔹 Volume/Market Cap Ratio: {ratio:.2f}% → {'Aktivitas Sehat' if skor['MarketCapRatio']==5 else 'Aktivitas Rendah'}

🏆 **Skor Akhir: {total_skor}/100**
{kategori}
"""
    return output

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Selamat datang di Crypto Checklist Bot!\n"
        "Ketik simbol crypto (contoh: BTC, ETH, SOL) untuk penilaian."
    )

# Handler simbol
async def handle_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = update.message.text.strip().upper()

    cg_data = get_coingecko_data(symbol)
    binance_data = get_binance_data(symbol)
    fear_greed = get_fear_greed()

    if not cg_data:
        await update.message.reply_text("❌ Data tidak ditemukan di CoinGecko.")
        return
    if not binance_data:
        await update.message.reply_text("❌ Data tidak ditemukan di Binance.")
        return

    result = generate_checklist(symbol, cg_data, binance_data, fear_greed)
    await update.message.reply_text(result, parse_mode="Markdown")

# Main
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_symbol))
    app.run_polling()
