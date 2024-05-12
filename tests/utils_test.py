from unittest.mock import MagicMock
from schwab.utils import AccountHashMismatchException, Utils
from schwab.utils import UnsuccessfulOrderException
from schwab.utils import EnumEnforcer
from .utils import no_duplicates, MockResponse

import enum
import unittest


class EnumEnforcerTest(unittest.TestCase):

    class TestClass(EnumEnforcer):
        def test_enforcement(self, value):
            self.convert_enum(value, EnumEnforcerTest.TestEnum)


    class TestEnum(enum.Enum):
        VALUE_1 = 1
        VALUE_2 = 2


    def test_valid_enum(self):
        t = self.TestClass(enforce_enums=True)
        t.test_enforcement(self.TestEnum.VALUE_1)

    def test_invalid_enum_passed_as_string(self):
        t = self.TestClass(enforce_enums=True)
        with self.assertRaisesRegex(
                ValueError, 'tests.utils_test.TestEnum.VALUE_1'):
            t.test_enforcement('VALUE_1')

    def test_invalid_enum_passed_as_not_string(self):
        t = self.TestClass(enforce_enums=True)
        with self.assertRaises(ValueError):
            t.test_enforcement(123)


class UtilsTest(unittest.TestCase):

    def setUp(self):
        self.mock_client = MagicMock()
        self.account_hash = '0xacc0unth45h'
        self.utils = Utils(self.mock_client, self.account_hash)

        self.order_id = 1

        self.maxDiff = None

    ##########################################################################
    # extract_order_id tests

    @no_duplicates
    def test_extract_order_id_order_not_ok(self):
        response = MockResponse({}, 403)
        with self.assertRaises(
                UnsuccessfulOrderException, msg='order not successful'):
            self.utils.extract_order_id(response)

    @no_duplicates
    def test_extract_order_id_no_location(self):
        response = MockResponse({}, 200, headers={})
        self.assertIsNone(self.utils.extract_order_id(response))

    @no_duplicates
    def test_extract_order_id_no_pattern_match(self):
        response = MockResponse({}, 200, headers={
            'Location': 'not-a-match'})
        self.assertIsNone(self.utils.extract_order_id(response))

    @no_duplicates
    def test_get_order_nonmatching_account_hash(self):
        response = MockResponse({}, 200, headers={
            'Location':
            'https://api.schwabapi.com/trader/v1/accounts/badhash/orders/123'})
        with self.assertRaisesRegex(
                AccountHashMismatchException,
                'order request account hash != Utils.account_hash') as cm:
            self.utils.extract_order_id(response)

    @no_duplicates
    def test_get_order_success_200(self):
        order_id = 123456
        response = MockResponse({}, 200, headers={
            'Location':
            'https://api.schwabapi.com/trader/v1/accounts/{}/orders/{}'.format(
                self.account_hash, order_id)})
        self.assertEqual(order_id, self.utils.extract_order_id(response))

    @no_duplicates
    def test_get_order_success_201(self):
        order_id = 123456
        response = MockResponse({}, 201, headers={
            'Location':
            'https://api.schwabapi.com/trader/v1/accounts/{}/orders/{}'.format(
                self.account_hash, order_id)})
        self.assertEqual(order_id, self.utils.extract_order_id(response))
