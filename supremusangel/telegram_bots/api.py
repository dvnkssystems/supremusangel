import hmac
import json

import frappe

from supremusangel.telegram_bots import tg


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook(bot=None):
	"""Receive a Telegram update. Always answers 200 quickly; work happens in a job."""
	settings_name = frappe.db.get_value("Telegram Settings", {"bot_name": bot}, "name") if bot else None
	if not settings_name:
		frappe.local.response["http_status_code"] = 404
		return

	received = frappe.get_request_header("X-Telegram-Bot-Api-Secret-Token") or ""
	if not hmac.compare_digest(received, tg.webhook_secret(settings_name)):
		frappe.local.response["http_status_code"] = 403
		return

	update = json.loads(frappe.request.get_data(as_text=True) or "{}")
	frappe.enqueue(
		"supremusangel.telegram_bots.router.process_update",
		queue="short",
		settings_name=settings_name,
		update=update,
	)
	return "ok"
