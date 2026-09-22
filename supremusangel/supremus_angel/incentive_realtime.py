# Copyright (c) 2026, Aniket Shinde and contributors
# For license information, please see license.txt

"""Real-time incentive recalculation.

The incentive scheme is still monthly (salary-based target, cumulative-
achievement slabs, reward on sales above target -- see the calc controllers).
This module just keeps those monthly figures *live*: the moment a Sales Invoice
is submitted or cancelled we refresh the affected people's current-month
calculation instead of waiting for the month-end scheduler job. The economics
are unchanged -- same ``calculate()`` math -- the numbers are simply always up
to date on the ESS dashboard.

Flow (per submit/cancel):
  1. Collect the Sales Persons credited on the invoice (its Sales Team).
  2. Add their managers (any Team Lead / Branch Manager above them in the
     Sales Person tree) so team/branch totals refresh too.
  3. Upsert each person's calc for the invoice's posting month and re-run
     calculate(), Salespeople first so managers read fresh member numbers.

The work runs in a background job (enqueued after the invoice commits) so
invoice submission stays fast and a calc error can never block a submit.
Approved / Paid calculations are left untouched -- a new invoice must never
silently rewrite a payout that has already been locked in.
"""

import frappe
from supremusangel.unlisted_shares.schemes import is_monthly_invoice, uses_tier_commission
from frappe.utils import getdate

from supremusangel.supremus_angel.incentive_tasks import (
	BM_DT,
	SA_DT,
	TL_DT,
	_salary_for,
)
from supremusangel.supremus_angel.sales_person_create import scheme_from_tree

# Statuses whose calc must not be overwritten by a live recompute.
LOCKED_STATUSES = {"Approved", "Paid"}

# Salespeople before Team Leads before Branch Managers, so a manager's recompute
# reads its members' freshly-updated SA calcs.
_ORDER = {"SA": 0, "TL": 1, "BM": 2}
_DOCTYPE = {"SA": SA_DT, "TL": TL_DT, "BM": BM_DT}
_LINK_FIELD = {"SA": "sales_person", "TL": "team_lead", "BM": "branch_manager"}


# --------------------------------------------------------------------- hooks


def on_invoice_submit(doc, method=None):
	_enqueue_recalc(doc)


def on_invoice_cancel(doc, method=None):
	_enqueue_recalc(doc)


def _enqueue_recalc(doc):
	if not is_monthly_invoice(doc):
		return
	persons = _sales_persons_on_invoice(doc)
	if not persons:
		return

	frappe.enqueue(
		"supremusangel.supremus_angel.incentive_realtime.recalculate_persons",
		queue="long",
		enqueue_after_commit=True,
		persons=persons,
		month=_month_of(doc.posting_date),
		source_invoice=doc.name,
	)


# ------------------------------------------------------------------ worker


def recalculate_persons(persons, month, source_invoice=None):
	"""Refresh the month's incentive calc for ``persons`` and their managers.

	Runs one person per transaction (commit/rollback each) so a single bad calc
	can't take down the rest, mirroring the monthly scheduler job."""
	work = _build_work_list(persons, month)

	done = skipped = failed = 0
	for scheme, sales_person in work:
		try:
			if _upsert_calc(scheme, sales_person, month):
				done += 1
			else:
				skipped += 1
			frappe.db.commit()
		except Exception:
			failed += 1
			frappe.db.rollback()
			frappe.log_error(
				title=f"Realtime incentive failed: {scheme} {sales_person} {month}",
				message=frappe.get_traceback(),
			)

	frappe.logger("supremusangel").info(
		f"recalculate_persons {month} src={source_invoice}: "
		f"done={done} skipped={skipped} failed={failed}"
	)
	return {"month": month, "done": done, "skipped": skipped, "failed": failed}


def _build_work_list(persons, month):
	"""Ordered [(scheme, sales_person)] for the affected people plus every
	Team Lead / Branch Manager above them, deduplicated and SA -> TL -> BM."""
	scheme_by_person = {}

	for sp in persons:
		if sp and sp not in scheme_by_person and not uses_tier_commission(sp):
			scheme_by_person[sp] = _scheme_of(sp)

	for sp in persons:
		for ancestor in _ancestors(sp):
			if ancestor in scheme_by_person or uses_tier_commission(ancestor):
				continue
			scheme = _scheme_of(ancestor)
			if scheme in ("TL", "BM"):
				scheme_by_person[ancestor] = scheme

	work = list(scheme_by_person.items())  # (sales_person, scheme)
	work.sort(key=lambda item: _ORDER.get(item[1], 9))
	return [(scheme, sp) for sp, scheme in work]


def _upsert_calc(scheme, sales_person, month):
	"""Find-or-create the calc for (person, month) and re-run calculate().

	Returns True when recomputed, False when intentionally skipped (locked
	status, or a brand-new calc for which no salary could be resolved)."""
	if uses_tier_commission(sales_person):
		return False
	doctype = _DOCTYPE[scheme]
	field = _LINK_FIELD[scheme]

	existing = frappe.db.get_value(
		doctype,
		{field: sales_person, "calculation_month": month},
		["name", "status"],
		as_dict=True,
	)
	if existing:
		if existing.status in LOCKED_STATUSES:
			return False
		doc = frappe.get_doc(doctype, existing.name)
		doc.calculate()
		return True

	# No calc yet -> create one only if we can resolve a salary for the month.
	employee = frappe.db.get_value("Sales Person", sales_person, "employee")
	if not employee:
		return False
	salary = _salary_for(employee, sales_person, month)
	if not salary:
		return False

	doc = frappe.new_doc(doctype)
	doc.set(field, sales_person)
	doc.salary = salary
	doc.calculation_month = month
	doc.insert(ignore_permissions=True)
	doc.calculate()
	return True


# ------------------------------------------------------------------ helpers


def _sales_persons_on_invoice(doc):
	return list({row.sales_person for row in (doc.get("sales_team") or []) if row.sales_person})


def _month_of(posting_date):
	return getdate(posting_date).strftime("%Y-%m")


def _scheme_of(sales_person):
	"""BM / TL / SA from the Sales Person's position in the tree (single source
	of truth). Falls back to SA for an unresolved node so a credited seller is
	never dropped from the recompute."""
	return scheme_from_tree(sales_person) or "SA"


def _ancestors(sales_person):
	"""Every Sales Person node strictly above ``sales_person`` in the tree."""
	node = frappe.db.get_value("Sales Person", sales_person, ["lft", "rgt"], as_dict=True)
	if not node:
		return []
	return frappe.get_all(
		"Sales Person",
		filters={"lft": ["<", node.lft], "rgt": [">", node.rgt]},
		pluck="name",
	)
