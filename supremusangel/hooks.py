app_name = "supremusangel"
app_title = "Supremus Angel"
app_publisher = "Aniket Shinde"
app_description = "Customisations for Supremus Angel"
app_email = "aniket@dvnks.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "supremusangel",
# 		"logo": "/assets/supremusangel/logo.png",
# 		"title": "Supremus Angel",
# 		"route": "/supremusangel",
# 		"has_permission": "supremusangel.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/supremusangel/css/supremusangel.css"
app_include_js = [
    "/assets/supremusangel/js/policy_ack.bundle.js",
    "/assets/supremusangel/js/shortcut_single_fix.bundle.js",
    "/assets/supremusangel/js/notification_sound.bundle.js",
]

# Web Routes
website_route_rules = [
    {"from_route": "/apply", "to_route": "apply"},
]

# Web includes (CSS/JS bundles)
web_include_css = [
    "/assets/supremusangel/css/job_application.bundle.css"
]

web_include_js = [
    "/assets/supremusangel/js/job_application.bundle.js"
]

website_generators = ["Job Opening"]
# on_session_creation = "supremusangel.supremus_angel.page.onboarding.onboarding.after_login"
# include js, css files in header of web template
# web_include_css = "/assets/supremusangel/css/supremusangel.css"
# web_include_js = "/assets/supremusangel/js/supremusangel.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "supremusangel/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
    "Customer": "public/js/customer.js",
    "Sales Person": "public/js/sales_person.js",
    "Employee": "public/js/employee.js",
    "Item Price": "public/js/item_price.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "supremusangel/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "supremusangel.utils.jinja_methods",
# 	"filters": "supremusangel.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "supremusangel.install.before_install"
# after_install = "supremusangel.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "supremusangel.uninstall.before_uninstall"
# after_uninstall = "supremusangel.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "supremusangel.utils.before_app_install"
# after_app_install = "supremusangel.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "supremusangel.utils.before_app_uninstall"
# after_app_uninstall = "supremusangel.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "supremusangel.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"supremusangel.tasks.all"
# 	],
# 	"daily": [
# 		"supremusangel.tasks.daily"
# 	],
# 	"hourly": [
# 		"supremusangel.tasks.hourly"
# 	],
# 	"weekly": [
# 		"supremusangel.tasks.weekly"
# 	],
# 	"monthly": [
# 		"supremusangel.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "supremusangel.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "supremusangel.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "supremusangel.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["supremusangel.utils.before_request"]
# after_request = ["supremusangel.utils.after_request"]

# Job Events
# ----------
# before_job = ["supremusangel.utils.before_job"]
# after_job = ["supremusangel.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"supremusangel.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
override_doctype_class = {
    "Interview": "supremusangel.supremus_angel.custom.interview.CustomInterview",
    "Item Price": "supremusangel.unlisted_shares.direct_ladder.AgentItemPrice",
}

# RM EOD scorecards are readable by every Employee so a reporting manager needs
# no special role; these keep each user's rows limited to their own reporting
# tree (HR and System Manager see everything). See rm_performance/scoping.py.
permission_query_conditions = {
    "RM Daily Scorecard": "supremusangel.rm_performance.scoping.scorecard_query_conditions",
    "RM Monthly Rating": "supremusangel.rm_performance.scoping.rating_query_conditions",
}

has_permission = {
    "RM Daily Scorecard": "supremusangel.rm_performance.scoping.scorecard_has_permission",
}

# Incentive sales are read live from core Sales Invoice + Sales Team at
# calculate() time (see supremus_angel/incentive_source.py), so no doc_events
# are needed to mirror invoices into a custom sales doctype. Submitting or
# cancelling an invoice does trigger a live incentive recompute for the credited
# people (see supremus_angel/incentive_realtime.py) so the ESS commission figures
# stay current without waiting for the month-end scheduler job.

fixtures = [
    {"dt": "Property Setter", "filters": [["doc_type", "=", "Interview"]]},
    # Link back from a Sales Person to the Customer it was created from
    # (Create Sales Person button on the Customer form).
    {"dt": "Custom Field", "filters": [["name", "in", [
        "Sales Person-custom_customer",
        "Sales Person-custom_incentive_role",
    ]]]},
    # Dedicated incentive-scheme roles that drive the ESS commission dashboard
    # view (consumed by ess/commission_api.py). Shipped so every site has them.
    {"dt": "Role", "filters": [["name", "in", [
        "Incentive Salesperson",
        "Incentive Team Lead",
        "Incentive Branch Manager",
    ]]]},
    # Investor-portal notifications (KYC verified/rejected, Purchase Note,
    # Payment Received, Shares Transferred, Invoice Generated). Email + bell.
    {"dt": "Notification", "filters": [["name", "in", [
        "SA KYC Verified",
        "SA KYC Rejected",
        "SA Purchase Note",
        "SA Payment Received",
        "SA Shares Transferred",
        "SA Invoice Generated",
    ]]]},
]

# Investor-portal notifications that can't be expressed as plain Notifications.
# See supremus_angel/portal_notifications.py.
doc_events = {
    # Mirror the newest contact-log row back onto the legacy Lead call fields so
    # the telecalling desk and its reports keep working.
    "Lead": {
        "validate": "supremusangel.rm_performance.lead_hooks.sync_contact_log",
    },
    "User": {
        "after_insert": "supremusangel.supremus_angel.portal_notifications.send_customer_welcome_email",
    },
    "Payment Entry": {
        "on_cancel": "supremusangel.supremus_angel.portal_notifications.notify_payment_failed",
    },
    "Sales Invoice": {
        "on_submit": "supremusangel.supremus_angel.incentive_realtime.on_invoice_submit",
        "on_cancel": [
            "supremusangel.supremus_angel.portal_notifications.notify_share_transfer_failed",
            "supremusangel.supremus_angel.incentive_realtime.on_invoice_cancel",
        ],
    },
}

scheduler_events = {
    "daily": [
        "supremusangel.supremus_angel.portal_notifications.send_mip_due_reminders",
        # Snapshot yesterday's RM EOD scorecard once the day has closed.
        "supremusangel.rm_performance.kpi_engine.build_yesterday",
    ],
    # 1st of every month: auto-calculate the previous month's incentives for
    # every eligible Sales Person (scheme chosen by their incentive role).
    "monthly": [
        "supremusangel.supremus_angel.incentive_tasks.run_monthly_incentives",
    ],
    "cron": {
        # Mon-Sat 10:00: Telegram onboarding checklist reminders + HR summary.
        "0 10 * * 1-6": [
            "supremusangel.telegram_bots.hr_checklist.daily_reminders",
        ],
    },
}

on_login = "supremusangel.supremus_angel.portal_notifications.send_kyc_reminder_on_login"

boot_session = "supremusangel.supremus_angel.boot.boot_session"

# Version-controlled share-sale commissions. Preserve existing app integrations.
after_install = "supremusangel.unlisted_shares.install.setup"
after_migrate = "supremusangel.unlisted_shares.install.setup"
doc_events["Payment Entry"]["validate"] = "supremusangel.unlisted_shares.payments.validate"
doc_events["Sales Invoice"].update({
    "before_validate": "supremusangel.unlisted_shares.commission_engine.prepare",
    "validate": ["supremusangel.unlisted_shares.direct_sales.validate_invoice", "supremusangel.unlisted_shares.commission_engine.calculate", "supremusangel.unlisted_shares.install.mark_pending"],
    "before_submit": ["supremusangel.unlisted_shares.direct_sales.validate_invoice", "supremusangel.unlisted_shares.commission_engine.calculate"],
    "before_update_after_submit": "supremusangel.unlisted_shares.commission_engine.protect_submitted",
    "on_submit": ["supremusangel.unlisted_shares.commission_engine.on_submit", "supremusangel.unlisted_shares.direct_sales.on_submit_invoice", "supremusangel.supremus_angel.incentive_realtime.on_invoice_submit"],
})
doc_events["Sales Invoice"]["on_cancel"].append("supremusangel.unlisted_shares.direct_sales.on_cancel_invoice")
doc_events["Item Price"] = {"validate": "supremusangel.unlisted_shares.direct_ladder.validate_item_price",
                            "on_update": "supremusangel.unlisted_shares.direct_ladder.on_update_item_price"}
for _dt, _function in {"Sales Invoice": "invoice", "Customer": "customer", "Sales Person": "person",
                       "Payment Entry": "payment", "Withdrawal Request": "withdrawal",
                       "Direct Sales Mandate": "direct_sales_mandate",
                       "Direct Sales Rate Revision": "direct_sales_rate_revision",
                       "Item Price": "item_price"}.items():
    permission_query_conditions[_dt] = f"supremusangel.unlisted_shares.permissions.{_function}_query"
    has_permission[_dt] = "supremusangel.unlisted_shares.permissions.has_permission"

_share_fields = ["Sales Person-custom_use_tier_commission", "Sales Invoice-custom_commission_scheme",
                 "Sales Person-custom_tier", "Sales Person-custom_agent_user", "Item-custom_logo",
                 "Customer-custom_sales_person", "Sales Invoice-custom_unlisted_shares", "Sales Invoice-custom_primary_agent", "Sales Invoice-custom_direct_sales", "Item Price-custom_agent", "Sales Invoice-custom_direct_sales_partner", "Sales Invoice-custom_direct_sales_rate",
                 "Sales Invoice-custom_pending_since", "Sales Invoice-custom_direct_sales_mandate",
                 "Sales Invoice-custom_direct_sales_rate_revision", "Sales Invoice-custom_company_settlement_rate",
                 "Sales Invoice-custom_direct_sales_partner_earning", "Sales Invoice-workflow_state", "Sales Team-custom_commission_tier",
                 "Payment Entry-custom_sales_person", "Payment Entry-custom_withdrawal_request", "Withdrawal Request-workflow_state"]
for _fixture in fixtures:
    if _fixture["dt"] == "Custom Field":
        _fixture["filters"][0][2].extend(_share_fields)
    if _fixture["dt"] == "Role":
        _fixture["filters"][0][2].extend(["Agent", "Admin"])
fixtures.extend([
    {"dt": "Item Group", "filters": [["name", "=", "Unlisted Shares"]]},
    {"dt": "Commission Tier", "filters": [["name", "in", ["Associate", "Sr. Associate", "Team Lead", "City Partner"]]]},
    {"dt": "Workflow", "filters": [["name", "in", ["SA Share Purchase Approval", "SA Withdrawal Approval"]]]},
    {"dt": "Workflow State", "filters": [["name", "in", ["Draft", "Pending Approval", "Approved", "Rejected", "Cancelled"]]]},
    {"dt": "Workflow Action Master", "filters": [["name", "in", ["Request Approval", "Approve", "Reject", "Revise", "Cancel", "Submit"]]]},
    {"dt": "Number Card", "filters": [["name", "in", ["SA Total Transactions", "SA Total Customers", "SA Active Deals", "SA Pending Payment Requests"]]]},
    {"dt": "Dashboard Chart", "filters": [["name", "=", "SA Weekly Transaction Value"]]},
])
