"""Match a Telegram contact to an ERP user and record the link."""

import re

import frappe
from frappe.utils import now_datetime

# Roles allowed per bot (keyed by Telegram Settings.bot_name). None = any active employee.
BOT_ROLES = {
	"supremus_hr_bot": None,
	"supremus_crm_bot": {
		"Tele Caller",
		"Relationship Manager",
		"Wealth Relationship Manager",
		"Team Lead",
		"Branch Manager",
	},
	"supremus_customer_onboarding_bot": {
		"Relationship Manager",
		"Wealth Relationship Manager",
		"Team Lead",
		"Branch Manager",
	},
}


def normalize_phone(value):
	"""Last 10 digits of a phone number, or None if it has fewer than 10."""
	digits = re.sub(r"\D", "", value or "")
	return digits[-10:] if len(digits) >= 10 else None


def find_users_by_phone(phone):
	"""Return the distinct enabled users whose Employee or User record has this number."""
	target = normalize_phone(phone)
	if not target:
		return []

	users = set()
	for e in frappe.get_all(
		"Employee",
		filters={"status": "Active", "user_id": ["is", "set"]},
		fields=["user_id", "cell_number"],
	):
		if normalize_phone(e.cell_number) == target:
			users.add(e.user_id)

	for u in frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User"},
		or_filters={"mobile_no": ["is", "set"], "phone": ["is", "set"]},
		fields=["name", "mobile_no", "phone"],
	):
		if target in (normalize_phone(u.mobile_no), normalize_phone(u.phone)):
			users.add(u.name)

	return [u for u in users if frappe.db.get_value("User", u, "enabled")]


def has_bot_access(bot_name, user):
	allowed = BOT_ROLES.get(bot_name)
	if allowed is None:
		return bool(frappe.db.exists("Employee", {"user_id": user, "status": "Active"}))
	return bool(allowed & set(frappe.get_roles(user)))


def get_link(settings_name, telegram_user_id):
	return frappe.db.get_value(
		"Telegram Link",
		{"telegram_settings": settings_name, "telegram_user_id": str(telegram_user_id), "enabled": 1},
		["name", "user", "full_name"],
		as_dict=True,
	)


def create_link(settings_name, user, sender, chat_id, phone, method):
	"""Create or refresh the Telegram Link, plus the stock Telegram User Settings record."""
	telegram_user_id = str(sender["id"])
	values = {
		"user": user,
		"employee": frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name"),
		"full_name": frappe.db.get_value("User", user, "full_name"),
		"chat_id": str(chat_id),
		"telegram_username": sender.get("username"),
		"phone": phone,
		"link_method": method,
		"linked_on": now_datetime(),
		"enabled": 1,
	}

	existing = frappe.db.get_value(
		"Telegram Link", {"telegram_settings": settings_name, "telegram_user_id": telegram_user_id}
	)
	if existing:
		link = frappe.get_doc("Telegram Link", existing)
		link.update(values)
		link.save(ignore_permissions=True)
	else:
		link = frappe.get_doc(
			{
				"doctype": "Telegram Link",
				"telegram_settings": settings_name,
				"telegram_user_id": telegram_user_id,
				**values,
			}
		).insert(ignore_permissions=True)

	_sync_stock_user_settings(settings_name, user, chat_id, sender.get("username"))
	return link


def _sync_stock_user_settings(settings_name, user, chat_id, username):
	"""Keep erpnext_telegram_integration's Telegram Notification working for linked users."""
	name = frappe.db.get_value("Telegram User Settings", {"telegram_user": user, "telegram_settings": settings_name})
	if name:
		frappe.db.set_value("Telegram User Settings", name, "telegram_chat_id", str(chat_id))
		return
	frappe.get_doc(
		{
			"doctype": "Telegram User Settings",
			"party": "User",
			"telegram_user": user,
			"telegram_user_name": username,
			"telegram_settings": settings_name,
			"telegram_chat_id": str(chat_id),
		}
	).insert(ignore_permissions=True)
