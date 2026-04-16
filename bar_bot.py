#!/usr/bin/env python3
"""Bar Budget Tracker Telegram Bot

A simple bot to track drink spending against an event budget.
"""

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
AWAITING_BUDGET, MAIN_MENU, ADD_MENU, REMOVE_MENU, AWAITING_QUANTITY = range(5)

# Price tiers
PRICE_TIERS = [2.0, 3.5, 4.5, 6.0]

# Session data (in-memory, resets on restart)
session = {
    "budget": 0.0,
    "total": 0.0,
    "items": {price: 0 for price in PRICE_TIERS},
    "warning_sent": False,
    "threshold_sent": False,
    "active": False,
    "pending_action": None,  # For "Add Multiple" flow
    "pending_price": None,
}


def reset_session():
    """Reset session to initial state."""
    session["budget"] = 0.0
    session["total"] = 0.0
    session["items"] = {price: 0 for price in PRICE_TIERS}
    session["warning_sent"] = False
    session["threshold_sent"] = False
    session["active"] = False
    session["pending_action"] = None
    session["pending_price"] = None


def format_price(price: float) -> str:
    """Format price for display."""
    if price == int(price):
        return f"{int(price)}€"
    return f"{price:.2f}€".replace(".", ",")


def build_main_menu() -> InlineKeyboardMarkup:
    """Build the main menu keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("➕ Add", callback_data="menu_add"),
            InlineKeyboardButton("➖ Remove", callback_data="menu_remove"),
        ],
        [
            InlineKeyboardButton("📊 Summary", callback_data="menu_summary"),
            InlineKeyboardButton("🔄 New Session", callback_data="menu_new"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_price_menu(action: str) -> InlineKeyboardMarkup:
    """Build the price selection keyboard."""
    keyboard = [
        [InlineKeyboardButton(format_price(price), callback_data=f"{action}_{price}")
         for price in PRICE_TIERS],
        [
            InlineKeyboardButton("Add Multiple...", callback_data=f"{action}_multiple"),
            InlineKeyboardButton("← Back", callback_data="back_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_multiple_price_menu(action: str) -> InlineKeyboardMarkup:
    """Build the price selection keyboard for multiple items."""
    keyboard = [
        [InlineKeyboardButton(format_price(price), callback_data=f"multi_{action}_{price}")
         for price in PRICE_TIERS],
        [InlineKeyboardButton("← Back", callback_data=f"menu_{action}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_confirmation_menu() -> InlineKeyboardMarkup:
    """Build the new session confirmation keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("Yes, start new", callback_data="confirm_new_yes"),
            InlineKeyboardButton("No, go back", callback_data="confirm_new_no"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_main_menu_text() -> str:
    """Generate the main menu text with current status."""
    if session["budget"] > 0:
        percentage = (session["total"] / session["budget"]) * 100
        return (
            f"💰 Total: {session['total']:.2f}€ / {session['budget']:.2f}€ ({percentage:.1f}%)\n\n"
            "What would you like to do?"
        )
    return "No budget set. Use /start to begin."


async def check_and_send_alerts(update: Update) -> None:
    """Check budget thresholds and send one-time alerts."""
    if session["budget"] <= 0:
        return

    percentage = (session["total"] / session["budget"]) * 100

    # 83% warning (once)
    if percentage >= 83 and not session["warning_sent"]:
        session["warning_sent"] = True
        await update.effective_message.reply_text(
            f"⚠️ Warning: You've used {percentage:.1f}% of your budget!\n"
            f"Remaining: {session['budget'] - session['total']:.2f}€"
        )

    # 100% threshold (once)
    if percentage >= 100 and not session["threshold_sent"]:
        session["threshold_sent"] = True
        await update.effective_message.reply_text(
            f"🚨 Budget reached! You've spent {session['total']:.2f}€ "
            f"(budget was {session['budget']:.2f}€)\n"
            "You can continue tracking if needed."
        )


def format_summary() -> str:
    """Generate the end-of-event summary."""
    lines = ["📊 *Event Summary*\n"]

    # Budget overview
    remaining = session["budget"] - session["total"]
    percentage = (session["total"] / session["budget"]) * 100 if session["budget"] > 0 else 0

    lines.append(f"Budget: {session['budget']:.2f}€")
    lines.append(f"*Total spent: {session['total']:.2f}€* ({percentage:.1f}%)")

    if remaining >= 0:
        lines.append(f"Remaining: {remaining:.2f}€")
    else:
        lines.append(f"Over budget by: {abs(remaining):.2f}€")

    lines.append("\n*Breakdown:*")

    # Item breakdown
    total_items = 0
    for price in PRICE_TIERS:
        count = session["items"][price]
        if count > 0:
            subtotal = price * count
            lines.append(f"  {format_price(price)}: {count}x = {subtotal:.2f}€")
            total_items += count

    if total_items == 0:
        lines.append("  No items recorded yet")
    else:
        lines.append(f"\n*Total items served: {total_items}*")

    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start command."""
    reset_session()
    await update.message.reply_text(
        "🍻 *Bar Budget Tracker*\n\n"
        "Enter your event budget (in EUR):",
        parse_mode="Markdown"
    )
    return AWAITING_BUDGET


async def receive_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle budget input."""
    try:
        # Handle both . and , as decimal separator
        text = update.message.text.replace(",", ".").strip()
        budget = float(text)

        if budget <= 0:
            await update.message.reply_text(
                "❌ Please enter a positive number for the budget:"
            )
            return AWAITING_BUDGET

        session["budget"] = budget
        session["active"] = True

        await update.message.reply_text(
            f"✅ Budget set to {budget:.2f}€\n\n" + get_main_menu_text(),
            reply_markup=build_main_menu()
        )
        return MAIN_MENU

    except ValueError:
        await update.message.reply_text(
            "❌ Invalid amount. Please enter a number (e.g., 300 or 150.50):"
        )
        return AWAITING_BUDGET


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle all button callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data

    # Main menu navigation
    if data == "menu_add":
        await query.edit_message_text(
            "➕ *Add drink*\n\nSelect price:",
            reply_markup=build_price_menu("add"),
            parse_mode="Markdown"
        )
        return ADD_MENU

    elif data == "menu_remove":
        await query.edit_message_text(
            "➖ *Remove drink*\n\nSelect price:",
            reply_markup=build_price_menu("remove"),
            parse_mode="Markdown"
        )
        return REMOVE_MENU

    elif data == "menu_summary":
        await query.edit_message_text(
            format_summary(),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("← Back", callback_data="back_main")]
            ]),
            parse_mode="Markdown"
        )
        return MAIN_MENU

    elif data == "menu_new":
        await query.edit_message_text(
            "🔄 *Start new session?*\n\nThis will clear all current data.",
            reply_markup=build_confirmation_menu(),
            parse_mode="Markdown"
        )
        return MAIN_MENU

    elif data == "confirm_new_yes":
        reset_session()
        await query.edit_message_text(
            "🍻 *New Session*\n\nEnter your event budget (in EUR):",
            parse_mode="Markdown"
        )
        return AWAITING_BUDGET

    elif data == "confirm_new_no" or data == "back_main":
        await query.edit_message_text(
            get_main_menu_text(),
            reply_markup=build_main_menu()
        )
        return MAIN_MENU

    # Add single item
    elif data.startswith("add_") and not data.endswith("_multiple"):
        price = float(data.split("_")[1])
        session["total"] += price
        session["items"][price] += 1

        await query.edit_message_text(
            f"✅ Added 1x {format_price(price)}\n\n" + get_main_menu_text(),
            reply_markup=build_main_menu()
        )
        await check_and_send_alerts(update)
        return MAIN_MENU

    # Remove single item
    elif data.startswith("remove_") and not data.endswith("_multiple"):
        price = float(data.split("_")[1])

        if session["items"][price] > 0:
            session["total"] -= price
            session["items"][price] -= 1
            # Ensure total doesn't go below 0 due to floating point
            session["total"] = max(0, session["total"])

            await query.edit_message_text(
                f"✅ Removed 1x {format_price(price)}\n\n" + get_main_menu_text(),
                reply_markup=build_main_menu()
            )
        else:
            await query.edit_message_text(
                f"❌ No {format_price(price)} items to remove\n\n" + get_main_menu_text(),
                reply_markup=build_main_menu()
            )
        return MAIN_MENU

    # Add Multiple - select price
    elif data == "add_multiple":
        await query.edit_message_text(
            "➕ *Add Multiple*\n\nSelect price:",
            reply_markup=build_multiple_price_menu("add"),
            parse_mode="Markdown"
        )
        return ADD_MENU

    # Remove Multiple - select price
    elif data == "remove_multiple":
        await query.edit_message_text(
            "➖ *Remove Multiple*\n\nSelect price:",
            reply_markup=build_multiple_price_menu("remove"),
            parse_mode="Markdown"
        )
        return REMOVE_MENU

    # Multi add - price selected, now ask quantity
    elif data.startswith("multi_add_"):
        price = float(data.split("_")[2])
        session["pending_action"] = "add"
        session["pending_price"] = price

        await query.edit_message_text(
            f"➕ Adding {format_price(price)} drinks\n\nHow many?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("← Cancel", callback_data="menu_add")]
            ])
        )
        return AWAITING_QUANTITY

    # Multi remove - price selected, now ask quantity
    elif data.startswith("multi_remove_"):
        price = float(data.split("_")[2])
        session["pending_action"] = "remove"
        session["pending_price"] = price

        max_items = session["items"][price]
        await query.edit_message_text(
            f"➖ Removing {format_price(price)} drinks (max: {max_items})\n\nHow many?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("← Cancel", callback_data="menu_remove")]
            ])
        )
        return AWAITING_QUANTITY

    return MAIN_MENU


async def receive_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle quantity input for multiple items."""
    try:
        quantity = int(update.message.text.strip())

        if quantity <= 0:
            await update.message.reply_text(
                "❌ Please enter a positive number:"
            )
            return AWAITING_QUANTITY

        price = session["pending_price"]
        action = session["pending_action"]

        if action == "add":
            session["total"] += price * quantity
            session["items"][price] += quantity

            await update.message.reply_text(
                f"✅ Added {quantity}x {format_price(price)} ({price * quantity:.2f}€)\n\n"
                + get_main_menu_text(),
                reply_markup=build_main_menu()
            )
            await check_and_send_alerts(update)

        elif action == "remove":
            max_items = session["items"][price]
            actual_quantity = min(quantity, max_items)

            if actual_quantity > 0:
                session["total"] -= price * actual_quantity
                session["items"][price] -= actual_quantity
                session["total"] = max(0, session["total"])

                msg = f"✅ Removed {actual_quantity}x {format_price(price)} ({price * actual_quantity:.2f}€)"
                if actual_quantity < quantity:
                    msg += f"\n(Only {max_items} were available)"
            else:
                msg = f"❌ No {format_price(price)} items to remove"

            await update.message.reply_text(
                msg + "\n\n" + get_main_menu_text(),
                reply_markup=build_main_menu()
            )

        # Clear pending action
        session["pending_action"] = None
        session["pending_price"] = None

        return MAIN_MENU

    except ValueError:
        await update.message.reply_text(
            "❌ Please enter a whole number (e.g., 3):"
        )
        return AWAITING_QUANTITY


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel command."""
    session["pending_action"] = None
    session["pending_price"] = None

    if session["active"]:
        await update.message.reply_text(
            get_main_menu_text(),
            reply_markup=build_main_menu()
        )
        return MAIN_MENU
    else:
        await update.message.reply_text(
            "No active session. Use /start to begin."
        )
        return ConversationHandler.END


def main() -> None:
    """Start the bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set!")
        return

    # Create application
    application = Application.builder().token(token).build()

    # Define conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AWAITING_BUDGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_budget)
            ],
            MAIN_MENU: [
                CallbackQueryHandler(handle_callback),
            ],
            ADD_MENU: [
                CallbackQueryHandler(handle_callback),
            ],
            REMOVE_MENU: [
                CallbackQueryHandler(handle_callback),
            ],
            AWAITING_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_quantity),
                CallbackQueryHandler(handle_callback),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    )

    application.add_handler(conv_handler)

    # Start the bot
    logger.info("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
