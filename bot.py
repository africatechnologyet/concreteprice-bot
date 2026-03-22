import os, logging
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)

GRADES = ["C5","C10","C15","C20","C25","C30","C35","C40","C45","C50","C60"]
DEFAULT_UNIT_COSTS = {
    "Cement":16.08,"Sand":3.15,"Gravel 00":2.47,
    "Gravel 01":1.89,"Gravel 02":2.40,"Water":0.50,"Chemicals":102.00
}
MIX_QTY = {
    "Cement":  [190,270,265,280,300,320,350,390,460,500,560],
    "Sand":    [341,500,432.1,432,700,665,723,700,655,610,590],
    "Gravel 00":[341,530,432.1,432,310,245,188,200,235,200,210],
    "Gravel 01":[494,300,190.16,190,335,330,351,320,301,310,320],
    "Gravel 02":[741,700,846,760,635,670,652,645,645,640,640],
    "Water":   [120,150,150,115,140,145,157,145,150,150,150],
    "Chemicals":[1.54,1.54,1.54,1.54,6.0,6.4,7.0,8.2,9.2,10.0,11.2],
}
FIXED_COSTS = {
    "Labor":      [160,160,160,160,200,147,160,200,200,200,200],
    "Overhead":   [160,160,160,160,200,147,160,200,200,200,200],
    "Reject 2.5%":[264,264,264,264,264,264,264,264,264,264,264],
    "Truck":      [400,400,400,400,400,400,400,400,400,400,400],
    "Fuel":       [317,260,200,366,200,200,260,200,200,353,244],
    "Pump":       [400,0,0,550,234,234,600,341,366,400,705],
}
DEFAULT_MARGINS = {
    "C5":0.13,"C10":0.13,"C15":0.10,"C20":0.13,"C25":0.13,
    "C30":0.13,"C35":0.13,"C40":0.11,"C45":0.13,"C50":0.13,"C60":0.13
}

def grade_index(g): return GRADES.index(g)

def calc_production_cost(grade, uc):
    idx = grade_index(grade)
    bd, mat = {}, 0
    for m, ql in MIX_QTY.items():
        q=ql[idx]; c=q*uc[m]; bd[m]={"qty":q,"unit_cost":uc[m],"cost":c}; mat+=c
    fix = 0
    for item, cl in FIXED_COSTS.items():
        c=cl[idx]; bd[item]={"cost":c}; fix+=c
    return bd, mat+fix

def calc_sale_price(grade, uc, margin=None):
    bd, pc = calc_production_cost(grade, uc)
    if margin is None: margin = DEFAULT_MARGINS[grade]
    sp = pc*(1+margin)
    return {"breakdown":bd,"prod_cost":pc,"margin":margin,"sale_price":sp,"profit":sp-pc}

def fmt_summary(grade, r):
    return (f"*{grade} - Price Summary*\n```\n"
            f"Prod Cost:  ETB {r['prod_cost']:>10,.2f}\n"
            f"Margin:         {r['margin']*100:.1f}%\n"
            f"Sale Price: ETB {r['sale_price']:>10,.2f}\n"
            f"Profit:     ETB {r['profit']:>10,.2f}\n```")

def fmt_breakdown(grade, r):
    bd = r["breakdown"]
    lines = [f"*{grade} - Full Breakdown*\n```",
             f"{'Item':<14}{'Qty':>9}{'Rate':>8}{'Cost':>12}","-"*44]
    for m in MIX_QTY:
        d=bd[m]; lines.append(f"{m:<14}{d['qty']:>9.2f}{d['unit_cost']:>8.2f}{d['cost']:>12,.2f}")
    lines.append("-"*44)
    for item in FIXED_COSTS:
        lines.append(f"{item:<14}{'':>9}{'':>8}{bd[item]['cost']:>12,.2f}")
    lines += ["-"*44,
              f"{'Prod Cost':<30}{r['prod_cost']:>14,.2f}",
              f"{'Margin':<30}{r['margin']*100:>13.1f}%",
              f"{'Sale Price':<30}{r['sale_price']:>14,.2f}","```"]
    return "\n".join(lines)

def fmt_margins(grade, uc):
    _, pc = calc_production_cost(grade, uc)
    lines = [f"*{grade} - All Margins*\n```",
             f"{'Margin':<10}{'Sale Price':>16}{'Profit':>14}","-"*42]
    for m in [0.10,0.11,0.12,0.13]:
        sp=pc*(1+m); tag=" <--" if m==DEFAULT_MARGINS[grade] else ""
        lines.append(f"{m*100:.0f}%{'':<7}{sp:>16,.2f}{sp-pc:>14,.2f}{tag}")
    lines.append("```")
    return "\n".join(lines)

(MAIN_MENU,SELECT_GRADE,GRADE_ACTION,
 ENTER_MARGIN,SELECT_MATERIAL,ENTER_COST) = range(6)

def mmk():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Get Sale Price", callback_data="menu_price")],
        [InlineKeyboardButton("Update Unit Costs", callback_data="menu_costs")],
        [InlineKeyboardButton("All Margins Table", callback_data="menu_margins")],
        [InlineKeyboardButton("Reset Unit Costs", callback_data="menu_reset")],
    ])

def gk(pfx):
    rows,row=[],[]
    for g in GRADES:
        row.append(InlineKeyboardButton(g, callback_data=pfx+"_"+g))
        if len(row)==4: rows.append(row); row=[]
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("Main Menu", callback_data="goto_main")])
    return InlineKeyboardMarkup(rows)

def gak(grade):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Price Summary", callback_data="summary_"+grade)],
        [InlineKeyboardButton("Full Breakdown", callback_data="breakdown_"+grade)],
        [InlineKeyboardButton("Custom Margin", callback_data="custom_"+grade)],
        [InlineKeyboardButton("Back", callback_data="menu_price"),
         InlineKeyboardButton("Main Menu", callback_data="goto_main")],
    ])

def mk():
    rows=[[InlineKeyboardButton(m, callback_data="setcost_"+m)] for m in DEFAULT_UNIT_COSTS]
    rows.append([InlineKeyboardButton("Main Menu", callback_data="goto_main")])
    return InlineKeyboardMarkup(rows)

def get_uc(ctx): return ctx.user_data.get("unit_costs", dict(DEFAULT_UNIT_COSTS))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = "Concrete Price Calculator\nGrades C5-C60 | Prices in ETB per m3"
    if update.message:
        await update.message.reply_text(text, reply_markup=mmk())
    else:
        await update.callback_query.edit_message_text(text, reply_markup=mmk())
    return MAIN_MENU

async def mmh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); d=q.data
    if d=="menu_price":
        await q.edit_message_text("Select grade:", reply_markup=gk("price")); return SELECT_GRADE
    elif d=="menu_margins":
        await q.edit_message_text("Select grade:", reply_markup=gk("margins")); return SELECT_GRADE
    elif d=="menu_costs":
        uc=get_uc(context)
        txt="Current Unit Costs (ETB)\n\n"+"\n".join(m+": "+str(c) for m,c in uc.items())+"\n\nSelect material:"
        await q.edit_message_text(txt, reply_markup=mk()); return SELECT_MATERIAL
    elif d=="menu_reset":
        context.user_data["unit_costs"]=dict(DEFAULT_UNIT_COSTS)
        await q.edit_message_text("Costs reset.", reply_markup=mmk()); return MAIN_MENU
    elif d=="goto_main": return await start(update, context)

async def sgh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); d=q.data
    if d=="goto_main": return await start(update, context)
    if d.startswith("price_"):
        grade=d.split("_",1)[1]; context.user_data["grade"]=grade
        await q.edit_message_text(grade+" - Choose:", reply_markup=gak(grade)); return GRADE_ACTION
    elif d.startswith("margins_"):
        grade=d.split("_",1)[1]
        await q.edit_message_text(fmt_margins(grade,get_uc(context)),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Back",callback_data="menu_margins"),
                InlineKeyboardButton("Main Menu",callback_data="goto_main")]])); return SELECT_GRADE
    elif d in ("menu_price","menu_margins"):
        pfx="price" if d=="menu_price" else "margins"
        await q.edit_message_text("Select grade:", reply_markup=gk(pfx)); return SELECT_GRADE

async def gah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); d=q.data; uc=get_uc(context)
    if d=="goto_main": return await start(update, context)
    if d=="menu_price":
        await q.edit_message_text("Select grade:", reply_markup=gk("price")); return SELECT_GRADE
    if d.startswith("summary_"):
        grade=d.split("_",1)[1]
        await q.edit_message_text(fmt_summary(grade,calc_sale_price(grade,uc)), reply_markup=gak(grade)); return GRADE_ACTION
    elif d.startswith("breakdown_"):
        grade=d.split("_",1)[1]
        await q.edit_message_text(fmt_breakdown(grade,calc_sale_price(grade,uc)), reply_markup=gak(grade)); return GRADE_ACTION
    elif d.startswith("custom_"):
        grade=d.split("_",1)[1]; context.user_data["grade"]=grade
        await q.edit_message_text("Enter margin % for "+grade+" (e.g. 12):"); return ENTER_MARGIN

async def emh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    grade=context.user_data.get("grade")
    try:
        m=float(update.message.text.strip().replace("%",""))/100
        if not (0<m<2): raise ValueError
    except ValueError:
        await update.message.reply_text("Enter a number between 1-100."); return ENTER_MARGIN
    await update.message.reply_text(fmt_summary(grade,calc_sale_price(grade,get_uc(context),m)), reply_markup=gak(grade))
    return GRADE_ACTION

async def smh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); d=q.data
    if d=="goto_main": return await start(update, context)
    if d.startswith("setcost_"):
        mat=d[len("setcost_"):]; context.user_data["material"]=mat
        await q.edit_message_text(mat+"\nCurrent: ETB "+str(get_uc(context)[mat])+"\n\nEnter new cost in ETB:"); return ENTER_COST

async def ech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mat=context.user_data.get("material")
    try:
        c=float(update.message.text.strip())
        if c<0: raise ValueError
    except ValueError:
        await update.message.reply_text("Enter a valid positive number."); return ENTER_COST
    uc=get_uc(context); old=uc[mat]; uc[mat]=c; context.user_data["unit_costs"]=uc
    await update.message.reply_text(mat+" updated: ETB "+str(old)+" to ETB "+str(c), reply_markup=mmk())
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. /start to restart.")
    return ConversationHandler.END

async def webhook_handler(request):
    data = await request.json()
    update = Update.de_json(data, request.app["ptb"].bot)
    await request.app["ptb"].process_update(update)
    return web.Response(text="ok")

async def health(request):
    return web.Response(text="ok")

async def on_startup(app):
    ptb = app["ptb"]
    await ptb.initialize()
    await ptb.bot.set_webhook(app["webhook_url"]+"/webhook")
    logging.info("Webhook set OK - bot ready")

async def on_cleanup(app):
    await app["ptb"].shutdown()

def main():
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    WEBHOOK_URL = os.environ["WEBHOOK_URL"]
    PORT = int(os.environ.get("PORT", 10000))
    logging.info("Starting on port "+str(PORT))

    ptb = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU:       [CallbackQueryHandler(mmh)],
            SELECT_GRADE:    [CallbackQueryHandler(sgh)],
            GRADE_ACTION:    [CallbackQueryHandler(gah)],
            ENTER_MARGIN:    [MessageHandler(filters.TEXT & ~filters.COMMAND, emh)],
            SELECT_MATERIAL: [CallbackQueryHandler(smh)],
            ENTER_COST:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ech)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
        per_message=False,
    )
    ptb.add_handler(conv)

    app = web.Application()
    app["ptb"] = ptb
    app["webhook_url"] = WEBHOOK_URL
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_post("/webhook", webhook_handler)
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
