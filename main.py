#!/usr/bin/env python3
# نویسنده : میر سینا بنی هاشم
import os
import io
import random
from datetime import datetime

import aiohttp
import matplotlib.pyplot as plt
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "your_bot_token"
USDT_TO_TOMAN = 60000
BINANCE_TICKER_24H = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_TICKER_PRICE = "https://api.binance.com/api/v3/ticker/price"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
NAVASAN_API_KEY = "freeYwJ7BQFzue1UC2nnIAxRp207r79V"
NAVASAN_URL = f"http://api.navasan.tech/latest/?api_key={NAVASAN_API_KEY}"

CACHE = {}  # symbol -> {"times":[], "closes":[]}


async def fetch_json(url, params=None):
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, params=params, timeout=10) as r:
                r.raise_for_status()
                return await r.json()
    except:
        return None

async def get_top20_prices():
    data = await fetch_json(BINANCE_TICKER_24H)
    if not data: return []
    usdt = [t for t in data if t["symbol"].endswith("USDT")]
    usdt.sort(key=lambda x: float(x.get("quoteVolume",0)), reverse=True)
    return [{"symbol": t["symbol"], "price": float(t["lastPrice"])} for t in usdt[:20]]

async def get_price_for_symbol(symbol):
    data = await fetch_json(BINANCE_TICKER_PRICE, params={"symbol": symbol})
    if data and "price" in data:
        return float(data["price"])
    return None

async def generate_chart(symbol, interval="1h", limit=30):
    data = await fetch_json(BINANCE_KLINES, params={"symbol": symbol,"interval": interval,"limit": limit})
    if not data:
        raise RuntimeError("Cannot fetch Klines")
    times = [datetime.fromtimestamp(c[0]/1000) for c in data]
    closes = [float(c[4]) for c in data]
    CACHE[symbol] = {"times": times, "closes": closes}

    fig, ax = plt.subplots(figsize=(6,4))
    ax.plot(times, closes)
    ax.set_title(symbol)
    ax.set_xlabel("Time")
    ax.set_ylabel("Price (USDT)")
    fig.autofmt_xdate()
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf

async def get_other_prices():
    data = await fetch_json(NAVASAN_URL)
    if not data: return {}
    return data


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/prices → نمایش ۲۰ ارز برتر\n/chart → نمودار رندوم\n/other → ارزهای دیگر")


async def prices_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = await get_top20_prices()
    if not items:
        await update.message.reply_text("⚠️ Cannot fetch prices")
        return

    rows = []
    for item in items:
        symbol = item["symbol"]
        price_toman = item["price"]*USDT_TO_TOMAN
        buttons = [
            InlineKeyboardButton(symbol, callback_data=f"price_{symbol}"),
            InlineKeyboardButton(f"{int(price_toman):,} تومان", callback_data=f"price_{symbol}"),
            InlineKeyboardButton(f"{item['price']:.6f} USDT", callback_data=f"price_{symbol}"),
        ]
        rows.append(buttons)
    markup = InlineKeyboardMarkup(rows)
    await update.message.reply_text("💹 ۲۰ ارز برتر", reply_markup=markup)

async def handle_price_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sym = query.data.split("_",1)[1]
    price = await get_price_for_symbol(sym)
    if not price:
        await query.message.reply_text(f"⚠️ Cannot fetch {sym}")
        return
    toman = price*USDT_TO_TOMAN
    await query.message.reply_text(f"{sym}\nقیمت: {price:.6f} USDT\n≈ {int(toman):,} تومان")

# ====== نمودار رندوم ======
async def chart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = await get_top20_prices()
    if not items:
        await update.message.reply_text("⚠️ Cannot fetch prices")
        return
    choice = random.choice(items)
    sym = choice["symbol"]
    buf = await generate_chart(sym)

    
    cached = CACHE[sym]
    times = cached["times"]
    closes = cached["closes"]
    labels = ["فعلی", "دیروز", "هفته پیش", "ماه پیش"]
    indices = [-1, -24 if len(closes)>24 else 0, -168 if len(closes)>168 else 0, -720 if len(closes)>720 else 0]

    buttons = []
    for l, idx in zip(labels, indices):
        idx = idx if idx>=0 else len(closes)+idx
        idx = max(0,min(idx,len(closes)-1))
        buttons.append([InlineKeyboardButton(f"{l}: {closes[idx]:.6f} USDT", callback_data=f"chartinfo_{sym}_{l}")])

    markup = InlineKeyboardMarkup(buttons)
    await context.bot.send_photo(chat_id=update.effective_chat.id, photo=buf, caption=f"{sym}", reply_markup=markup)

async def handle_chartinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, sym, label = query.data.split("_",2)
    cached = CACHE.get(sym)
    if not cached:
        await query.message.reply_text("⚠️ No cached data")
        return
    closes = cached["closes"]
    times = cached["times"]
    idx_map = {"فعلی": -1, "دیروز": -24, "هفته پیش": -168, "ماه پیش": -720}
    idx = idx_map.get(label,-1)
    idx = idx if idx>=0 else len(closes)+idx
    idx = max(0,min(idx,len(closes)-1))
    price_usdt = closes[idx]
    price_toman = price_usdt*USDT_TO_TOMAN
    dt = times[idx]
    await query.message.reply_text(f"{sym} - {label}\nقیمت: {price_usdt:.6f} USDT ≈ {int(price_toman):,} تومان\nزمان: {dt}")

async def other_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = await get_other_prices()
    if not data:
        await update.message.reply_text("⚠️ Cannot fetch other currencies")
        return

    rows = []
    for key, val in data.items():
        try:
            value = val.get("value")
            change = val.get("change", 0)
            date = val.get("date", "")
            buttons = [
                InlineKeyboardButton(key, callback_data=f"other_{key}"),
                InlineKeyboardButton(f"{value} تومان", callback_data=f"other_{key}"),
                InlineKeyboardButton(f"Δ {change}", callback_data=f"other_{key}"),
            ]
            rows.append(buttons)
        except:
            continue
    markup = InlineKeyboardMarkup(rows)
    await update.message.reply_text("💱 ارزهای دیگر", reply_markup=markup)

async def handle_other_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sym = query.data.split("_",1)[1]
    data = await get_other_prices()
    if sym not in data:
        await query.message.reply_text(f"⚠️ Cannot fetch {sym}")
        return
    val = data[sym]
    value = val.get("value")
    change = val.get("change",0)
    date = val.get("date","")
    await query.message.reply_text(f"{sym}\nقیمت: {value} تومان\nتغییر نسبت به دیروز: {change}\nتاریخ: {date}")


def main():
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN=="PUT_YOUR_TOKEN_HERE":
        raise RuntimeError("Set TELEGRAM_TOKEN")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("prices", prices_cmd))
    app.add_handler(CommandHandler("chart", chart_cmd))
    app.add_handler(CommandHandler("other", other_cmd))
    app.add_handler(CallbackQueryHandler(handle_price_button, pattern="^price_"))
    app.add_handler(CallbackQueryHandler(handle_chartinfo, pattern="^chartinfo_"))
    app.add_handler(CallbackQueryHandler(handle_other_button, pattern="^other_"))
    print("🚀 Bot started...")
    app.run_polling()

if __name__=="__main__":
    main()
