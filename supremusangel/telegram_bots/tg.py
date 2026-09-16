"""Minimal synchronous Telegram Bot API client.

Frappe workers are synchronous, so we call the HTTP API directly with
`requests` instead of python-telegram-bot's asyncio client.
"""

import hashlib

import frappe
import requests

API_BASE = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 15


class TelegramError(Exception):
	def __init__(self, method, status, description):
		super().__init__(f"{method}: {status} {description}")
		self.status = status
		self.description = description


def get_token(settings_name):
	return frappe.db.get_value("Telegram Settings", settings_name, "telegram_token")


def call(settings_name, method, **payload):
	token = get_token(settings_name)
	if not token:
		frappe.throw(f"Telegram Settings {settings_name} has no token")
	resp = requests.post(API_BASE.format(token=token, method=method), json=payload, timeout=TIMEOUT)
	data = resp.json()
	if not data.get("ok"):
		raise TelegramError(method, resp.status_code, data.get("description"))
	return data.get("result")


def send_message(settings_name, chat_id, text, reply_markup=None, parse_mode="HTML"):
	payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
	if reply_markup is not None:
		payload["reply_markup"] = reply_markup
	return call(settings_name, "sendMessage", **payload)


def webhook_secret(settings_name):
	"""Per-bot secret derived from the bot token and the site's encryption key.

	Nothing extra to store, and it changes automatically when a token is rotated.
	"""
	token = get_token(settings_name) or ""
	key = frappe.local.conf.get("encryption_key") or ""
	return hashlib.sha256(f"{key}:{token}".encode()).hexdigest()
