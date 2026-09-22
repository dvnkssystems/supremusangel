# Scheduled month-end incentive calculation.
#
# On the 1st of each month the scheduler runs `run_monthly_incentives` which,
# for the just-finished month, creates and calculates the right incentive
# document for every enabled Sales Person that has an active linked Employee.
#
# The *scheme* (Salesperson / Team Lead / Branch Manager) is decided by the
# person's position in the Sales Person tree (see ``scheme_from_tree``) -- the
# same single source of truth the ESS commission dashboard uses. Salespeople are
# processed before managers so that a manager's team/branch target (which reads
# each member's SA Incentive Calculation) is already in place.

import frappe
from supremusangel.unlisted_shares.schemes import uses_tier_commission
from frappe.utils import add_months, flt, get_first_day, getdate, nowdate

from supremusangel.supremus_angel.incentive_source import get_monthly_salary
from supremusangel.supremus_angel.sales_person_create import scheme_from_tree

SA_DT = "SA Incentive Calculation"
TL_DT = "SA TL Incentive Calculation"
BM_DT = "SA BM Incentive Calculation"


def _previous_month(as_of=None):
	"""Return the previous calendar month as 'YYYY-MM' (relative to today or
	the given date)."""
	first_of_this_month = get_first_day(getdate(as_of or nowdate()))
	return add_months(first_of_this_month, -1).strftime("%Y-%m")


def _month_end(month):
	"""Last day of a 'YYYY-MM' month, as a date."""
	from calendar import monthrange
	from datetime import date

	year, mon = int(month[:4]), int(month[5:7])
	return date(year, mon, monthrange(year, mon)[1])


def _salary_for(employee, sales_person, month):
	"""Monthly salary for the calc. Thin wrapper over the shared resolver in
	``incentive_source`` so the scheduler, the realtime recalc, the team/branch
	target roll-up and the ESS dashboard all read the same salary."""
	return get_monthly_salary(sales_person, month, employee=employee)


def _already_done(scheme, sales_person, month):
	dt, field = {
		"SA": (SA_DT, "sales_person"),
		"TL": (TL_DT, "team_lead"),
		"BM": (BM_DT, "branch_manager"),
	}[scheme]
	return bool(frappe.db.exists(dt, {field: sales_person, "calculation_month": month}))


def _make_calc(scheme, sales_person, salary, month):
	if scheme == "SA":
		doc = frappe.new_doc(SA_DT)
		doc.sales_person = sales_person
	elif scheme == "TL":
		doc = frappe.new_doc(TL_DT)
		doc.team_lead = sales_person
	else:
		doc = frappe.new_doc(BM_DT)
		doc.branch_manager = sales_person
	doc.salary = salary
	doc.calculation_month = month
	doc.insert(ignore_permissions=True)
	doc.calculate()
	return doc.name


def run_monthly_incentives(month=None):
	"""Scheduler entry point. Calculates incentives for `month` (defaults to the
	previous calendar month). Salespeople first, then TLs, then BMs."""
	month = month or _previous_month()

	# Collect (scheme, sales_person, employee) for every eligible person.
	targets = []
	for sp in frappe.get_all("Sales Person", filters={"enabled": 1}, fields=["name", "employee"]):
		if uses_tier_commission(sp.name):
			continue
		if not sp.employee:
			continue
		emp = frappe.db.get_value(
			"Employee", sp.employee, ["status", "user_id"], as_dict=True
		)
		if not emp or emp.status != "Active" or not emp.user_id:
			continue
		scheme = scheme_from_tree(sp.name)
		if not scheme:
			continue  # unresolved / structural node -> nothing to calculate
		targets.append((scheme, sp.name, sp.employee))

	# Order so managers run after their members' SA calcs exist.
	order = {"SA": 0, "TL": 1, "BM": 2}
	targets.sort(key=lambda t: order[t[0]])

	created, skipped, failed = 0, 0, 0
	for scheme, sales_person, employee in targets:
		try:
			if _already_done(scheme, sales_person, month):
				skipped += 1
				continue
			salary = _salary_for(employee, sales_person, month)
			if not salary:
				skipped += 1
				continue
			_make_calc(scheme, sales_person, salary, month)
			frappe.db.commit()
			created += 1
		except Exception:
			failed += 1
			frappe.db.rollback()
			frappe.log_error(
				title=f"Monthly incentive failed: {scheme} {sales_person} {month}",
				message=frappe.get_traceback(),
			)

	frappe.logger("supremusangel").info(
		f"run_monthly_incentives {month}: created={created} skipped={skipped} failed={failed}"
	)
	return {"month": month, "created": created, "skipped": skipped, "failed": failed}


@frappe.whitelist()
def trigger_monthly_incentives(month=None):
	"""Manual trigger (button / API) for the same job, so admins can run or
	re-run a month on demand."""
	frappe.only_for(("System Manager", "Accounts Manager"))
	return run_monthly_incentives(month)
