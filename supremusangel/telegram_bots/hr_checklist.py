"""Employee onboarding checklist delivered through the HR bot.

Every item is computed live from the Employee record and related documents, so
the checklist is always current no matter where the employee filled things in
(web onboarding form, desk, or HR on their behalf).
"""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import add_days, escape_html, format_date, format_datetime, getdate, now_datetime, nowdate

from supremusangel.telegram_bots import tg

HR_BOT = "Supremus HR Bot"
HR_ROLES = {"HR Manager", "HR User", "System Manager"}
RECENT_JOINER_DAYS = 45
HR_ESCALATION_DAYS = 3

PERSONAL_FIELDS = ["date_of_birth", "gender", "personal_email", "cell_number", "emergency_phone_number"]
ADDRESS_FIELDS = ["current_address", "permanent_address"]
BANK_FIELDS = ["bank_name", "bank_ac_no", "ifsc_code", "pan_number"]
EMPLOYEE_FIELDS = [
	"name", "employee_name", "user_id", "designation", "branch", "date_of_joining", "image",
	"custom_profile_status", "custom_onboarding_completed", "custom_checklist_completed_on",
	*PERSONAL_FIELDS, *ADDRESS_FIELDS, *BANK_FIELDS,
]  # fmt: skip


# ------------------------------------------------------------------ checklist


def get_checklist(employee):
	"""Return (employee_row, items). Each item: key, label, done, detail, employee_action."""
	emp = frappe.db.get_value("Employee", employee, EMPLOYEE_FIELDS, as_dict=True)

	def missing(fields):
		return [frappe.get_meta("Employee").get_label(f) for f in fields if not emp.get(f)]

	items = []

	linked = bool(
		frappe.db.exists("Telegram Link", {"telegram_settings": HR_BOT, "employee": emp.name, "enabled": 1})
	)
	items.append(_item("telegram", "Telegram linked", linked, "", True))

	for key, label, fields in (
		("personal", "Personal details", PERSONAL_FIELDS),
		("address", "Address", ADDRESS_FIELDS),
		("bank", "Bank & PAN", BANK_FIELDS),
	):
		gaps = missing(fields)
		items.append(_item(key, label, not gaps, "missing: " + ", ".join(gaps) if gaps else "", True))

	items.append(_item("photo", "Profile photo", bool(emp.image), "", True))

	total, agreed = _policy_counts(emp.user_id)
	items.append(_item("policies", "Company policies", agreed >= total, f"{agreed}/{total} agreed", True))

	review_done = emp.custom_profile_status == "Profile Completed"
	items.append(_item("review", "HR profile review", review_done, emp.custom_profile_status or "Pending", False))

	meeting = _orientation_meeting(emp.name)
	items.append(
		_item(
			"orientation",
			"Orientation meeting",
			bool(meeting),
			format_datetime(meeting.meeting_start_time, "dd MMM, hh:mm a") if meeting else "HR will schedule",
			False,
		)
	)
	return emp, items


def _item(key, label, done, detail, employee_action):
	return frappe._dict(key=key, label=label, done=done, detail=detail, employee_action=employee_action)


def _policy_counts(user):
	policies = frappe.get_all(
		"Company Policy",
		filters={"active": 1, "mandatory_for_new_joinee": 1, "effective_from": ["<=", nowdate()]},
		pluck="name",
	)
	if not policies or not user:
		return len(policies), 0
	agreed = frappe.db.count("Company Policy Acknowledgement", {"user": user, "policy": ["in", policies]})
	return len(policies), min(agreed, len(policies))


def _orientation_meeting(employee):
	rows = frappe.db.sql(
		"""
		select m.name, m.meeting_start_time from `tabMeeting` m
		where m.status in ('Scheduled', 'Rescheduled', 'Completed')
		  and (
			(m.meeting_with = 'Employee' and m.meeting_party = %(emp)s)
			or exists (select 1 from `tabMeeting Attendee` a
				where a.parent = m.name and a.party_type = 'Employee' and a.party = %(emp)s)
		  )
		order by m.meeting_start_time desc limit 1
		""",
		{"emp": employee},
		as_dict=True,
	)
	return rows[0] if rows else None


def is_complete(items):
	return all(i.done for i in items)


def employee_actions_pending(items):
	return any(not i.done and i.employee_action for i in items)


# ------------------------------------------------------------------ rendering


def render(emp, items, header=None):
	done = sum(1 for i in items if i.done)
	lines = []
	if header:
		lines += [header, ""]
	lines.append(f"📋 <b>Your Onboarding Checklist — {escape_html(emp.employee_name)}</b>")
	meta = " · ".join(
		escape_html(str(x))
		for x in (emp.designation, emp.branch, emp.date_of_joining and "Joined " + format_date(emp.date_of_joining, "dd MMM"))
		if x
	)
	if meta:
		lines.append(meta)
	lines.append("")
	for n, i in enumerate(items, 1):
		detail = f"  <i>({escape_html(i.detail)})</i>" if i.detail and not i.done else ""
		if i.done and i.key == "orientation":
			detail = f"  <i>({escape_html(i.detail)})</i>"
		lines.append(f"{'✅' if i.done else '⬜'} {n}. {i.label}{detail}")
	lines += ["", f"<b>Progress: {done}/{len(items)}</b>"]
	if not is_complete(items):
		lines.append("Tap <b>Fill details</b> to complete pending items in Supremus ERP.")
	return "\n".join(lines), _keyboard()


def _keyboard():
	base = tg.site_url()
	return {
		"inline_keyboard": [
			[{"text": "📝 Fill details", "url": f"{base}/app/onboarding"}],
			[
				{"text": "📄 Upload documents", "url": f"{base}/app/onboarding"},
				{"text": "📜 Policies", "url": f"{base}/app"},
			],
			[{"text": "🔄 Refresh", "callback_data": "chk:refresh"}],
		]
	}


# ------------------------------------------------------------------ sending


def get_hr_chat_id(employee):
	return frappe.db.get_value(
		"Telegram Link", {"telegram_settings": HR_BOT, "employee": employee, "enabled": 1}, "chat_id"
	)


def send_checklist(employee, header=None):
	"""Send the checklist to the employee. Returns False if they have not linked the HR bot."""
	chat_id = get_hr_chat_id(employee)
	if not chat_id:
		return False
	emp, items = get_checklist(employee)
	if _mark_complete_if_done(emp, items):
		return True
	text, keyboard = render(emp, items, header)
	tg.send_message(HR_BOT, chat_id, text, reply_markup=keyboard)
	return True


def refresh_message(chat_id, message_id, employee):
	emp, items = get_checklist(employee)
	text, keyboard = render(emp, items)
	try:
		tg.call(
			HR_BOT, "editMessageText", chat_id=chat_id, message_id=message_id, text=text,
			parse_mode="HTML", reply_markup=keyboard,
		)  # fmt: skip
	except tg.TelegramError as e:
		if "message is not modified" not in (e.description or ""):
			raise
	_mark_complete_if_done(emp, items)


def _mark_complete_if_done(emp, items):
	"""On first full completion: stamp the Employee, congratulate, tell HR. Returns True if it fired."""
	if not is_complete(items) or emp.custom_checklist_completed_on:
		return False
	frappe.db.set_value(
		"Employee", emp.name,
		{"custom_checklist_completed_on": now_datetime(), "custom_onboarding_completed": 1},
	)  # fmt: skip
	chat_id = get_hr_chat_id(emp.name)
	if chat_id:
		tg.send_message(
			HR_BOT, chat_id,
			f"🎉 <b>Congratulations, {escape_html(emp.employee_name)}!</b>\n\n"
			"Your onboarding checklist is complete. Welcome to Supremus Angel!",
		)  # fmt: skip
	_notify_hr(f"🎉 <b>{escape_html(emp.employee_name)}</b> ({emp.name}) has completed the onboarding checklist.")
	return True


def _notify_hr(text):
	hr_users = frappe.get_all(
		"Has Role",
		filters={"role": ["in", ["HR Manager"]], "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	for chat_id in frappe.get_all(
		"Telegram Link",
		filters={"telegram_settings": HR_BOT, "enabled": 1, "user": ["in", hr_users or [""]]},
		pluck="chat_id",
		distinct=True,
	):
		try:
			tg.send_message(HR_BOT, chat_id, text)
		except Exception:
			frappe.log_error(title="Telegram HR notify failed", message=frappe.get_traceback())


# ------------------------------------------------------------------ desk button


@frappe.whitelist()
def send_checklist_from_desk(employee):
	if not HR_ROLES & set(frappe.get_roles()):
		frappe.throw(_("Only HR can send the onboarding checklist"), frappe.PermissionError)
	frappe.has_permission("Employee", "read", employee, throw=True)

	if send_checklist(employee):
		return {"sent": True}

	emp = frappe.db.get_value("Employee", employee, ["employee_name", "cell_number"], as_dict=True)
	bot_name = frappe.db.get_value("Telegram Settings", HR_BOT, "bot_name")
	text = (
		f"Hi {emp.employee_name}, welcome to Supremus Angel!\n\n"
		f"Please complete your onboarding on Telegram:\n"
		f"1. Open https://t.me/{bot_name}\n"
		f"2. Tap Start\n"
		f"3. Tap 'Share my phone number'\n\n"
		f"Your onboarding checklist will appear right after."
	)
	phone = "".join(c for c in (emp.cell_number or "") if c.isdigit())[-10:]
	return {
		"sent": False,
		"text": text,
		"whatsapp_url": f"https://wa.me/91{phone}?text={quote(text)}" if len(phone) == 10 else None,
	}


# ------------------------------------------------------------------ daily job


def daily_reminders():
	"""Mon–Sat 10:00. Remind employees with pending items; send HR a summary."""
	if getdate().weekday() == 6:
		return
	since = add_days(nowdate(), -RECENT_JOINER_DAYS)
	employees = frappe.db.sql(
		"""
		select name from `tabEmployee`
		where status = 'Active' and custom_checklist_completed_on is null
		  and (ifnull(custom_onboarding_completed, 0) = 0 or date_of_joining >= %s)
		order by date_of_joining desc
		""",
		since,
		pluck=True,
	)

	summary = []
	for employee in employees:
		try:
			emp, items = get_checklist(employee)
			if _mark_complete_if_done(emp, items):
				continue
			if employee_actions_pending(items) and get_hr_chat_id(employee):
				text, keyboard = render(emp, items, header="⏰ <b>Reminder:</b> a few onboarding items are still pending.")
				tg.send_message(HR_BOT, get_hr_chat_id(employee), text, reply_markup=keyboard)
			summary.append((emp, items))
		except Exception:
			frappe.log_error(title=f"Onboarding checklist reminder {employee}", message=frappe.get_traceback())

	if summary:
		_notify_hr(_hr_summary(summary))


def _hr_summary(rows):
	lines = [f"📋 <b>Onboarding pending — {len(rows)} employee(s)</b>", ""]
	for emp, items in rows[:20]:
		done = sum(1 for i in items if i.done)
		days = (getdate() - getdate(emp.date_of_joining)).days if emp.date_of_joining else 0
		flag = "⚠️ " if days > HR_ESCALATION_DAYS else ""
		pending = ", ".join(i.label for i in items if not i.done)
		lines.append(f"{flag}<b>{escape_html(emp.employee_name)}</b> ({emp.name}) · {done}/{len(items)} · day {days}")
		lines.append(f"   <i>{escape_html(pending)}</i>")
	if len(rows) > 20:
		lines.append(f"…and {len(rows) - 20} more")
	return "\n".join(lines)
