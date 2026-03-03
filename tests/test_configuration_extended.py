"""
Tests for the Configuration class — defaults, aliases, domain parsing, and properties.
"""

import pytest
from keboola.component.exceptions import UserException

from configuration import Configuration

BASE_URL = "https://demo.odoo.com"


@pytest.fixture
def base_config():
    return Configuration(odoo_url=BASE_URL, database="demo")


class TestUrlValidation:
    def test_valid_https_url_accepted(self):
        config = Configuration(odoo_url="https://demo.odoo.com", database="demo")
        assert config.odoo_url == "https://demo.odoo.com"

    def test_valid_http_url_accepted(self):
        config = Configuration(odoo_url="http://localhost:8069", database="demo")
        assert config.odoo_url == "http://localhost:8069"

    def test_trailing_slash_stripped(self):
        config = Configuration(odoo_url="https://demo.odoo.com/", database="demo")
        assert config.odoo_url == "https://demo.odoo.com"

    def test_invalid_url_raises(self):
        with pytest.raises(Exception):
            Configuration(odoo_url="not-a-url", database="demo")


class TestApiKeyAlias:
    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            ({"#api_key": "secret_key"}, "secret_key"),
            ({"api_key": "direct_key"}, "direct_key"),
        ],
    )
    def test_api_key_set_via_alias_or_direct(self, kwargs, expected):
        config = Configuration(odoo_url=BASE_URL, database="demo", **kwargs)
        assert config.api_key == expected

    def test_api_key_defaults_to_empty(self, base_config):
        assert base_config.api_key == ""


class TestDefaults:
    @pytest.mark.parametrize(
        "field,expected",
        [
            ("database", ""),
            ("username", None),
            ("api_key", ""),
            ("api_protocol", "xmlrpc"),
            ("model", ""),
            ("fields", None),
            ("domain", None),
            ("incremental", False),
            ("page_size", 1000),
        ],
    )
    def test_default_value(self, field, expected):
        config = Configuration(odoo_url=BASE_URL)
        assert getattr(config, field) == expected


class TestApiProtocol:
    @pytest.mark.parametrize("protocol", ["xmlrpc", "json2"])
    def test_protocol_accepted(self, protocol):
        config = Configuration(odoo_url=BASE_URL, api_protocol=protocol)
        assert config.api_protocol == protocol


class TestTableName:
    @pytest.mark.parametrize(
        "model,expected",
        [
            ("res.partner", "res_partner.csv"),
            ("sale.order.line", "sale_order_line.csv"),
            ("", ""),
        ],
    )
    def test_table_name_conversion(self, model, expected):
        config = Configuration(odoo_url=BASE_URL, model=model)
        assert config.table_name == expected


class TestGetDomain:
    def test_empty_domain_returns_empty_list(self):
        config = Configuration(odoo_url=BASE_URL)
        assert config.get_domain() == []

    def test_valid_json_domain_parsed(self):
        config = Configuration(
            odoo_url=BASE_URL,
            domain='[["is_company", "=", true], ["country_id", "=", 233]]',
        )
        domain = config.get_domain()
        assert domain == [["is_company", "=", True], ["country_id", "=", 233]]

    def test_invalid_json_raises_user_exception(self):
        config = Configuration(odoo_url=BASE_URL, domain="not valid json")
        with pytest.raises(UserException, match="Invalid domain JSON"):
            config.get_domain()


class TestFieldsAndIncremental:
    @pytest.mark.parametrize("incremental", [True, False])
    def test_incremental_flag(self, incremental):
        config = Configuration(odoo_url=BASE_URL, incremental=incremental)
        assert config.incremental is incremental

    def test_fields_accepts_list(self):
        config = Configuration(odoo_url=BASE_URL, fields=["id", "name", "email"])
        assert config.fields == ["id", "name", "email"]

    @pytest.mark.parametrize("page_size", [100, 500, 1000, 10000])
    def test_page_size_accepted(self, page_size):
        config = Configuration(odoo_url=BASE_URL, page_size=page_size)
        assert config.page_size == page_size
