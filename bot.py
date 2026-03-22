import os, asyncio, logging, math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters
logging.basicConfig(level=logging.INFO)
GRADES=["C5","C10","C15","C20","C25","C30","C35","C40","C45","C50","C60"]
DEFAULT_UNIT_COSTS={"Cement":16.08,"Sand":3.15,"Gravel 00":2.47,"Gravel 01":1.89,"Gravel 02":2.40,"Water":0.50,"Chemicals":102.00}
DEFAULT_FIXED={"Labor":160.0,"Overhead":160.0,"Reject 2.5%":264.0,"Truck":400.0}
DEFAULT_MIX_QTY={"Cement":[190,270,265,280,300,320,350,390,460,500,560],"Sand":[341,500,432.1,432,700,665,723,700,655,610,590],"Gravel 00":[341,530,432.1,432,310,245,188,200,235,200,210],"Gravel 01":[494,300,190.16,190,335,330,351,320,301,310,320],"Gravel 02":[741,700,846,760,635,670,652,645,645,640,640],"Water":[120,150,150,115,140,145,157,145,150,150,150],"Chemicals":[1.54,1.54,1.54,1.54,6.0,6.4,7.0,8.2,9.2,10.0,11.2]}
DEFAULT_MARGINS={"C5":0.13,"C10":0.13,"C15":0.10,"C20":0.13,"C25":0.13,"C30":0.13,"C35":0.13,"C40":0.11,"C45":0.13,"C50":0.13,"C60":0.13}
TRUCK_CAPACITY=10
FUEL_CONSUMPTION=1
def grade_index(g): return GRADES.index(g)
def get_uc(ctx):
    if "unit_costs" not in ctx.user_data: ctx.user_data["unit_costs"]=dict(DEFAULT_UNIT_COSTS)
    return ctx.user_data["unit_costs"]
def get_fc(ctx):
    if "fixed_costs" not in ctx.user_data: ctx.user_data["fixed_costs"]=dict(DEFAULT_FIXED)
    return ctx.user_data["fixed_costs"]
def get_mq(ctx):
    if "mix_qty" not in ctx.user_data: ctx.user_data["mix_qty"]={m:list(v) for m,v in DEFAULT_MIX_QTY.items()}
    return ctx.user_data["mix_qty"]
def calc_material_cost(grade,uc,mq):
    idx=grade_index(grade);bd,total={},0
    for m,ql in mq.items():
        q=ql[idx];c=q*uc[m];bd[m]={"qty":q,"unit_cost":uc[m],"cost":c};total+=c
    return bd,total
def calc_fixed_cost(fc):
    bd,total={},0
    for item,c in fc.items(): bd[item]={"cost":c};total+=c
    return bd,total
def calc_transport(volume,pump_total,distance_km,fuel_price):
    pump_per_m3=pump_total/volume;trucks=math.ceil(volume/TRUCK_CAPACITY)
    total_liters=trucks*distance_km*FUEL_CONSUMPTION;fuel_total=total_liters*fuel_price
    return {"pump_total":pump_total,"pump_per_m3":pump_per_m3,"trucks":trucks,"total_liters":total_liters,"fuel_total":fuel_total,"fuel_per_m3":fuel_total/volume,"distance_km":distance_km,"fuel_price":fuel_price,"volume":volume}
def calc_sale_price(grade,uc,fc,mq,transport,margin=None):
    mat_bd,mat_cost=calc_material_cost(grade,uc,mq);fix_bd,fix_cost=calc_fixed_cost(fc)
    if margin is None: margin=DEFAULT_MARGINS[grade]
    prod_cost=mat_cost+fix_cost+transport["pump_per_m3"]+transport["fuel_per_m3"]
    sale_price=prod_cost*(1+margin)
    return {"mat_bd":mat_bd,"fix_bd":fix_bd,"mat_cost":mat_cost,"fix_cost":fix_cost,"transport":transport,"prod_cost":prod_cost,"margin":margin,"sale_price":sale_price,"profit":sale_price-prod_cost}
def fmt_summary(grade,r):
    t=r["transport"]
    lines=[f"🏢 *COBUILT READY MIX — {grade}*","",f"📦 Volume: {t['volume']} m³  |  🚛 {t['trucks']} trucks  |  📍 {t['distance_km']} km","","```",f"{'Item':<24} {'ETB/m³':>10}","─"*36,f"{'Materials':<24} {r['mat_cost']:>10,.2f}",f"{'Fixed Costs':<24} {r['fix_cost']:>10,.2f}",f"{'Pump Cost/m³':<24} {t['pump_per_m3']:>10,.2f}",f"{'Fuel Cost/m³':<24} {t['fuel_per_m3']:>10,.2f}","─"*36,f"{'Production Cost':<24} {r['prod_cost']:>10,.2f}",f"{'Margin':<24} {r['margin']*100:>9.1f}%","─"*36,f"{'Sale Price':<24} {r['sale_price']:>10,.2f}",f"{'Profit':<24} {r['profit']:>10,.2f}","```"]
    return "\n".join(lines)
def fmt_breakdown(grade,r):
    t=r["transport"]
    lines=[f"📋 *{grade} — Full Cost Breakdown*","","```",f"{'Item':<14}{'Qty':>7}{'Rate':>8}{'ETB/m³':>10}","─"*42]
    for m,d in r["mat_bd"].items(): lines.append(f"{m:<14}{d['qty']:>7.2f}{d['unit_cost']:>8.2f}{d['cost']:>10,.2f}")
    lines.append("─"*42)
    for item,d in r["fix_bd"].items(): lines.append(f"{item:<14}{'—':>7}{'—':>8}{d['cost']:>10,.2f}")
    lines+=[f"{'Pump Cost/m³':<14}{'—':>7}{'—':>8}{t['pump_per_m3']:>10,.2f}",f"{'Fuel Cost/m³':<14}{'—':>7}{'—':>8}{t['fuel_per_m3']:>10,.2f}","─"*42,f"{'Prod Cost':<30}{r['prod_cost']:>10,.2f}",f"{'Margin':<30}{r['margin']*100:>9.1f}%",f"{'Sale Price':<30}{r['sale_price']:>10,.2f}","```","","🚛 *Transport Detail*","```",f"{'Pump Total':<24}ETB {t['pump_total']:>10,.2f}",f"{'Pump per m³':<24}ETB {t['pump_per_m3']:>10,.2f}",f"{'Distance':<24}{t['distance_km']:>10} km",f"{'Trucks':<24}{t['trucks']:>10}",f"{'Total Liters':<24}{t['total_liters']:>10.1f} L",f"{'Fuel/Liter':<24}ETB {t['fuel_price']:>10,.2f}",f"{'Fuel Total':<24}ETB {t['fuel_total']:>10,.2f}",f"{'Fuel per m³':<24}ETB {t['fuel_per_m3']:>10,.2f}","```"]
    return "\n".join(lines)
def costs_text(ctx):
    uc=get_uc(ctx);fc=get_fc(ctx)
    lines=["⚙️  *Current Unit Costs (ETB)*\n","```"]
    for m,c in uc.items(): lines.append(f"{m:<14}{c:>8.2f}"+(" ✏️" if c!=DEFAULT_UNIT_COSTS[m] else ""))
    lines.append("─"*24)
    for m,c in fc.items(): lines.append(f"{m:<14}{c:>8.2f}"+(" ✏️" if c!=DEFAULT_FIXED[m] else ""))
    lines.append("```\n_Select a material to update:_")
    return "\n".join(lines)
def mix_grade_text(ctx,grade):
    mq=get_mq(ctx);idx=grade_index(grade)
    lines=[f"📐 *Mix Quantities — {grade}* (kg/m³)\n","```"]
    for m,ql in mq.items():
        current=ql[idx];default=DEFAULT_MIX_QTY[m][idx];marker=" ✏️" if current!=default else ""
        lines.append(f"{m:<14}{current:>8.2f}{marker}")
    lines.append("```\n_Select a material to update:_")
    return "\n".join(lines)
(MAIN_MENU,SELECT_GRADES,ASK_VOLUME,ASK_PUMP,ASK_DISTANCE,ASK_FUEL_PRICE,SHOW_RESULT,ENTER_CUSTOM_MARGIN,SETTINGS_MENU,SELECT_COST_MATERIAL,ENTER_COST,SELECT_MIX_GRADE,SELECT_MIX_MATERIAL,ENTER_MIX_QTY)=range(14)
def main_menu_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("🏗  Grade Types",callback_data="goto_grades")],[InlineKeyboardButton("⚙️  Update Settings",callback_data="goto_settings")]])
def settings_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("💰 Update Unit Costs",callback_data="goto_costs")],[InlineKeyboardButton("📐 Update Mix Quantities",callback_data="goto_mixqty")],[InlineKeyboardButton("🏠 Main Menu",callback_data="goto_main")]])
def grades_kb(selected):
    rows,row=[],[]
    for g in GRADES:
        row.append(InlineKeyboardButton(("✅ "+g) if g in selected else g,callback_data="toggle_"+g))
        if len(row)==4: rows.append(row);row=[]
    if row: rows.append(row)
    rows.append([InlineKeyboardButton(f"✅ Done ({len(selected)} selected)" if selected else "✅ Done",callback_data="grades_done"),InlineKeyboardButton("🏠 Main Menu",callback_data="goto_main")])
    return InlineKeyboardMarkup(rows)
def step_kb(show_back=True):
    row=[]
    if show_back: row.append(InlineKeyboardButton("← Back",callback_data="step_back"))
    row.append(InlineKeyboardButton("❌ Cancel",callback_data="goto_main"))
    return InlineKeyboardMarkup([row])
def result_kb(idx,total):
    rows=[[InlineKeyboardButton("📋 Full Breakdown",callback_data=f"breakdown_{idx}")],[InlineKeyboardButton("✏️  Custom Margin",callback_data=f"custom_{idx}")]]
    nav=[]
    if idx>0: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data=f"nav_{idx-1}"))
    if idx<total-1: nav.append(InlineKeyboardButton("Next ➡️",callback_data=f"nav_{idx+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("🔄 New Calculation",callback_data="goto_grades"),InlineKeyboardButton("🏠 Main Menu",callback_data="goto_main")])
    return InlineKeyboardMarkup(rows)
def cost_material_kb():
    rows=[[InlineKeyboardButton(m,callback_data="setcost_"+m)] for m in list(DEFAULT_UNIT_COSTS.keys())+list(DEFAULT_FIXED.keys())]
    rows.append([InlineKeyboardButton("← Back",callback_data="goto_settings"),InlineKeyboardButton("🏠 Main Menu",callback_data="goto_main")])
    return InlineKeyboardMarkup(rows)
def back_to_costs_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("← Back to Costs",callback_data="goto_costs"),InlineKeyboardButton("❌ Cancel",callback_data="goto_main")]])
def mix_grade_kb():
    rows,row=[],[]
    for g in GRADES:
        row.append(InlineKeyboardButton(g,callback_data="mixgrade_"+g))
        if len(row)==4: rows.append(row);row=[]
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("← Back",callback_data="goto_settings"),InlineKeyboardButton("🏠 Main Menu",callback_data="goto_main")])
    return InlineKeyboardMarkup(rows)
def mix_material_kb(grade):
    rows=[[InlineKeyboardButton(m,callback_data="mixmat_"+m)] for m in DEFAULT_MIX_QTY.keys()]
    rows.append([InlineKeyboardButton("← Back",callback_data="goto_mixqty"),InlineKeyboardButton("🏠 Main Menu",callback_data="goto_main")])
    return InlineKeyboardMarkup(rows)
def back_to_mix_kb(grade): return InlineKeyboardMarkup([[InlineKeyboardButton("← Back",callback_data="mixgrade_"+grade),InlineKeyboardButton("❌ Cancel",callback_data="goto_main")]])
async def start(update,context):
    context.user_data.pop("selected_grades",None)
    text="🏢 *COBUILT READY MIX Price Calculator*\n\nCalculate accurate sale prices for ready mix\nconcrete grades C5–C60 with real transport costs.\n\nAll prices in *ETB per m³*"
    if update.message: await update.message.reply_text(text,parse_mode="Markdown",reply_markup=main_menu_kb())
    else: await update.callback_query.edit_message_text(text,parse_mode="Markdown",reply_markup=main_menu_kb())
    return MAIN_MENU
async def main_menu_handler(update,context):
    q=update.callback_query;await q.answer();d=q.data
    if d=="goto_grades":
        context.user_data["selected_grades"]=[]
        await q.edit_message_text("🏗  *Select Concrete Grades*\n\nTap grades to select, tap again to deselect.\nTap *Done* when ready.",parse_mode="Markdown",reply_markup=grades_kb([]))
        return SELECT_GRADES
    elif d=="goto_settings":
        await q.edit_message_text("⚙️  *Update Settings*\n\nWhat would you like to update?",parse_mode="Markdown",reply_markup=settings_kb())
        return SETTINGS_MENU
    elif d=="goto_main": return await start(update,context)
async def settings_handler(update,context):
    q=update.callback_query;await q.answer();d=q.data
    if d=="goto_main": return await start(update,context)
    if d=="goto_settings":
        await q.edit_message_text("⚙️  *Update Settings*\n\nWhat would you like to update?",parse_mode="Markdown",reply_markup=settings_kb())
        return SETTINGS_MENU
    if d=="goto_costs":
        await q.edit_message_text(costs_text(context),parse_mode="Markdown",reply_markup=cost_material_kb())
        return SELECT_COST_MATERIAL
    if d=="goto_mixqty":
        await q.edit_message_text("📐 *Update Mix Quantities*\n\nSelect a concrete grade to update:",parse_mode="Markdown",reply_markup=mix_grade_kb())
        return SELECT_MIX_GRADE
async def select_grades_handler(update,context):
    q=update.callback_query;await q.answer();d=q.data
    if d=="goto_main": return await start(update,context)
    selected=context.user_data.get("selected_grades",[])
    if d.startswith("toggle_"):
        grade=d.split("_",1)[1]
        if grade in selected: selected.remove(grade)
        else: selected.append(grade)
        context.user_data["selected_grades"]=selected
        await q.edit_message_text("🏗  *Select Concrete Grades*\n\nTap grades to select, tap again to deselect.\nTap *Done* when ready.",parse_mode="Markdown",reply_markup=grades_kb(selected))
        return SELECT_GRADES
    elif d=="grades_done":
        if not selected: await q.answer("⚠️ Please select at least one grade!",show_alert=True);return SELECT_GRADES
        await q.edit_message_text(f"✅ Selected: *{', '.join(selected)}*\n\n*Step 1 of 4* — Total Volume\n\nEnter the total volume of concrete\nfor this project in m³:\n\n_Example: 50_",parse_mode="Markdown",reply_markup=step_kb(show_back=False))
        return ASK_VOLUME
async def ask_volume(update,context):
    if update.callback_query:
        q=update.callback_query;await q.answer()
        if q.data=="goto_main": return await start(update,context)
        return ASK_VOLUME
    try:
        vol=float(update.message.text.strip())
        if vol<=0: raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a valid positive number for volume (m³).",reply_markup=step_kb(show_back=False));return ASK_VOLUME
    context.user_data["volume"]=vol;trucks=math.ceil(vol/TRUCK_CAPACITY)
    await update.message.reply_text(f"✅ Volume: *{vol} m³*  →  *{trucks} trucks* needed\n\n*Step 2 of 4* — Pump Cost\n\nEnter the *total* pump cost for\nthe entire project (ETB):\n\n_Example: 15000_",parse_mode="Markdown",reply_markup=step_kb())
    return ASK_PUMP
async def ask_pump(update,context):
    if update.callback_query:
        q=update.callback_query;await q.answer()
        if q.data=="goto_main": return await start(update,context)
        if q.data=="step_back":
            selected=context.user_data.get("selected_grades",[])
            await q.edit_message_text(f"✅ Selected: *{', '.join(selected)}*\n\n*Step 1 of 4* — Total Volume\n\nEnter the total volume of concrete\nfor this project in m³:\n\n_Example: 50_",parse_mode="Markdown",reply_markup=step_kb(show_back=False))
            return ASK_VOLUME
        return ASK_PUMP
    try:
        pump=float(update.message.text.strip())
        if pump<0: raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a valid number for pump cost (ETB).",reply_markup=step_kb());return ASK_PUMP
    context.user_data["pump"]=pump;vol=context.user_data["volume"]
    await update.message.reply_text(f"✅ Pump Cost: *ETB {pump:,.2f}*  →  *ETB {pump/vol:,.2f}/m³*\n\n*Step 3 of 4* — Project Distance\n\nEnter the distance from plant\nto project site in km:\n\n_Example: 25_",parse_mode="Markdown",reply_markup=step_kb())
    return ASK_DISTANCE
async def ask_distance(update,context):
    if update.callback_query:
        q=update.callback_query;await q.answer()
        if q.data=="goto_main": return await start(update,context)
        if q.data=="step_back":
            vol=context.user_data.get("volume","");trucks=math.ceil(vol/TRUCK_CAPACITY) if vol else "?"
            await q.edit_message_text(f"✅ Volume: *{vol} m³*  →  *{trucks} trucks* needed\n\n*Step 2 of 4* — Pump Cost\n\nEnter the *total* pump cost for\nthe entire project (ETB):\n\n_Example: 15000_",parse_mode="Markdown",reply_markup=step_kb())
            return ASK_PUMP
        return ASK_DISTANCE
    try:
        dist=float(update.message.text.strip())
        if dist<=0: raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a valid positive number for distance (km).",reply_markup=step_kb());return ASK_DISTANCE
    context.user_data["distance"]=dist;trucks=math.ceil(context.user_data["volume"]/TRUCK_CAPACITY)
    await update.message.reply_text(f"✅ Distance: *{dist} km*\n   {trucks} trucks × {dist} km = *{trucks*dist:.0f} liters*\n\n*Step 4 of 4* — Fuel Price\n\nEnter the current fuel price\nper liter (ETB):\n\n_Example: 92.5_",parse_mode="Markdown",reply_markup=step_kb())
    return ASK_FUEL_PRICE
async def ask_fuel_price(update,context):
    if update.callback_query:
        q=update.callback_query;await q.answer()
        if q.data=="goto_main": return await start(update,context)
        if q.data=="step_back":
            vol=context.user_data.get("volume","")
            await q.edit_message_text(f"✅ Volume: *{vol} m³*\n\n*Step 3 of 4* — Project Distance\n\nEnter the distance from plant\nto project site in km:\n\n_Example: 25_",parse_mode="Markdown",reply_markup=step_kb())
            return ASK_DISTANCE
        return ASK_FUEL_PRICE
    try:
        fuel_price=float(update.message.text.strip())
        if fuel_price<=0: raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a valid positive number for fuel price (ETB/L).",reply_markup=step_kb());return ASK_FUEL_PRICE
    grades=context.user_data["selected_grades"];vol=context.user_data["volume"];pump=context.user_data["pump"];dist=context.user_data["distance"]
    uc=get_uc(context);fc=get_fc(context);mq=get_mq(context);transport=calc_transport(vol,pump,dist,fuel_price)
    results=[(g,calc_sale_price(g,uc,fc,mq,transport)) for g in grades]
    context.user_data["results"]=results;context.user_data["result_idx"]=0;t=transport
    await update.message.reply_text(f"✅ Fuel: *ETB {fuel_price}/L*\n   {t['trucks']} trucks × {dist} km = *{t['total_liters']:.0f} L*  →  *ETB {t['fuel_total']:,.2f}*\n\n⏳ Calculating {len(grades)} grade(s)...",parse_mode="Markdown")
    grade,r=results[0];total=len(results);header=f"📊 *Result 1 of {total}*\n\n" if total>1 else ""
    await update.message.reply_text(header+fmt_summary(grade,r),parse_mode="Markdown",reply_markup=result_kb(0,total))
    return SHOW_RESULT
async def show_result_handler(update,context):
    q=update.callback_query;await q.answer();d=q.data
    if d=="goto_main": return await start(update,context)
    if d=="goto_grades":
        context.user_data["selected_grades"]=[]
        await q.edit_message_text("🏗  *Select Concrete Grades*\n\nTap grades to select, tap again to deselect.\nTap *Done* when ready.",parse_mode="Markdown",reply_markup=grades_kb([]))
        return SELECT_GRADES
    results=context.user_data.get("results",[]);total=len(results)
    if d.startswith("nav_"):
        idx=int(d.split("_",1)[1]);context.user_data["result_idx"]=idx;grade,r=results[idx]
        header=f"📊 *Result {idx+1} of {total}*\n\n" if total>1 else ""
        await q.edit_message_text(header+fmt_summary(grade,r),parse_mode="Markdown",reply_markup=result_kb(idx,total));return SHOW_RESULT
    if d.startswith("breakdown_"):
        idx=int(d.split("_",1)[1]);grade,r=results[idx]
        await q.edit_message_text(fmt_breakdown(grade,r),parse_mode="Markdown",reply_markup=result_kb(idx,total));return SHOW_RESULT
    if d.startswith("custom_"):
        idx=int(d.split("_",1)[1]);context.user_data["result_idx"]=idx;grade,_=results[idx]
        await q.edit_message_text(f"✏️  *Custom Margin for {grade}*\n\nEnter your desired margin percentage:\n\n_Example: type 15 for 15%_",parse_mode="Markdown")
        return ENTER_CUSTOM_MARGIN
async def enter_custom_margin(update,context):
    try:
        m=float(update.message.text.strip().replace("%",""))/100
        if not (0<m<2): raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a number between 1 and 100.");return ENTER_CUSTOM_MARGIN
    results=context.user_data.get("results",[]);idx=context.user_data.get("result_idx",0);total=len(results)
    grade,r=results[idx];uc=get_uc(context);fc=get_fc(context);mq=get_mq(context)
    new_r=calc_sale_price(grade,uc,fc,mq,r["transport"],margin=m);results[idx]=(grade,new_r);context.user_data["results"]=results
    header=f"📊 *Result {idx+1} of {total}*\n\n" if total>1 else ""
    await update.message.reply_text(header+fmt_summary(grade,new_r),parse_mode="Markdown",reply_markup=result_kb(idx,total))
    return SHOW_RESULT
async def select_cost_material_handler(update,context):
    q=update.callback_query;await q.answer();d=q.data
    if d=="goto_main": return await start(update,context)
    if d=="goto_settings":
        await q.edit_message_text("⚙️  *Update Settings*\n\nWhat would you like to update?",parse_mode="Markdown",reply_markup=settings_kb())
        return SETTINGS_MENU
    if d=="goto_costs":
        await q.edit_message_text(costs_text(context),parse_mode="Markdown",reply_markup=cost_material_kb())
        return SELECT_COST_MATERIAL
    if d.startswith("setcost_"):
        mat=d[len("setcost_"):];context.user_data["material"]=mat
        uc=get_uc(context);fc=get_fc(context)
        current=uc.get(mat) if mat in uc else fc.get(mat)
        default=DEFAULT_UNIT_COSTS.get(mat) if mat in DEFAULT_UNIT_COSTS else DEFAULT_FIXED.get(mat)
        await q.edit_message_text(f"💰 *Update: {mat}*\n\nDefault : *ETB {default:.2f}*\nCurrent : *ETB {current:.2f}*\n\nEnter new cost in ETB:",parse_mode="Markdown",reply_markup=back_to_costs_kb())
        return ENTER_COST
async def enter_cost(update,context):
    if update.callback_query:
        q=update.callback_query;await q.answer()
        if q.data=="goto_main": return await start(update,context)
        if q.data=="goto_costs":
            await q.edit_message_text(costs_text(context),parse_mode="Markdown",reply_markup=cost_material_kb())
            return SELECT_COST_MATERIAL
        return ENTER_COST
    mat=context.user_data.get("material")
    try:
        c=float(update.message.text.strip())
        if c<0: raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a valid positive number.",reply_markup=back_to_costs_kb());return ENTER_COST
    uc=get_uc(context);fc=get_fc(context)
    if mat in uc: old=uc[mat];uc[mat]=c;context.user_data["unit_costs"]=uc
    else: old=fc[mat];fc[mat]=c;context.user_data["fixed_costs"]=fc
    await update.message.reply_text(f"✅ *{mat}* updated!\n\nETB {old:.2f}  →  ETB {c:.2f}\n\n_Update another or go to Main Menu:_",parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Update More Costs",callback_data="goto_costs")],[InlineKeyboardButton("🏠 Main Menu",callback_data="goto_main")]]))
    return SELECT_COST_MATERIAL
async def select_mix_grade_handler(update,context):
    q=update.callback_query;await q.answer();d=q.data
    if d=="goto_main": return await start(update,context)
    if d=="goto_settings":
        await q.edit_message_text("⚙️  *Update Settings*\n\nWhat would you like to update?",parse_mode="Markdown",reply_markup=settings_kb())
        return SETTINGS_MENU
    if d=="goto_mixqty":
        await q.edit_message_text("📐 *Update Mix Quantities*\n\nSelect a concrete grade to update:",parse_mode="Markdown",reply_markup=mix_grade_kb())
        return SELECT_MIX_GRADE
    if d.startswith("mixgrade_"):
        grade=d.split("_",1)[1];context.user_data["mix_grade"]=grade
        await q.edit_message_text(mix_grade_text(context,grade),parse_mode="Markdown",reply_markup=mix_material_kb(grade))
        return SELECT_MIX_MATERIAL
async def select_mix_material_handler(update,context):
    q=update.callback_query;await q.answer();d=q.data
    if d=="goto_main": return await start(update,context)
    if d=="goto_mixqty":
        await q.edit_message_text("📐 *Update Mix Quantities*\n\nSelect a concrete grade to update:",parse_mode="Markdown",reply_markup=mix_grade_kb())
        return SELECT_MIX_GRADE
    grade=context.user_data.get("mix_grade","")
    if d.startswith("mixgrade_"):
        grade=d.split("_",1)[1];context.user_data["mix_grade"]=grade
        await q.edit_message_text(mix_grade_text(context,grade),parse_mode="Markdown",reply_markup=mix_material_kb(grade))
        return SELECT_MIX_MATERIAL
    if d.startswith("mixmat_"):
        mat=d[len("mixmat_"):];context.user_data["mix_material"]=mat
        mq=get_mq(context);idx=grade_index(grade)
        current=mq[mat][idx];default=DEFAULT_MIX_QTY[mat][idx]
        await q.edit_message_text(f"📐 *Update Mix Quantity*\n\nGrade    : *{grade}*\nMaterial : *{mat}*\n\nDefault  : *{default:.2f} kg/m³*\nCurrent  : *{current:.2f} kg/m³*\n\nEnter new quantity in kg/m³:",parse_mode="Markdown",reply_markup=back_to_mix_kb(grade))
        return ENTER_MIX_QTY
async def enter_mix_qty(update,context):
    if update.callback_query:
        q=update.callback_query;await q.answer()
        if q.data=="goto_main": return await start(update,context)
        grade=context.user_data.get("mix_grade","")
        if q.data.startswith("mixgrade_"):
            grade=q.data.split("_",1)[1];context.user_data["mix_grade"]=grade
            await q.edit_message_text(mix_grade_text(context,grade),parse_mode="Markdown",reply_markup=mix_material_kb(grade))
            return SELECT_MIX_MATERIAL
        return ENTER_MIX_QTY
    grade=context.user_data.get("mix_grade","");mat=context.user_data.get("mix_material","")
    try:
        qty=float(update.message.text.strip())
        if qty<0: raise ValueError
    except ValueError: await update.message.reply_text("❌ Please enter a valid positive number.");return ENTER_MIX_QTY
    mq=get_mq(context);idx=grade_index(grade);old=mq[mat][idx];mq[mat][idx]=qty;context.user_data["mix_qty"]=mq
    await update.message.reply_text(f"✅ *{mat}* for *{grade}* updated!\n\n{old:.2f} kg/m³  →  {qty:.2f} kg/m³\n\n_Update another material or go back:_",parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📐 Update More in "+grade,callback_data="mixgrade_"+grade)],[InlineKeyboardButton("📐 Change Grade",callback_data="goto_mixqty")],[InlineKeyboardButton("🏠 Main Menu",callback_data="goto_main")]]))
    return SELECT_MIX_MATERIAL
async def cancel(update,context):
    await update.message.reply_text("Cancelled. Type /start to begin again.");return ConversationHandler.END
async def run():
    BOT_TOKEN=os.environ["BOT_TOKEN"]
    logging.info("Starting COBUILT READY MIX Bot...")
    app=Application.builder().token(BOT_TOKEN).build()
    conv=ConversationHandler(entry_points=[CommandHandler("start",start)],states={MAIN_MENU:[CallbackQueryHandler(main_menu_handler)],SELECT_GRADES:[CallbackQueryHandler(select_grades_handler)],ASK_VOLUME:[MessageHandler(filters.TEXT&~filters.COMMAND,ask_volume),CallbackQueryHandler(ask_volume)],ASK_PUMP:[MessageHandler(filters.TEXT&~filters.COMMAND,ask_pump),CallbackQueryHandler(ask_pump)],ASK_DISTANCE:[MessageHandler(filters.TEXT&~filters.COMMAND,ask_distance),CallbackQueryHandler(ask_distance)],ASK_FUEL_PRICE:[MessageHandler(filters.TEXT&~filters.COMMAND,ask_fuel_price),CallbackQueryHandler(ask_fuel_price)],SHOW_RESULT:[CallbackQueryHandler(show_result_handler)],ENTER_CUSTOM_MARGIN:[MessageHandler(filters.TEXT&~filters.COMMAND,enter_custom_margin)],SETTINGS_MENU:[CallbackQueryHandler(settings_handler)],SELECT_COST_MATERIAL:[CallbackQueryHandler(select_cost_material_handler)],ENTER_COST:[MessageHandler(filters.TEXT&~filters.COMMAND,enter_cost),CallbackQueryHandler(enter_cost)],SELECT_MIX_GRADE:[CallbackQueryHandler(select_mix_grade_handler)],SELECT_MIX_MATERIAL:[CallbackQueryHandler(select_mix_material_handler)],ENTER_MIX_QTY:[MessageHandler(filters.TEXT&~filters.COMMAND,enter_mix_qty),CallbackQueryHandler(enter_mix_qty)]},fallbacks=[CommandHandler("cancel",cancel),CommandHandler("start",start)],per_message=False)
    app.add_handler(conv)
    await app.initialize();await app.start();await app.updater.start_polling()
    logging.info("Bot is running!")
    await asyncio.Event().wait()
if __name__=="__main__": asyncio.run(run())
