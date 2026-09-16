"""Dispatch an incoming Telegram update. Runs in a background job."""

import frappe
from frappe.utils import escape_html

from supremusangel.telegram_bots import linking, tg

SHARE_PHONE_KEYBOARD = {
	"keyboard": [[{"text": "📱 Share my phone number", "request_contact": True}]],
	"resize_keyboard": True,
	"one_time_keyboard": True,
	"is_persistent": True,
}
REMOVE_KEYBOARD = {"remove_keyboard": True}


def process_update(settings_name, update):
	message = update.get("message")
	if not message or message.get("chat", {}).get("type") != "private":
		return  # group messages and button callbacks are handled in later phases

	try:
		frappe.set_user("Administrator")
		handle_message(settings_name, message)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title=f"Telegram bot {settings_name}", message=frappe.get_traceback())
		_safe_send(settings_name, message["chat"]["id"], "Something went wrong. Please try again or contact admin.")


def handle_message(settings_name, message):
	chat_id = message["chat"]["id"]
	sender = message["from"]
	bot_name = frappe.db.get_value("Telegram Settings", settings_name, "bot_name")

	if message.get("contact"):
		return handle_contact(settings_name, bot_name, message)

	link = linking.get_link(settings_name, sender["id"])
	if not link:
		return tg.send_message(
			settings_name,
			chat_id,
			"👋 Welcome to <b>Supremus Angel</b>.\n\n"
			"To verify who you are, tap <b>📱 Share my phone number</b> below. "
			"It must be the mobile number registered with HR.",
			reply_markup=SHARE_PHONE_KEYBOARD,
		)

	tg.send_message(
		settings_name,
		chat_id,
		f"✅ You are linked as <b>{escape_html(link.full_name or link.user)}</b>.\n\n"
		"Bot features are being rolled out — you will receive updates here.",
		reply_markup=REMOVE_KEYBOARD,
	)


def handle_contact(settings_name, bot_name, message):
	chat_id = message["chat"]["id"]
	sender = message["from"]
	contact = message["contact"]

	if contact.get("user_id") != sender["id"]:
		return tg.send_message(
			settings_name,
			chat_id,
			"Please share <b>your own</b> number using the button below.",
			reply_markup=SHARE_PHONE_KEYBOARD,
		)

	users = linking.find_users_by_phone(contact.get("phone_number"))
	if len(users) != 1:
		reason = "is not registered" if not users else "matches more than one account"
		return tg.send_message(
			settings_name,
			chat_id,
			f"❌ This number {reason} in Supremus ERP.\n\n"
			"Please ask HR to update the mobile number on your employee record, then tap the button again.",
			reply_markup=SHARE_PHONE_KEYBOARD,
		)

	user = users[0]
	if not linking.has_bot_access(bot_name, user):
		return tg.send_message(
			settings_name,
			chat_id,
			"⛔ Your account does not have access to this bot. Contact your manager if you think this is wrong.",
			reply_markup=REMOVE_KEYBOARD,
		)

	link = linking.create_link(
		settings_name, user, sender, chat_id, linking.normalize_phone(contact["phone_number"]), "Phone"
	)
	tg.send_message(
		settings_name,
		chat_id,
		f"✅ Linked as <b>{escape_html(link.full_name or user)}</b>.\n\n"
		"You will now receive Supremus updates here.",
		reply_markup=REMOVE_KEYBOARD,
	)


def _safe_send(settings_name, chat_id, text):
	try:
		tg.send_message(settings_name, chat_id, text, parse_mode=None)
	except Exception:
		pass
