"""
Concrete Sales Price Calculator — Telegram Bot (Render/Webhook mode)
Deploy on Render as a Web Service.
Set environment variables:
  BOT_TOKEN   — from @BotFather
  WEBHOOK_URL — your Render URL, e.g. https://your-app.onrender.com
"""

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────

GRADES = ["C5", "C10", "C15", "C20", "C25", "C30", "C35", "C40", "C45", "C50", "C60"]

DEFAULT_UNIT_COSTS = {
    "Cement":     16.08,
    "Sand":        3.15,
    "Gravel 00":   2.47,
    "Gravel 01":   1.89,
    "Gravel 02":   2.40,
    "Water":       0.50,
    "Chemicals": 102.00,
}

MIX_QTY = {
    "Cement":   [190,   270,   265,     280,   300,   320,   350,   390,   460,   500,   560],
    "Sand":     [341,   500,   432.1,   432,   700,   665,   723,   700,   655,   610,   590],
    "Gravel 00":[341,   530,   432.1,   432,   310,   245,   188,   200,   235,   200,   210],
    "Gravel 01":[494,   300,   190.16,  190,   335,   330,   351,   320,   301,   310,   320],
    "Gravel 02":[741,   700,   846,     760,   635,   670,   652,   645,   645,   640,   640],
    "Water":    [120,   150,   150,     115,   140,   145,   157,   145,   150,   150,   150],
    "Chemicals":[1.54,  1.54,  1.54,   1.54,   6.0,   6.4,   7.0,   8.2,   9.2,  10.0,  11.2],
}

FIXED_COSTS = {
    "Labor":       [160, 160, 160, 160, 200, 147, 160, 200, 200, 200, 200],
    "Overhead":    [160, 160, 160, 160, 200, 147, 160, 200, 200, 200, 200],
    "Reject 2.5%": [264, 264, 264, 264, 264, 264, 264, 264, 264, 264, 264],
    "Truck":       [400, 400, 400, 400, 400, 400, 400, 400, 400, 400, 400],
    "Fuel":        [317, 260, 200, 366, 200, 200, 260, 200, 200, 353, 244],
    "Pump":        [400,   0,   0, 550, 234, 234, 600, 341, 366, 400, 705],
}

DEFAULT_MARGINS = {
    "C5": 0.13, "C10": 0.13, "C15": 0.10, "C20": 0.13,
    "C25": 0.13, "C30": 0.13, "C35": 0.13, "C40": 0.11,
    "C45": 0.13, "C50": 0.13, "C60": 0.13,
}

# ─────────────────────────────────────────────
# CALCULATION ENGINE
# ─────────────────────────────────────────────

def grade_index(grade):
    return GRADES.index(grade)

def calc_production_cost(grade, unit_costs):
    idx = grade_index(grade)
    breakdown = {}
    mat_total = 0
    for mat, qty_list in MIX_QTY.items():
        qty = qty_list[idx]
        cost = qty * unit_costs[mat]
        breakdown[mat] = {"qty": qty, "unit_cost": unit_costs[mat], "cost": cost}
        mat_total += cost
    fixed_total = 0
    for item, cost_list in FIXED_COSTS.items():
        cost = cost_list[idx]
        breakdown[item] = {"cost": cost}
        fixed_total += cost
    return breakdown, mat_total + fixed_total

def calc_sale_price(grade, unit_costs, margin=None):
    breakdown, prod_cost = calc_production_cost(grade, unit_costs)
    if margin is None:
        margin = DEFAULT_MARGINS[grade]
    sale_price = prod_cost * (1 + margin)
    return {
        "breakdown": breakdown,
        "prod_cost": prod_cost,
        "margin": margin,
        "sale_price": sale_price,
        "profit": sale_price - prod_cost,
    }

# ─────────────────────────────────────────────
# FORMATTERS
# ─────────────────────────────────────────────

def fmt_price_summary(grade, result):
    lines = [
        f"📊 *{grade} Concrete — Price Summary*\n",
        f"{'Production Cost:':<22} ETB {result['prod_cost']:>10,.2f}",
        f"{'Margin:':<22} {result['margin']*100:.1f}%",
        f"{'Sale Price:':<22} ETB {result['sale_price']:>10,.2f}",
        f"{'Profit:':<22} ETB {result['profit']:>10,.2f}",
    ]
    return "```\n" + "\n".join(lines) + "\n```"

def fmt_full_breakdown(grade, result):
    bd = result["breakdown"]
    lines = [f"📋 *{grade} — Full Cost Breakdown*\n", "```"]
    lines.append(f"{'Item':<14} {'Qty':>8} {'Rate':>8} {'Cost (ETB)':>12}")
    lines.append("─" * 46)
    for mat in MIX_QTY:
        d = bd[mat]
        lines.append(f"{mat:<14} {d['qty']:>8.2f} {d['unit_cost']:>8.2f} {d['cost']:>12,.2f}")
    lines.append("─" * 46)
    for item in FIXED_COSTS:
        d = bd[item]
        lines.append(f"{item:<14} {'—':>8} {'—':>8} {d['cost']:>12,.2f}")
    lines.append("─" * 46)
    lines.append(f"{'Prod. Cost':<32} {result['prod_cost']:>12,.2f}")
    lines.append(f"{'Margin':<32} {result['margin']*100:>11.1f}%")
    lines.append(f"{'Sale Price':<32} {result['sale_price']:>12,.2f}")
    lines.append("```")
    return "\n".join(lines)

def fmt_all_margins(grade, unit_costs):
    _, prod_cost = calc_production_cost(grade, unit_costs)
    lines = [f"📈 *{grade} — Prices at Different Margins*\n", "```"]
    lines.append(f"{'Margin':<10} {'Sale Price (ETB)':>18} {'Profit (ETB)':>14}")
    lines.append("─" * 44)
    for m in [0.10, 0.11, 0.12, 0.13]:
        sp = prod_cost * (1 + m)
        pr = sp - prod_cost
        tag = " ◀ default" if m == DEFAULT_MARGINS[grade] else ""
        lines.append(f"{m*100:.0f}%{'':<7} {sp:>18,.2f} {pr:>14,.2f}{tag}")
    lines.append("```")
    return "\n".join(lines)

# ─────────────────────────────────────────────
# STATES
# ─────────────────────────────────────────────

(MAIN_MENU, SELECT_GRADE, GRADE_ACTION,
 ENTER_CUSTOM_MARGIN, SELECT_COST_MATERIAL, ENTER_COST_VALUE) = range(6)

# ─────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Get Sale Price", callback_data="menu_price")],
        [InlineKeyboardButton("⚙️ Update Unit Costs", callback_data="menu_costs")],
        [InlineKeyboardButton("📊 All Margins Table", callback_data="menu_margins")],
        [InlineKeyboardButton("🔄 Reset Unit Costs", callback_data="menu_reset")],
    ])

def grade_keyboard(action_prefix):
    rows = []
    row = []
    for i, g in enumerate(GRADES):
        row.append(InlineKeyboardButton(g, callback_data=f"{action_prefix}_{g}"))
        if len(row) == 4:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="goto_main")])
    return InlineKeyboardMarkup(rows)

def grade_action_keyboard(grade):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Price Summary", callback_data=f"summary_{grade}")],
        [InlineKeyboardButton("📋 Full Breakdown", callback_data=f"breakdown_{grade}")],
        [InlineKeyboardButton("✏️ Custom Margin", callback_data=f"custom_{grade}")],
        [InlineKeyboardButton("← Back", callback_data="menu_price"),
         InlineKeyboardButton("🏠 Main Menu", callback_data="goto_main")],
    ])

def material_keyboard():
    rows = [[InlineKeyboardButton(m, callback_data=f"setcost_{m}")] for m in DEFAULT_UNIT_COSTS]
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="goto_main")])
    return InlineKeyboardMarkup(rows)

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_unit_costs(context):
    return context.user_data.get("unit_costs", dict(DEFAULT_UNIT_COSTS))

# ─────────────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = (
        "🏗️ *Concrete Sales Price Calculator*\n\n"
        "Welcome! I calculate sale prices for concrete grades C5–C60.\n"
        "All prices are in *ETB per m³*.\n\n"
        "What would you like to do?"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
    else:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
    return MAIN_MENU

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_price":
        await query.edit_message_text("📦 *Select a concrete grade:*", parse_mode="Markdown", reply_markup=grade_keyboard("price"))
        return SELECT_GRADE

    elif data == "menu_margins":
        await query.edit_message_text("📦 *Select a grade to see all margin options:*", parse_mode="Markdown", reply_markup=grade_keyboard("margins"))
        return SELECT_GRADE

    elif data == "menu_costs":
        unit_costs = get_unit_costs(context)
        lines = ["⚙️ *Current Unit Costs (ETB)*\n", "```"]
        for mat, cost in unit_costs.items():
            marker = " ✏️" if cost != DEFAULT_UNIT_COSTS[mat] else ""
            lines.append(f"{mat:<14} {cost:>8.2f}{marker}")
        lines.append("```\nSelect a material to update:")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=material_keyboard())
        return SELECT_COST_MATERIAL

    elif data == "menu_reset":
        context.user_data["unit_costs"] = dict(DEFAULT_UNIT_COSTS)
        await query.edit_message_text("✅ Unit costs have been *reset* to original values.\n\nWhat would you like to do?", parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    elif data == "goto_main":
        return await start(update, context)

async def select_grade_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "goto_main":
        return await start(update, context)

    if data.startswith("price_"):
        grade = data.split("_", 1)[1]
        context.user_data["selected_grade"] = grade
        await query.edit_message_text(f"*{grade} — What would you like?*", parse_mode="Markdown", reply_markup=grade_action_keyboard(grade))
        return GRADE_ACTION

    elif data.startswith("margins_"):
        grade = data.split("_", 1)[1]
        msg = fmt_all_margins(grade, get_unit_costs(context))
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("← Back", callback_data="menu_margins"),
             InlineKeyboardButton("🏠 Main Menu", callback_data="goto_main")]
        ]))
        return SELECT_GRADE

    elif data in ("menu_price", "menu_margins"):
        prefix = "price" if data == "menu_price" else "margins"
        label = "Select a concrete grade:" if prefix == "price" else "Select a grade to see all margin options:"
        await query.edit_message_text(f"📦 *{label}*", parse_mode="Markdown", reply_markup=grade_keyboard(prefix))
        return SELECT_GRADE

async def grade_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    unit_costs = get_unit_costs(context)

    if data == "goto_main":
        return await start(update, context)

    if data == "menu_price":
        await query.edit_message_text("📦 *Select a concrete grade:*", parse_mode="Markdown", reply_markup=grade_keyboard("price"))
        return SELECT_GRADE

    if data.startswith("summary_"):
        grade = data.split("_", 1)[1]
        result = calc_sale_price(grade, unit_costs)
        await query.edit_message_text(fmt_price_summary(grade, result), parse_mode="Markdown", reply_markup=grade_action_keyboard(grade))
        return GRADE_ACTION

    elif data.startswith("breakdown_"):
        grade = data.split("_", 1)[1]
        result = calc_sale_price(grade, unit_costs)
        await query.edit_message_text(fmt_full_breakdown(grade, result), parse_mode="Markdown", reply_markup=grade_action_keyboard(grade))
        return GRADE_ACTION

    elif data.startswith("custom_"):
        grade = data.split("_", 1)[1]
        context.user_data["selected_grade"] = grade
        await query.edit_message_text(f"✏️ Enter a custom margin % for *{grade}*\nExample: type `12` for 12%", parse_mode="Markdown")
        return ENTER_CUSTOM_MARGIN

async def enter_custom_margin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace("%", "")
    grade = context.user_data.get("selected_grade")
    try:
        margin = float(text) / 100
        if not (0 < margin < 2):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number between 1 and 100.")
        return ENTER_CUSTOM_MARGIN
    result = calc_sale_price(grade, get_unit_costs(context), margin)
    await update.message.reply_text(fmt_price_summary(grade, result), parse_mode="Markdown", reply_markup=grade_action_keyboard(grade))
    return GRADE_ACTION

async def select_cost_material(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "goto_main":
        return await start(update, context)
    if data.startswith("setcost_"):
        material = data[len("setcost_"):]
        context.user_data["editing_material"] = material
        current = get_unit_costs(context)[material]
        await query.edit_message_text(
            f"✏️ *{material}*\nCurrent cost: ETB {current:.2f}/kg\n\nEnter new unit cost in ETB:",
            parse_mode="Markdown",
        )
        return ENTER_COST_VALUE

async def enter_cost_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    material = context.user_data.get("editing_material")
    try:
        new_cost = float(text)
        if new_cost < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid positive number.")
        return ENTER_COST_VALUE
    unit_costs = get_unit_costs(context)
    old_cost = unit_costs[material]
    unit_costs[material] = new_cost
    context.user_data["unit_costs"] = unit_costs
    await update.message.reply_text(
        f"✅ *{material}* updated\nETB {old_cost:.2f} → ETB {new_cost:.2f}\n\nWhat would you like to do next?",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. Type /start to begin again.")
    return ConversationHandler.END

# ─────────────────────────────────────────────
# MAIN — WEBHOOK MODE FOR RENDER
# ─────────────────────────────────────────────

def main():
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    WEBHOOK_URL = os.environ["WEBHOOK_URL"]  # e.g. https://your-app.onrender.com
    PORT = int(os.environ.get("PORT", 8443))

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU:             [CallbackQueryHandler(main_menu_handler)],
            SELECT_GRADE:          [CallbackQueryHandler(select_grade_handler)],
            GRADE_ACTION:          [CallbackQueryHandler(grade_action_handler)],
            ENTER_CUSTOM_MARGIN:   [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_custom_margin)],
            SELECT_COST_MATERIAL:  [CallbackQueryHandler(select_cost_material)],
            ENTER_COST_VALUE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_cost_value)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    )
    app.add_handler(conv)

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/webhook",
    )

if __name__ == "__main__":
    main()
