"""Direct Sales price ladder on Item Price (deal price + partner access + agent prices), using
the worked example from the business:

Company settlement 30 -> City Partner charges 32 -> Team Lead 35 -> Sr. Associate 38
-> Associate sells to the customer at 45. Margins 2 / 3 / 3 / 7; company keeps 30.
Everything is rolled back after the class. Run with --skip-before-tests (see README).
"""
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from supremusangel.unlisted_shares import direct_ladder as ladder

DEAL = "_TESTLADDER01"
LIST = ladder.DIRECT_SALES_LIST


def agent(name, tier, parent=None):
    return frappe.get_doc({"doctype": "Sales Person", "sales_person_name": name, "custom_tier": tier,
                           "parent_sales_person": parent or "Sales Team", "is_group": 1, "enabled": 1}).insert().name


def deal_price(company=30, low=30, high=45, valid_from=None):
    return frappe.get_doc({"doctype": "Item Price", "price_list": LIST, "item_code": DEAL, "price_list_rate": company,
                           "custom_minimum_selling_rate": low, "custom_maximum_selling_rate": high,
                           "valid_from": valid_from or today()}).insert()


def access(partner, reserved=100):
    return frappe.get_doc({"doctype": "Item Price", "price_list": LIST, "item_code": DEAL, "custom_sales_partner": partner,
                           "custom_reserved_qty": reserved, "price_list_rate": 0}).insert()


class TestDirectLadder(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = frappe.defaults.get_global_default("company")
        frappe.get_doc({"doctype": "Item", "item_code": DEAL, "item_name": DEAL, "item_group": "Unlisted Shares",
                        "stock_uom": "Nos", "is_stock_item": 0}).insert()
        cls.cp = agent("_TL City Partner", "City Partner")
        cls.tl = agent("_TL Team Lead", "Team Lead", cls.cp)
        cls.sra = agent("_TL Sr Associate", "Sr. Associate", cls.tl)
        cls.assoc = agent("_TL Associate", "Associate", cls.sra)
        cls.price_name = deal_price().name
        cls.access_name = access(cls.cp).name
        for who, price in ((cls.cp, 32), (cls.tl, 35), (cls.sra, 38)):
            cls.price(who, price)

    @classmethod
    def price(cls, who, rate):
        return frappe.get_doc({"doctype": "Item Price", "price_list": LIST, "item_code": DEAL,
                               "custom_agent": who, "price_list_rate": rate}).insert()

    @property
    def rate(self):
        return ladder.rate_for_partner(DEAL, self.cp)

    def margins(self, seller, qty, sale_rate, rate=None):
        return {r["sales_person"]: r["amount"] for r in ladder.split(seller, rate or self.rate, qty, sale_rate)}

    def invoice(self, seller, qty=2, rate=45, direct=1):
        branch = frappe.db.get_value("Branch", {}, "name")
        customer = frappe.db.get_value("Customer", {}, "name")
        si = frappe.get_doc({"doctype": "Sales Invoice", "company": self.company, "customer": customer,
                             "branch": branch, "custom_primary_agent": seller, "custom_is_direct": direct,
                             "items": [{"item_code": DEAL, "qty": qty, "rate": rate, "branch": branch}]})
        si.set_missing_values()
        si.items[0].rate = rate
        return si

    def test_full_chain(self):
        self.assertEqual(self.margins(self.assoc, 1, 45), {self.assoc: 7, self.sra: 3, self.tl: 3, self.cp: 2})

    def test_qty_multiplies(self):
        self.assertEqual(self.margins(self.assoc, 10, 45)[self.assoc], 70)

    def test_seller_higher_up_keeps_the_gap(self):
        self.assertEqual(self.margins(self.tl, 1, 45), {self.tl: 13, self.cp: 2})
        self.assertEqual(self.margins(self.cp, 1, 45), {self.cp: 15})

    def test_sale_below_own_buy_price_is_blocked(self):
        with self.assertRaises(frappe.ValidationError):
            ladder.split(self.sra, self.rate, 1, 34)

    def test_seller_outside_partner_downline_is_blocked(self):
        outsider = agent("_TL Outsider", "Associate")
        self.assertIsNone(ladder.get_rate(DEAL, outsider))
        with self.assertRaises(frappe.ValidationError):
            ladder.split(outsider, self.rate, 1, 45)

    def test_upline_without_price_passes_at_cost(self):
        tl = agent("_TL TL No Price", "Team Lead", self.cp)
        assoc = agent("_TL Assoc Direct", "Associate", tl)
        self.assertEqual(self.margins(assoc, 1, 40), {assoc: 8, tl: 0, self.cp: 2})

    def test_agent_price_bounds(self):
        with self.assertRaises(frappe.ValidationError):
            self.price(agent("_TL TL Low", "Team Lead", self.cp), 31)  # below own buy of 32
        with self.assertRaises(frappe.ValidationError):
            self.price(agent("_TL TL High", "Team Lead", self.cp), 50)  # above max 45

    def test_one_price_per_agent(self):
        with self.assertRaises(frappe.ValidationError):
            self.price(self.cp, 33)

    def test_deal_price_and_access_rules(self):
        with self.assertRaises(frappe.ValidationError):
            deal_price(company=40, low=30, valid_from=add_days(today(), 1))  # company price above min
        with self.assertRaises(frappe.ValidationError):
            deal_price()  # a second deal price on the same date
        with self.assertRaises(frappe.ValidationError):
            access(self.cp)  # the same partner's access twice
        with self.assertRaises(frappe.ValidationError):
            access(agent("_TL CP No Qty", "City Partner"), reserved=0)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Item Price", "price_list": LIST, "item_code": DEAL, "custom_agent": self.tl,
                            "custom_sales_partner": self.cp, "price_list_rate": 35}).insert()  # both kinds at once

    def test_one_deal_price_serves_every_partner(self):
        other_cp = agent("_TL CP Two", "City Partner")
        access(other_cp)
        rate = ladder.get_rate(DEAL, other_cp)
        self.assertEqual((rate.custom_sales_partner, rate.company_price, rate.price_row), (other_cp, 30, self.price_name))

    def test_later_deal_price_is_a_price_change(self):
        deal_price(company=31, low=31, valid_from=add_days(today(), 10))
        self.assertEqual(ladder.rate_for_partner(DEAL, self.cp).company_price, 30)  # not yet
        future = ladder.rate_for_partner(DEAL, self.cp, add_days(today(), 10))
        self.assertEqual(future.company_price, 31)
        self.assertEqual(self.margins(self.assoc, 1, 45, future)[self.cp], 1)  # 32 - 31

    def test_rate_rise_flags_and_blocks_stale_upline_price(self):
        rate = frappe._dict(self.rate, company_price=33, custom_minimum_selling_rate=33)
        price = frappe._dict(name="new", item_code=DEAL, price_list_rate=33, custom_minimum_selling_rate=33,
                             custom_maximum_selling_rate=45)
        self.assertEqual([row[0] for row in ladder.stale_agent_prices(DEAL, price)], [self.cp])
        with self.assertRaises(frappe.ValidationError):
            ladder.split(self.assoc, rate, 1, 45)
        self.assertEqual(self.margins(self.cp, 1, 45, rate), {self.cp: 12})  # partner selling direct is fine

    def test_invoice_writes_sales_team_ledger(self):
        si = self.invoice(self.assoc)
        si.insert()
        self.assertEqual(si.custom_commission_scheme, "Direct Sales")
        self.assertEqual((si.custom_direct_sales_partner, si.custom_direct_sales_rate), (self.cp, self.price_name))
        self.assertEqual(si.custom_company_settlement_rate, 30)
        self.assertEqual({r.sales_person: r.incentives for r in si.sales_team},
                         {self.assoc: 14, self.sra: 6, self.tl: 6, self.cp: 4})
        self.assertEqual(si.custom_direct_sales_partner_earning, 30)

    def test_customer_rate_must_be_in_range(self):
        with self.assertRaises(frappe.ValidationError):
            self.invoice(self.assoc, rate=46).insert()

    def test_quota_blocks_overselling(self):
        with self.assertRaises(frappe.ValidationError):
            self.invoice(self.assoc, qty=101).insert()

    def test_sold_quantity_sync(self):
        before = ladder.sold_quantity(DEAL, self.cp)  # other tests in this class may have sold some
        frappe.db.set_value("Sales Invoice", self.invoice(self.assoc, qty=3).insert().name, "docstatus", 1)
        ladder.sync_sold_quantity(DEAL, self.cp)
        self.assertEqual(frappe.db.get_value("Item Price", self.access_name, ["custom_sold_qty", "custom_remaining_qty"]),
                         (before + 3, 100 - before - 3))

    def test_unticked_invoice_uses_tier_commission(self):
        si = self.invoice(self.cp, qty=1, direct=0)
        si.insert()
        self.assertNotEqual(si.custom_commission_scheme, "Direct Sales")
        self.assertFalse(si.custom_direct_sales_rate)

    def test_get_downline_prices_for_admin_preview(self):
        data = ladder.get_downline_prices(self.tl)
        row = next(d for d in data["deals"] if d["deal"] == DEAL)
        self.assertTrue(data["has_downline"])
        self.assertEqual((row["sales_partner"], row["buy_price"], row["downline_price"]), (self.cp, 32, 35))

    def test_agent_can_only_manage_own_prices(self):
        user = frappe.get_doc({"doctype": "User", "email": "_tl.agent@example.test", "first_name": "TL Agent",
                               "send_welcome_email": 0, "roles": [{"role": "Agent"}]}).insert()
        frappe.db.set_value("Sales Person", self.sra, "custom_agent_user", user.name)
        frappe.set_user(user.name)
        try:
            self.assertEqual(ladder.set_downline_price(DEAL, 39)["price"], 39)
            with self.assertRaises(frappe.PermissionError):
                ladder.set_downline_price(DEAL, 36, sales_person=self.tl)
        finally:
            frappe.set_user("Administrator")
        self.assertEqual(self.margins(self.assoc, 1, 45)[self.sra], 4)
        ladder.set_downline_price(DEAL, 38, sales_person=self.sra)
        frappe.db.set_value("Sales Person", self.sra, "custom_agent_user", None)

    def test_agent_item_price_access_is_scoped_to_own_rows(self):
        user = frappe.get_doc({"doctype": "User", "email": "_tl.ip.agent@example.test", "first_name": "IP Agent",
                               "send_welcome_email": 0, "roles": [{"role": "Agent"}]}).insert()
        frappe.db.set_value("Sales Person", self.tl, "custom_agent_user", user.name)
        own = frappe.db.get_value("Item Price", {"custom_agent": self.tl, "item_code": DEAL})
        other = frappe.db.get_value("Item Price", {"custom_agent": self.cp, "item_code": DEAL})
        frappe.set_user(user.name)
        try:
            # Own row plus the downline's rows, read-only; never the upline's.
            visible = frappe.get_list("Item Price", filters={"item_code": DEAL}, pluck="name")
            downline = frappe.get_all("Item Price", filters={"item_code": DEAL, "custom_agent": ["in", [self.sra, self.assoc]]},
                                      pluck="name")
            self.assertCountEqual(visible, [own] + downline)
            self.assertNotIn(other, visible)
            for name in downline:
                self.assertTrue(frappe.has_permission("Item Price", "read", doc=frappe.get_doc("Item Price", name)))
                self.assertFalse(frappe.has_permission("Item Price", "write", doc=frappe.get_doc("Item Price", name)))
            self.assertFalse(frappe.has_permission("Item Price", "write", doc=frappe.get_doc("Item Price", other)))
            self.assertFalse(frappe.has_permission("Item Price", "write", doc=frappe.get_doc("Item Price", self.price_name)))
            self.assertFalse(frappe.has_permission("Item Price", "write", doc=frappe.get_doc("Item Price", self.access_name)))
            doc = frappe.get_doc("Item Price", own)
            doc.price_list_rate = 36
            doc.save()  # standard permission path, no ignore_permissions
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc({"doctype": "Item Price", "price_list": LIST, "item_code": DEAL,
                                "custom_sales_partner": self.tl, "custom_reserved_qty": 1,
                                "price_list_rate": 0}).insert()  # own partner access
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc({"doctype": "Item Price", "price_list": LIST, "item_code": DEAL, "price_list_rate": 1,
                                "custom_minimum_selling_rate": 1, "custom_maximum_selling_rate": 99,
                                "valid_from": add_days(today(), 3)}).insert()  # a deal price
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc({"doctype": "Item Price", "price_list": LIST, "item_code": DEAL,
                                "custom_agent": self.sra, "price_list_rate": 40}).insert()  # someone else's
        finally:
            frappe.set_user("Administrator")
        ladder.set_downline_price(DEAL, 35, sales_person=self.tl)
        frappe.db.set_value("Sales Person", self.tl, "custom_agent_user", None)

    def test_retired_doctypes_refuse_new_records(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Direct Sales Mandate", "sales_partner": self.cp, "deal": DEAL,
                            "company": self.company, "mandate_date": today(), "reserved_quantity": 1}).insert()

    def test_direct_sales_commission_report(self):
        from supremusangel.unlisted_shares.reports import run_report
        si = self.invoice(self.assoc, qty=3).insert()
        frappe.db.set_value("Sales Invoice", si.name, "docstatus", 1)
        frappe.db.sql("update `tabSales Team` set docstatus=1 where parent=%s", si.name)
        f = {"from_date": add_days(today(), -1), "to_date": today(), "deal": DEAL}
        rows = {r.sales_person: r for r in run_report("direct_commission", f)[1]}
        self.assertEqual((rows[self.assoc].own_qty, rows[self.assoc].own_margin, rows[self.assoc].downline_margin), (3, 21, 0))
        self.assertEqual((rows[self.cp].own_margin, rows[self.cp].downline_margin, rows[self.cp].total), (0, 6, 6))
        user = frappe.get_doc({"doctype": "User", "email": "_tl.rep.agent@example.test", "first_name": "Rep Agent",
                               "send_welcome_email": 0, "roles": [{"role": "Agent"}]}).insert()
        frappe.db.set_value("Sales Person", self.sra, "custom_agent_user", user.name)
        frappe.set_user(user.name)
        try:
            own = run_report("direct_commission", f)[1]
            self.assertEqual([r.sales_person for r in own], [self.sra])
            with self.assertRaises(frappe.PermissionError):
                run_report("direct_commission", dict(f, sales_person=self.cp))
        finally:
            frappe.set_user("Administrator")
            frappe.db.set_value("Sales Person", self.sra, "custom_agent_user", None)
