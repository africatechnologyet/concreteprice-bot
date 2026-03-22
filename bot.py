import os, asyncio, logging, math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters
logging.basicConfig(level=logging.INFO)
GRADES=["C5","C10","C15","C20","C25","C30","C35","C40","C45","C50","C60"]
DEFAULT_UNIT_COSTS={"Cement":16.08,"Sand":3.15,"Gravel 00":2.47,"Gravel 01":1.89,"Gravel 02":2.40,"Water":0.50,"Chemicals":102.00}
MIX_QTY={"Cement":[190,270,265,280,300,320,350,390,460,500,560],"Sand":[341,500,432.1,432,700,665,723,700,655,610,590],"Gravel 00":[341,530,432.1,432,310,245,188,200,235,200,210],"Gravel 01":[494,300,190.16,190,335,330,351,320,301,310,320],"Gravel 02":[741,700,846,760,635,670,652,645,645,640,640],"Water":[120,150,150,115,140,145,157,145,150,150,150],"Chemicals":[1.54,1.54,1.54,1.54,6.0,6.4,7.0,8.2,9.2,10.0,11.2]}
FIXED_COSTS={"Labor":[160,160,160,160,200,147,160,200,200,200,200],"Overhead":[160,160,160,160,200,147,160,200,200,200,200],"Reject 2.5%":[264,264,264,264,264,264,264,264,264,264,264],"Truck":[400,400,400,400,400,400,400,400,400,400,400]}
DEFAULT_MARGINS={"C5":0.13,"C10":0.13,"C15":0.10,"C20":0.13,"C25":0.13,"C30":0.13,"C35":0.13,"C40":0.11,"C45":0.13,"C50":0.13,"C60":0.13}
TRUCK_CAPACITY=10
FUEL_CONSUMPTION=1
def grade_index(g): return GRADES.index(g)
def calc_material_cost(grade,uc):
    idx=grade_index(grade);bd,total={},0
    for m,ql in MIX_QTY.items():
        q=ql[idx];c=q*uc[m];bd[m]={"qty":q,"unit_cost":uc[m],"cost":c};total+=c
    return bd,total
def calc_fixed_cost(grade):
    idx=grade_index(grade);bd,total={},0
    for item,cl in FIXED_COSTS.items():
        c=cl[idx];bd[item]={"cost":c};total+=c
    return bd,total
def calc_transport(volume,pump_total,distance_km,fuel_price):
    pump_per_m3=pump_total/volume
    trucks=math.ceil(volume/TRUCK_CAPACITY)
    total_liters=trucks*distance_km*FUEL_CONSUMPTION
    fuel_total=total_liters*fuel_price
    fuel_per_m3=fuel_total/volume
    return {"pump_total":pump_total,"pump_per_m3":pump_per_m3,"trucks":trucks,"total_liters":total_liters,"fuel_total":fuel_total,"fuel_per_m3":fuel_per_m3,"distance_km":distance_km,"fuel_price":fuel_price,"volume":volume}
def calc_sale_price(grade,uc,transport,margin=None):
    mat_bd,mat_cost=calc_material_cost(grade,uc)
    fix_bd,fix_cost=calc_fixed_cost(grade)
    if margin is None: margin=DEFAULT_MARGINS[grade]
    prod_cost=mat_cost+fix_cost+transport["pump_per_m3"]+transport["fuel_per_m3"]
    sale_price=prod_cost*(1+margin)
    return {"mat_bd":mat_bd,"fix_bd":fix_bd,"mat_cost":mat_cost,"fix_cost":fix_cost,"transport":transport,"prod_cost":prod_cost,"margin":margin,"sale_price":sale_price,"profit":sale_price-prod_cost}
def fmt_summary(grade,r):
    t=r["transport"]
    lines=[f"🏗  *{grade} Concrete — Price Summary*","",f"📦 Volume : {t['volume']} m³",f"🚛 Trucks : {t['trucks']} trucks  ({t['distance_km']} km)","","```",f"{'Item':<24} {'ETB/m³':>10}","─"*36,f"{'Materials':<24} {r['mat_cost']:>10,.2f}",f"{'Fixed Costs':<24} {r['fix_cost']:>10,.2f}",f"{'Pump Cost/m³':<24} {t['pump_per_m3']:>10,.2f}",f"{'Fuel Cost/m³':<24} {t['fuel_per_m3']:>10,.2f}","─"*36,f"{'Production Cost':<24} {r['prod_cost']:>10,.2f}",f"{'Margin':<24} {r['margin']*100:>9.1f}%","─"*36,f"{'Sale Price':<24} {r['sale_price']:>10,.2f}",f"{'Profit':<24} {r['profit']:>10,.2f}","```"]
    return "\n".join(lines)
def fmt_breakdown(grade,r):
    t=r["transport"]
    lines=[f"📋 *{grade} — Full Cost Breakdown*","","```",f"{'Item':<14}{'Qty':>7}{'Rate':>8}{'ETB/m³':>10}","─"*42]
    for m,d in r["mat_bd"].items(): lines.append(f"{m:<14}{d['qty']:>7.2f}{d['unit_cost']:>8.2f}{d['cost']:>10,.2f}")
    lines.append("─"*42)
    for item,d in r["fix_bd"].items(): lines.append(f"{item:<14}{'—':>7}{'—':>8}{d['cost']:>10,.2f}")
    lines+=[f"{'Pump Cost/m³':<14}{'—':>7}{'—':>8}{t['pump_per_m3']:>10,.2f}",f"{'Fuel Cost/m³':<14}{'—':>7}{'—':>8}{t['fuel_per_m3']:>10,.2f}","─"*42,f"{'Prod Cost':<30}{r['prod_cost']:>10,.2f}",f"{'Margin':<30}{r['margin']*100:>9.1f}%",f"{'Sale Price':<30}{r['sale_price']:>10,.2f}","```","",f"🚛 *Transport Detail*","```",f"{'Pump Total':<24}ETB {t['pump_total']:>10,.2f}",f"{'Pump per m³':<24}ETB {t['pump_per_m3']:>10,.2f}",f"{'Distance':<24}{t['distance_km']:>10} km",f"{'Trucks':<24}{t['trucks']:>10}",f"{'Total Liters':<24}{t['total_liters']:>10.1f} L",f"{'Fuel/Liter':<24}ETB {t['fuel_price']:>10,.2f}",f"{'Fuel Total':<24}ETB {t['fuel_total']:>10,.2f}",f"{'Fuel per m³':<24}ETB {t['fuel_per_m3']:>10,.2f}","```"]
    return "\n".join(lines)
def fmt_all_margins(grade,r):
    lines=[f"📈 *{grade} — Price at Different Margins*","","```",f"{'Margin':<10}{'Sale Price':>12}{'Profit':>12}","─"*36]
    for m in [0.10,0.11,0.12,0.13]:
        sp=r["prod_cost"]*(1+m);pr=sp-r["prod_cost"];tag=" ◀" if m==DEFAULT_MARGINS[grade] else ""
        lines.append(f"{m*100:.0f}%{'':7}{sp:>12,.2f}{pr:>12,.2f}{tag}")
    lines.append("```")
    return "\n".join(lines)
(MAIN_MENU,SELECT_GRADE,ASK_VOLUME,ASK_PUMP,ASK_DISTANCE,ASK_FUEL_PRICE,SHOW_RESULT,ENTER_CUSTOM_MARGIN,SELECT_MATERIAL,ENTER_COST)=range(10)
def main_menu_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("🏗  Grade Types",callback_data="goto_grades")],[InlineKeyboardButton("⚙️  Update Unit Costs",callback_data="goto_costs")]])
def grades_kb():
    rows,row=[],[]
    for g in GRADES:
        row.append(InlineKeyboardButton(g,callback_data="grade_"+g))
        if len(row)==4: rows.append(row);row=[]
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Main Menu",callback_data="goto_main")])
    return InlineKeyboardMarkup(rows)
def result_kb(grade): return InlineKeyboardMarkup([[InlineKeyboardButton("📋 Full Breakdown",callback_data="breakdown_"+grade)],[InlineKeyboardButton("✏️  Custom Margin",callback_data="custom_"+grade)],[InlineKeyboardButton("🔄 Recalculate",callback_data="grade_"+grade),InlineKeyboardButton("🏠 Main Menu",callback_data="goto_main")]])
def material_kb():
    rows=[[InlineKeyboardButton(m,callback_data="setcost_"+m)] for m in DEFAULT_UNIT_COSTS]
    rows.append([InlineKeyboardButton("🏠 Main Menu",callback_data="goto_main")])
    return InlineKeyboardMarkup(rows)
def get_uc(ctx): return ctx.user_data.get("unit_costs",dict(DEFAULT_UNIT_COSTS))
async def start(update,context):
    context.user_data.clear()
    text="🏗  *Concrete Sales Price Calculator*\n\nCalculate accurate sale prices for concrete\ngrades C5–C60 with real transport costs.\n\nAll prices in *ETB per m³*"
    kb=main_menu_kb()
    if update.message: await update.message.reply_text(text,parse_mode="Markdown",reply_markup=kb)
    else: await update.callback_query.edit_message_text(text,parse_mode="Markdown",reply_markup=kb)
    return MAIN_MENU
async def main_menu_handler(update,context):
    q=update.callback_query;await q.answer();d=q.data
    if d=="goto_grades":
        await q.edit_message_text("🏗  *Select Concrete Grade*\n\nChoose the grade to calculate:",parse_mode="Markdown",reply_markup=grades_kb());return SELECT_GRADE
    elif d=="goto_costs":
        uc=get_uc(context);lines=["⚙️  *Current Unit Costs (ETB)*\n","```"]
        for m,c in uc.items(): lines.append(f"{m:<14}{c:>8.2f}"+(" ✏️" if c!=DEFAULT_UNIT_COSTS[m] else ""))
        lines.append("```\n_Select a material to update:_")
        await q.edit_message_text("\n".join(lines),parse_mode="Markdown",reply_markup=material_kb());return SELECT_MATERIAL
    elif d=="goto_main": return await start(update,context)
async def select_grade_handler(update,context):
    q=update.callback_query;await q.answer();d=q.data
    if d=="goto_main": return await start(update,context)
    if d.startswith("grade_"):
        grade=d.split("_",1)[1];context.user_data["grade"]=grade
        await q.edit_message_text(f"🏗  *{grade} Concrete*\n\n*Step 1 of 4* — Total Volume\n\nEnter the total volume of concrete\nfor this project in m³:\n\n_Example: 50_",parse_mode="Markdown");return ASK_VOLUME
async def ask_volume(update,context):
    try:
        vol=float(update.message.text.strip())
        if vol<=0: raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a valid positive number for volume (m³).");return ASK_VOLUME
    context.user_data["volume"]=vol;grade=context.user_data["grade"];trucks=math.ceil(vol/TRUCK_CAPACITY)
    await update.message.reply_text(f"✅ Volume: *{vol} m³*  →  *{trucks} trucks* needed\n\n*Step 2 of 4* — Pump Cost\n\nEnter the *total* pump cost for\nthe entire project (ETB):\n\n_Example: 15000_",parse_mode="Markdown");return ASK_PUMP
async def ask_pump(update,context):
    try:
        pump=float(update.message.text.strip())
        if pump<0: raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a valid number for pump cost (ETB).");return ASK_PUMP
    context.user_data["pump"]=pump;vol=context.user_data["volume"];pump_per_m3=pump/vol
    await update.message.reply_text(f"✅ Pump Cost: *ETB {pump:,.2f}*  →  *ETB {pump_per_m3:,.2f}/m³*\n\n*Step 3 of 4* — Project Distance\n\nEnter the distance from plant\nto project site in km:\n\n_Example: 25_",parse_mode="Markdown");return ASK_DISTANCE
async def ask_distance(update,context):
    try:
        dist=float(update.message.text.strip())
        if dist<=0: raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a valid positive number for distance (km).");return ASK_DISTANCE
    context.user_data["distance"]=dist;trucks=math.ceil(context.user_data["volume"]/TRUCK_CAPACITY)
    await update.message.reply_text(f"✅ Distance: *{dist} km*\n   {trucks} trucks × {dist} km × 1 L/km = *{trucks*dist:.0f} liters*\n\n*Step 4 of 4* — Fuel Price\n\nEnter the current fuel price\nper liter (ETB):\n\n_Example: 92.5_",parse_mode="Markdown");return ASK_FUEL_PRICE
async def ask_fuel_price(update,context):
    try:
        fuel_price=float(update.message.text.strip())
        if fuel_price<=0: raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a valid positive number for fuel price (ETB/L).");return ASK_FUEL_PRICE
    grade=context.user_data["grade"];vol=context.user_data["volume"];pump=context.user_data["pump"];dist=context.user_data["distance"];uc=get_uc(context)
    transport=calc_transport(vol,pump,dist,fuel_price);result=calc_sale_price(grade,uc,transport);context.user_data["result"]=result
    t=transport
    await update.message.reply_text(f"✅ Fuel: *ETB {fuel_price}/L*\n   {t['trucks']} trucks × {dist} km × 1 L/km = *{t['total_liters']:.0f} L*\n   {t['total_liters']:.0f} L × ETB {fuel_price} = *ETB {t['fuel_total']:,.2f}*\n\n⏳ Calculating...",parse_mode="Markdown")
    await update.message.reply_text(fmt_summary(grade,result),parse_mode="Markdown",reply_markup=result_kb(grade));return SHOW_RESULT
async def show_result_handler(update,context):
    q=update.callback_query;await q.answer();d=q.data
    if d=="goto_main": return await start(update,context)
    if d.startswith("grade_"):
        grade=d.split("_",1)[1];context.user_data["grade"]=grade;context.user_data.pop("result",None)
        await q.edit_message_text(f"🏗  *{grade} Concrete*\n\n*Step 1 of 4* — Total Volume\n\nEnter the total volume of concrete\nfor this project in m³:\n\n_Example: 50_",parse_mode="Markdown");return ASK_VOLUME
    elif d.startswith("breakdown_"):
        grade=d.split("_",1)[1];result=context.user_data.get("result")
        await q.edit_message_text(fmt_breakdown(grade,result),parse_mode="Markdown",reply_markup=result_kb(grade));return SHOW_RESULT
    elif d.startswith("custom_"):
        grade=d.split("_",1)[1]
        await q.edit_message_text(f"✏️  *Custom Margin for {grade}*\n\nEnter your desired margin percentage:\n\n_Example: type 15 for 15%_",parse_mode="Markdown");return ENTER_CUSTOM_MARGIN
async def enter_custom_margin(update,context):
    grade=context.user_data.get("grade");result=context.user_data.get("result")
    try:
        m=float(update.message.text.strip().replace("%",""))/100
        if not (0<m<2): raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a number between 1 and 100.");return ENTER_CUSTOM_MARGIN
    transport=result["transport"];uc=get_uc(context);new_result=calc_sale_price(grade,uc,transport,margin=m);context.user_data["result"]=new_result
    await update.message.reply_text(fmt_summary(grade,new_result),parse_mode="Markdown",reply_markup=result_kb(grade));return SHOW_RESULT
async def select_material_handler(update,context):
    q=update.callback_query;await q.answer();d=q.data
    if d=="goto_main": return await start(update,context)
    if d.startswith("setcost_"):
        mat=d[len("setcost_"):];context.user_data["material"]=mat;current=get_uc(context)[mat]
        await q.edit_message_text(f"⚙️  *Update: {mat}*\n\nCurrent price: *ETB {current:.2f}/kg*\n\nEnter the new unit cost in ETB:",parse_mode="Markdown");return ENTER_COST
async def enter_cost(update,context):
    mat=context.user_data.get("material")
    try:
        c=float(update.message.text.strip())
        if c<0: raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a valid positive number.");return ENTER_COST
    uc=get_uc(context);old=uc[mat];uc[mat]=c;context.user_data["unit_costs"]=uc
    await update.message.reply_text(f"✅ *{mat}* updated successfully!\n\nETB {old:.2f}  →  ETB {c:.2f}/kg\n\nWhat would you like to do next?",parse_mode="Markdown",reply_markup=main_menu_kb());return MAIN_MENU
async def cancel(update,context):
    await update.message.reply_text("Cancelled. Type /start to begin again.");return ConversationHandler.END
async def run():
    BOT_TOKEN=os.environ["BOT_TOKEN"]
    logging.info("Starting Concrete Price Bot...")
    app=Application.builder().token(BOT_TOKEN).build()
    conv=ConversationHandler(entry_points=[CommandHandler("start",start)],states={MAIN_MENU:[CallbackQueryHandler(main_menu_handler)],SELECT_GRADE:[CallbackQueryHandler(select_grade_handler)],ASK_VOLUME:[MessageHandler(filters.TEXT&~filters.COMMAND,ask_volume)],ASK_PUMP:[MessageHandler(filters.TEXT&~filters.COMMAND,ask_pump)],ASK_DISTANCE:[MessageHandler(filters.TEXT&~filters.COMMAND,ask_distance)],ASK_FUEL_PRICE:[MessageHandler(filters.TEXT&~filters.COMMAND,ask_fuel_price)],SHOW_RESULT:[CallbackQueryHandler(show_result_handler)],ENTER_CUSTOM_MARGIN:[MessageHandler(filters.TEXT&~filters.COMMAND,enter_custom_margin)],SELECT_MATERIAL:[CallbackQueryHandler(select_material_handler)],ENTER_COST:[MessageHandler(filters.TEXT&~filters.COMMAND,enter_cost)]},fallbacks=[CommandHandler("cancel",cancel),CommandHandler("start",start)],per_message=False)
    app.add_handler(conv)
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logging.info("Bot is running!")
    await asyncio.Event().wait()
if __name__=="__main__": asyncio.run(run())
