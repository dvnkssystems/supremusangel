import frappe
from frappe.utils import now_datetime


def _get_current_user():
    return frappe.session.user


@frappe.whitelist()
def get_pending_policies():
    user = _get_current_user()
    if user in ("Guest", "Administrator"):
        return []

    # Optionally map User -> Employee to filter by company, etc.
    employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
    # Base filter: active + mandatory_for_new_joinee
    filters=[
        ["active","=",1],
        ["mandatory_for_new_joinee","=",1],
        ["effective_from","<=",frappe.utils.nowdate()]
    ]
    # filters = {
    #     "active": 1,
    #     "mandatory_for_new_joinee": 1,
    #     "effective_from":{frappe.utils.nowdate()}
    # }

    policies = frappe.get_all(
        "Company Policy",
        filters=filters,
        fields=["name", "policy_title", "policy_content", "effective_from","policy_pdf"],
        order_by="effective_from asc, creation asc",
    )

    if not policies:
        return []

    # Get already acknowledged policies for this user
    acknowledged = frappe.get_all(
        "Company Policy Acknowledgement",
        filters={"user": user},
        fields=["policy"],
    )
    acknowledged_set = {d.policy for d in acknowledged}

    pending = [p for p in policies if p["name"] not in acknowledged_set]
    return pending

@frappe.whitelist()
def get_employee_for_user():
    """
    Return employee linked to current user, or None.
    """
    user = frappe.session.user
    emp = frappe.db.get_value("Employee", {"user_id": user}, ["name", "employee_name"], as_dict=True)
    return emp

@frappe.whitelist()
def acknowledge_policies(policy_names: str):
    """
    policy_names: JSON list or comma-separated names of Company Policy docs.
    """
    import json

    user = _get_current_user()
    emp = get_employee_for_user()
    if user in ("Guest", "Administrator"):
        frappe.throw("Not allowed")

    try:
        if policy_names.strip().startswith("["):
            names = json.loads(policy_names)
        else:
            names = [x.strip() for x in policy_names.split(",") if x.strip()]
    except Exception:
        frappe.throw("Invalid input")

    if not names:
        return

    ip = frappe.local.request_ip if hasattr(frappe.local, "request_ip") else None
    # A browser string longer than the field would refuse the whole acknowledgement.
    ua = (frappe.get_request_header("User-Agent") or "")[:140]

    for policy in names:
        # Skip if already acknowledged
        exists = frappe.db.exists(
            "Company Policy Acknowledgement",
            {"user": user, "policy": policy},
        )
        if exists:
            continue

        doc = frappe.get_doc({
            "doctype": "Company Policy Acknowledgement",
            "user": user,
            "employee": emp.name if emp else None,
            "policy": policy,
            "acknowledged_on": now_datetime(),
            "ip_address": ip,
            "user_agent": ua,
        })
        # Rows are named {employee}-{policy}, which is the same for everyone without an Employee.
        doc.insert(ignore_permissions=True, set_name=None if emp else f"{user}-{policy}")

    frappe.db.commit()
    return {"status": "ok"}
