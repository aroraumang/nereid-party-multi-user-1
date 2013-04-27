# -*- coding: utf-8 -*-
"""
    test_user

    Test the multi user implementation

    :copyright: (c) 2013 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
import unittest

from mock import patch
import trytond.tests.test_tryton
from trytond.tests.test_tryton import test_view, test_depends, POOL, USER, \
    DB_NAME, CONTEXT
from trytond.config import CONFIG
from trytond.transaction import Transaction
from nereid.testing import NereidTestCase


CONFIG['smtp_server'] = 'smtpserver'
CONFIG['smtp_user'] = 'test@xyz.com'
CONFIG['smtp_password'] = 'testpassword'
CONFIG['smtp_port'] = 587
CONFIG['smtp_tls'] = True
CONFIG['smtp_from'] = 'from@xyz.com'


class TestNereidMultiUserCase(NereidTestCase):

    def setUp(self):
        trytond.tests.test_tryton.install_module('nereid_party_multi_user')

        # Patch SMTP Lib
        self.smtplib_patcher = patch('smtplib.SMTP')
        self.PatchedSMTP = self.smtplib_patcher.start()

    def tearDown(self):
        # Unpatch SMTP Lib
        self.smtplib_patcher.stop()

    def test0005views(self):
        """
        Test Views.
        """
        test_view('nereid_party_multi_user')

    def test0006depends(self):
        """
        Test depends.
        """
        test_depends()

    def setup_defaults(self):
        """
        Setup the defaults
        """
        Currency = POOL.get('currency.currency')
        Company = POOL.get('company.company')
        NereidUser = POOL.get('nereid.user')
        UrlMap = POOL.get('nereid.url_map')
        Language = POOL.get('ir.lang')
        NereidWebsite = POOL.get('nereid.website')

        usd = Currency.create({
            'name': 'US Dollar',
            'code': 'USD',
            'symbol': '$',
        })
        company = Company.create({
            'name': 'Openlabs',
            'currency': usd.id,
        })
        guest_user = NereidUser.create({
            'name': 'Guest User',
            'display_name': 'Guest User',
            'email': 'guest@openlabs.co.in',
            'password': 'password',
            'company': company.id,
        })
        url_map, = UrlMap.search([], limit=1)
        en_us, = Language.search([('code', '=', 'en_US')])
        NereidWebsite.create({
            'name': 'localhost',
            'url_map': url_map.id,
            'company': company.id,
            'application_user': USER,
            'default_language': en_us,
            'guest_user': guest_user,
        })

    def get_template_source(self, name):
        """
        Return templates
        """
        templates = {
            'localhost/registration.jinja': 'registration',
            'localhost/emails/activation-text.jinja': 'activation-email-text',
            'localhost/emails/activation-html.jinja': 'activation-email-html',
        }
        return templates.get(name)

    def test0010registration(self):
        """
        Test the registration workflow
        """
        NereidUser = POOL.get('nereid.user')

        with Transaction().start(DB_NAME, USER, CONTEXT) as txn:
            self.setup_defaults()
            app = self.get_app()

            with app.test_client() as c:
                response = c.get('/en_US/registration')
                self.assertEqual(response.status_code, 200)

            data = {
                'name': 'New Test Registered User',
                'email': 'new.test@example.com',
                'password': 'password'
            }
            with app.test_client() as c:
                # Record should not be created because there is no confirm
                # password
                response = c.post('/en_US/registration', data=data)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    NereidUser.search([
                        ('email', '=', 'new.test@example.com')
                    ], count=True), 0
                )
            with app.test_client() as c:
                # It should be successfully created since all data is correct
                data['confirm'] = 'password'
                response = c.post('/en_US/registration', data=data)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(
                    NereidUser.search([
                        ('email', '=', 'new.test@example.com')
                    ], count=True), 1
                )
            txn.cursor.rollback()

    def test0020_switch_company(self):
        """
        Test switching between companies of the user
        """
        Company = POOL.get('company.company')
        NereidUser = POOL.get('nereid.user')
        Party = POOL.get('party.party')

        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()
            app = self.get_app()

            company, = Company.search([])
            regd_user = NereidUser.create({
                'name': 'Registered User',
                'display_name': 'Registered User',
                'email': 'regd-user@openlabs.co.in',
                'password': 'password',
                'company': company.id,
            })
            self.assertEqual(len(regd_user.parties), 1)
            parent_co = regd_user.party

            # Add a part time company
            part_time_co = Party.create({'name': 'Part time co LLC'})
            NereidUser.write(
                [regd_user],
                {'parties': [('add', [part_time_co.id])]}
            )
            self.assertEqual(len(regd_user.parties), 2)

            with app.test_client() as c:
                # Login
                resp = c.post(
                    '/en_US/login', data={
                        'email': 'regd-user@openlabs.co.in',
                        'password': 'password',
                    }
                )

                # Switch to the new company
                resp = c.get('/en_US/change-current-party/%d' % part_time_co)
                self.assertEqual(resp.status_code, 302)

                # Rebrowse the record and check if the new party is set
                self.assertEqual(regd_user.party, part_time_co)

                # Switch to the previous company
                resp = c.get('/en_US/change-current-party/%d' % parent_co)
                self.assertEqual(resp.status_code, 302)

                # Rebrowse the record and check if the new party is set
                self.assertEqual(regd_user.party, parent_co)

    def test0030_check_reverse_relationship(self):
        """
        Check the reverse relationship between party and the user
        """
        Company = POOL.get('company.company')
        NereidUser = POOL.get('nereid.user')

        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()

            company, = Company.search([])
            regd_user = NereidUser.create({
                'name': 'Registered User',
                'display_name': 'Registered User',
                'email': 'regd-user@openlabs.co.in',
                'password': 'password',
                'company': company.id,
            })
            self.assertEqual(len(regd_user.parties), 1)
            self.assertEqual(len(regd_user.party.nereid_users), 1)


def suite():
    test_suite = trytond.tests.test_tryton.suite()
    test_suite.addTests(
        unittest.TestLoader().loadTestsFromTestCase(TestNereidMultiUserCase)
    )
    return test_suite


if __name__ == '__main__':
    unittest.TextTestRunner(verbosity=2).run(suite())
