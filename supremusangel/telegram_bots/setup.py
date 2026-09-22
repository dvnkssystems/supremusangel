"""Register webhooks for all bots.

bench --site <site> execute supremusangel.telegram_bots.setup.set_webhooks
"""

import frappe

from supremusangel.telegram_bots import tg

WEBHOOK_PATH = "/api/method/supremusangel.telegram_bots.api.webhook"


def set_webhooks():
	base = tg.site_url()
	for s in frappe.get_all("Telegram Settings", fields=["name", "bot_name"]):
		tg.call(
			s.name,
			"setWebhook",
			url=f"{base}{WEBHOOK_PATH}?bot={s.bot_name}",
			secret_token=tg.webhook_secret(s.name),
			allowed_updates=["message", "callback_query"],
			drop_pending_updates=True,
		)
		commands = [{"command": "start", "description": "Start / link your account"}]
		if s.name == "Supremus HR Bot":
			commands.append({"command": "checklist", "description": "My onboarding checklist"})
		tg.call(s.name, "setMyCommands", commands=commands)
		info = tg.call(s.name, "getWebhookInfo")
		print(s.bot_name, info.get("url"), "pending:", info.get("pending_update_count"))


def delete_webhooks():
	for s in frappe.get_all("Telegram Settings", pluck="name"):
		tg.call(s, "deleteWebhook")
