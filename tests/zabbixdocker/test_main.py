from unittest import mock, TestCase

from zabbixdocker.main import Application


class TestApplication(TestCase):
    def test_singleton(self):
        app1 = Application()
        app2 = Application()

        assert app1 == app2
