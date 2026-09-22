"""Scheme routing checks without saving or recalculating financial documents."""
import unittest
from unittest.mock import patch

import frappe

from supremusangel.unlisted_shares import commission_engine as engine
from supremusangel.unlisted_shares import schemes
from supremusangel.supremus_angel import incentive_realtime


class TestCommissionSchemeOptIn(unittest.TestCase):
    def invoice(self):
        return frappe.get_doc({
            'doctype': 'Sales Invoice', 'customer': 'Test Customer',
            'custom_primary_agent': 'Seller', 'items': [{'item_code': 'Test Share'}],
            'sales_team': [{'sales_person': 'Seller', 'allocated_percentage': 100}],
        })

    def prepare(self, doc, opted_in, mandate=None):
        with patch.object(engine, 'is_share_invoice', return_value=True), \
             patch.object(engine.frappe.db, 'get_value', return_value=engine.GROUP), \
             patch.object(engine, 'uses_tier_commission', return_value=opted_in), \
             patch('supremusangel.unlisted_shares.permissions.agent_only', return_value=False), \
             patch('supremusangel.unlisted_shares.permissions.is_admin', return_value=True):
            engine.prepare(doc)

    def test_unchecked_seller_keeps_monthly_scheme(self):
        doc = self.invoice()
        self.prepare(doc, False)
        self.assertEqual(doc.custom_commission_scheme, schemes.MONTHLY)
        with patch.object(engine, 'build_chain') as build:
            engine.calculate(doc)
            build.assert_not_called()

    def test_checked_seller_gets_tier_scheme(self):
        doc = self.invoice()
        self.prepare(doc, True)
        self.assertEqual(doc.custom_commission_scheme, schemes.TIER)
        self.assertFalse(schemes.is_monthly_invoice(doc))

    def test_direct_sales_checkbox_selects_direct_scheme(self):
        doc = self.invoice()
        doc.custom_direct_sales = 1
        self.prepare(doc, True)
        self.assertEqual(doc.custom_commission_scheme, schemes.DIRECT)

    def test_unticked_direct_sales_drops_stale_mandate(self):
        doc = self.invoice()
        doc.custom_direct_sales_rate = 'old-rate-row'
        doc.custom_direct_sales_partner_earning = 500
        self.prepare(doc, True)
        self.assertEqual(doc.custom_commission_scheme, schemes.TIER)
        self.assertIsNone(doc.custom_direct_sales_rate)
        self.assertFalse(doc.custom_direct_sales_partner_earning)

    def test_draft_switch_to_monthly_clears_tier_rows(self):
        doc = self.invoice()
        doc.custom_commission_scheme = schemes.TIER
        doc.append('sales_team', {'sales_person': 'Manager', 'allocated_percentage': 0, 'incentives': 200})
        self.prepare(doc, False)
        self.assertEqual([row.sales_person for row in doc.sales_team], ['Seller'])
        self.assertFalse(doc.sales_team[0].incentives)

    def test_historical_invoice_classification_is_preserved(self):
        self.assertFalse(schemes.is_monthly_invoice(frappe._dict(custom_unlisted_shares=1)))
        self.assertTrue(schemes.is_monthly_invoice(frappe._dict(custom_unlisted_shares=0)))
        self.assertTrue(schemes.is_monthly_invoice(frappe._dict(
            custom_unlisted_shares=1, custom_commission_scheme=schemes.MONTHLY)))

    def test_checked_agent_is_not_recalculated(self):
        with patch.object(incentive_realtime, 'uses_tier_commission', return_value=True), \
             patch.object(incentive_realtime.frappe, 'get_doc') as get_doc:
            self.assertFalse(incentive_realtime._upsert_calc('SA', 'Seller', '2026-09'))
            get_doc.assert_not_called()

    def test_realtime_work_excludes_checked_sellers_and_managers(self):
        with patch.object(incentive_realtime, 'uses_tier_commission', side_effect=lambda name: name == 'New'), \
             patch.object(incentive_realtime, '_ancestors', return_value=['New']), \
             patch.object(incentive_realtime, '_scheme_of', return_value='SA'):
            self.assertEqual(incentive_realtime._build_work_list(['Existing', 'New'], '2026-09'), [('SA', 'Existing')])

    def test_tier_invoice_does_not_enqueue_monthly_recalculation(self):
        with patch.object(incentive_realtime.frappe, 'enqueue') as enqueue:
            incentive_realtime._enqueue_recalc(frappe._dict(custom_commission_scheme=schemes.TIER))
            enqueue.assert_not_called()

    def test_direct_rate_is_only_for_the_seller(self):
        names = ['Associate', 'Sr. Associate', 'Team Lead', 'City Partner']
        tiers = {name: frappe.get_doc('Commission Tier', name) for name in names}
        agents = {name: frappe._dict(name=name, enabled=1, custom_tier=name,
                  parent_sales_person=names[i+1] if i < 3 else None) for i, name in enumerate(names)}
        with patch.object(engine, 'uses_tier_commission', return_value=True), \
             patch.object(engine.frappe.db, 'get_value', side_effect=lambda dt, name, *a, **k: agents[name]), \
             patch.object(engine.frappe, 'get_doc', side_effect=lambda dt, name: tiers[name]):
            for seller, expected in zip(names, [[20, 5, 3, 2], [25, 3, 2], [28, 2], [30]]):
                self.assertEqual([row[1] for row in engine.build_chain(seller)], expected)

    def test_unchecked_ancestor_cannot_receive_tier_commission(self):
        with patch.object(engine, 'uses_tier_commission', return_value=False), \
             patch.object(engine.frappe.db, 'get_value', return_value=frappe._dict(enabled=1)), \
             patch.object(engine, 'fail', side_effect=ValueError) as fail:
            with self.assertRaises(ValueError):
                engine.build_chain('Unchecked')
            self.assertIn('Use Tier Commission', fail.call_args.args[0])
