# Copyright (c) 2026, Aniket Shinde and contributors
# For license information, please see license.txt

"""Single source of truth for incentive sales figures.

Sales are read straight from the core ERPNext **Sales Invoice** and its
**Sales Team** allocation table — no custom sales doctype is involved. A
person's credited sales for an invoice = invoice net total x their
allocated_percentage. Only submitted (docstatus = 1) invoices in the window
count; cancelled invoices (docstatus = 2) and credit-note returns net out
naturally because their net_total is negative.
"""

import calendar
from datetime import date

import frappe
from frappe.utils import flt
from supremusangel.unlisted_shares.schemes import monthly_invoice_condition


def month_range(month):
	"""("YYYY-MM") -> ("YYYY-MM-01", "YYYY-MM-<last day>"). (None, None) when malformed."""
	if not month or len(str(month)) < 7:
		return None, None
	try:
		year = int(str(month)[:4])
		mon = int(str(month)[5:7])
		last_day = calendar.monthrange(year, mon)[1]
		return date(year, mon, 1).strftime("%Y-%m-%d"), date(year, mon, last_day).strftime("%Y-%m-%d")
	except (ValueError, IndexError):
		return None, None


def get_monthly_salary(sales_person, month, employee=None):
	"""The monthly salary a person's target is derived from, for ``month``.

	Prefers the Salary Structure Assignment base effective as of month-end, and
	falls back to the salary their most recent incentive calculation was run
	with. Returns 0 when neither exists -- the caller then cannot derive a
	target for this person.
	"""
	if employee is None:
		employee = frappe.db.get_value("Sales Person", sales_person, "employee")

	if employee and frappe.db.table_exists("Salary Structure Assignment"):
		_, to_date = month_range(month)
		if to_date:
			rows = frappe.get_all(
				"Salary Structure Assignment",
				filters={"employee": employee, "docstatus": 1, "from_date": ["<=", to_date]},
				fields=["base"],
				order_by="from_date desc",
				limit=1,
			)
			if rows and flt(rows[0].base):
				return flt(rows[0].base)

	# Carry forward the last salary this person's incentive was calculated with.
	for doctype, field in (
		("SA BM Incentive Calculation", "branch_manager"),
		("SA TL Incentive Calculation", "team_lead"),
		("SA Incentive Calculation", "sales_person"),
	):
		prior = frappe.get_all(
			doctype,
			filters={field: sales_person},
			fields=["salary"],
			order_by="calculation_month desc",
			limit=1,
		)
		if prior and flt(prior[0].salary):
			return flt(prior[0].salary)

	return 0.0


def get_member_target(member, month, settings, employee=None):
	"""``(target, salary, has_calculation)`` for one team / branch member.

	A manager's team/branch target is the sum of their members' individual
	targets, so this is what that roll-up is built from.

	The member's own calculation for the month wins -- that is the figure they are
	officially measured against. A branch contains Team Leads and nested Branch
	Managers as well as salespeople, so all three calc types are checked, manager
	schemes first. When no calc exists yet the target falls back to
	``salary x target_multiple``, the same formula the calc itself would use.
	Without that fallback a missing calc contributed 0, which silently zeroed the
	whole team/branch target and with it the achievement % and the commission.
	"""
	for doctype, person_field, target_field in (
		("SA BM Incentive Calculation", "branch_manager", "personal_target"),
		("SA TL Incentive Calculation", "team_lead", "personal_target"),
		("SA Incentive Calculation", "sales_person", "base_target"),
	):
		calc = frappe.get_all(
			doctype,
			filters={person_field: member, "calculation_month": month},
			fields=["salary", f"{target_field} as target"],
			limit=1,
		)
		if calc:
			salary = flt(calc[0].salary)
			return (flt(calc[0].target) or salary * flt(settings.target_multiple)), salary, 1

	salary = get_monthly_salary(member, month, employee=employee)
	return salary * flt(settings.target_multiple), salary, 0


def get_group_commission(full_target, sales, min_achievement, on_target_percent, overachieved_percent):
	"""A manager's commission on their team's / branch's combined sales.

	Identical shape for a Team Lead and a Branch Manager -- only the rates differ
	(TL 1%, BM 0.5%). Three bands, measured against the FULL group target (the sum
	of every member's own target):

	  * below ``min_achievement``       -> nothing.
	  * ``min_achievement`` .. 100%     -> the rate applies ONLY to the slice of
	    sales sitting above the ``min_achievement`` floor, not to the whole of
	    sales. On a 20,00,000 target with 16,00,000 sold (80%), a TL is paid 1% of
	    (16,00,000 - 14,20,000) = 1,800, not 1% of 16,00,000.
	  * above 100%                      -> the rate applies to the WHOLE of sales.
	    Same target with 25,00,000 sold pays 1% of 25,00,000 = 25,000.

	Crossing 100% therefore steps the payout up sharply. That is deliberate -- it
	is the scheme's over-target reward -- not a rounding artefact.

	Returns ``(amount, rate_applied, achievement_percent)``.
	"""
	sales = flt(sales)
	full_target = flt(full_target)
	achievement = (sales / full_target * 100) if full_target else 0.0

	if not full_target or achievement < flt(min_achievement):
		return 0.0, 0.0, achievement

	if achievement > 100:
		# A blank overachieved rate (e.g. a site whose settings predate the field)
		# must not zero the commission of a team that beat its target -- fall back
		# to the on-target rate.
		rate = flt(overachieved_percent) or flt(on_target_percent)
		return sales * rate / 100, rate, achievement

	rate = flt(on_target_percent)
	floor = full_target * flt(min_achievement) / 100
	return max(sales - floor, 0.0) * rate / 100, rate, achievement


def get_sales_rows(sales_person, from_date, to_date):
	"""Per-invoice credited sales for a Sales Person within [from_date, to_date]."""
	if not (sales_person and from_date and to_date):
		return []

	rows = frappe.db.sql(
		f"""
		SELECT si.name AS sales_invoice,
		       si.posting_date,
		       si.customer,
		       si.net_total,
		       si.grand_total,
		       st.allocated_percentage
		FROM `tabSales Team` st
		INNER JOIN `tabSales Invoice` si ON si.name = st.parent
		WHERE st.parenttype = 'Sales Invoice'
		  AND st.sales_person = %(sp)s
		  AND si.docstatus = 1
		  AND {monthly_invoice_condition()}
		  AND si.posting_date BETWEEN %(fd)s AND %(td)s
		ORDER BY si.posting_date ASC
		""",
		{"sp": sales_person, "fd": from_date, "td": to_date},
		as_dict=True,
	)

	for r in rows:
		pct = 100 if r.allocated_percentage is None else flt(r.allocated_percentage)
		base = flt(r.net_total) or flt(r.grand_total)
		r.allocated_percentage = pct
		r.credited_amount = base * pct / 100
	return rows


def get_total_sales(sales_person, from_date, to_date):
	"""Sum of credited sales for a Sales Person within the window."""
	return sum(flt(r.credited_amount) for r in get_sales_rows(sales_person, from_date, to_date))


def get_settings():
	"""The single source of all incentive rules (slabs + commission rates)."""
	return frappe.get_cached_doc("SA Incentive Settings")
