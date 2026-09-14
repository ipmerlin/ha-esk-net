"""Offline protocol tests using synthetic cabinet HTML, without importing HA."""

import base64
import importlib.util
import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path

from aiohttp import ClientConnectionError, CookieJar
from yarl import URL

# Load only the HA-independent package under a distinct name.
ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("esk_test_client")
package.__path__ = [str(ROOT / "custom_components" / "esk_net")]
sys.modules[package.__name__] = package
for module in ("const", "parser", "api"):
    spec = importlib.util.spec_from_file_location(
        f"esk_test_client.{module}", Path(package.__path__[0]) / f"{module}.py"
    )
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)

from esk_test_client.api import CannotConnect, EskClient, challenge_target  # noqa: E402
from esk_test_client.parser import (  # noqa: E402
    AuthenticationError,
    ParseError,
    parse_account,
    parse_tariff_info,
)

HTML = (ROOT / "tests/fixtures/account.html").read_text(encoding="utf-8")
TARIFF_HTML = (ROOT / "tests/fixtures/tariff_info.html").read_text(encoding="utf-8")
CHALLENGE = "var rs_ifr='/check'; var rs_uri='abc123';"
PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

from esk_test_client.sbp import SbpError, decode_qr, validate_amount  # noqa: E402


class SbpTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_qr_request_and_bytes(self):
        session = Session(Response(), Response(HTML), Response(PNG_BASE64))
        qr = await EskClient(session, "test", "secret").async_generate_qr(10, "00123456")
        self.assertEqual(qr, base64.b64decode(PNG_BASE64))
        self.assertEqual(
            session.calls[-1][0:2], ("GET", "https://lk.esknet.net/ajax/sbp.jsp?payment=10")
        )
        self.assertEqual(len(session.calls), 3)

    async def test_invalid_amount_never_requests(self):
        for amount in (9, -10, 10.1, 100001, "NaN", "Infinity", True, "bad"):
            session = Session()
            with self.subTest(amount=amount), self.assertRaises(SbpError):
                await EskClient(session, "test", "secret").async_generate_qr(amount, "00123456")
            self.assertEqual(session.calls, [])
        self.assertEqual(validate_amount("1001"), 1001)

    async def test_wrong_account_never_requests_qr(self):
        session = Session(Response(), Response(HTML))
        with self.assertRaises(AuthenticationError):
            await EskClient(session, "test", "secret").async_generate_qr(10, "different")
        self.assertEqual(len(session.calls), 2)

    async def test_failed_qr_not_retried(self):
        for error in (
            TimeoutError(),
            Response(status=500),
            Response(status=302, headers={"Location": "/index.jsp"}),
        ):
            session = Session(Response(), Response(HTML), error)
            with self.subTest(error=type(error).__name__), self.assertRaises(CannotConnect):
                await EskClient(session, "test", "secret").async_generate_qr(10, "00123456")
            self.assertEqual(len(session.calls), 3)

    async def test_non_png_and_malformed_response(self):
        for body in (
            "<html>Login</html>",
            "not base64",
            base64.b64encode(b"hello").decode(),
            PNG_BASE64[:-12],
            "a" * 2000001,
        ):
            with self.subTest(size=len(body)), self.assertRaises(SbpError):
                decode_qr(body)


class ParserTests(unittest.TestCase):
    def test_total_before_javascript_runs(self):
        page = TARIFF_HTML.replace("950 руб/мес", "... руб/мес")
        self.assertEqual(parse_tariff_info(page)[0], Decimal("950"))

    def test_total_and_services(self):
        total, services = parse_tariff_info(TARIFF_HTML)
        self.assertEqual(total, Decimal("950"))
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0].name, "Дополнительная услуга")
        self.assertEqual(services[0].monthly_price, Decimal("400"))

    def test_total_is_not_summed_from_service_prices(self):
        total, services = parse_tariff_info(TARIFF_HTML.replace("950 руб/мес", "875,50 руб/мес"))
        self.assertEqual(total, Decimal("875.50"))
        self.assertEqual(services[0].monthly_price, Decimal("400"))

    def test_absent_service_page_is_unknown(self):
        self.assertEqual(parse_tariff_info("<h1>Технические работы</h1>"), (None, None))

    def test_empty_activated_list_is_zero_services(self):
        self.assertEqual(
            parse_tariff_info('<h4>Активированные услуги:</h4><div class="service-list"></div>'),
            (None, ()),
        )

    def test_available_services_are_not_activated(self):
        self.assertIsNone(
            parse_tariff_info(TARIFF_HTML.replace("Активированные услуги:", "Доступные услуги:"))[1]
        )

    def test_unknown_price_and_multiple_services(self):
        page = TARIFF_HTML.replace(
            "</div>\n</div>",
            '</div><div class="service-item"><div class="serv-itm-title">Услуга 2</div><div class="serv-itm-price">По запросу</div></div>\n</div>',
        )
        services = parse_tariff_info(page)[1]
        self.assertEqual(len(services), 2)
        self.assertIsNone(services[1].monthly_price)

    def test_service_login_page_is_auth_error(self):
        with self.assertRaises(AuthenticationError):
            parse_tariff_info('<input type="password">')

    def test_all_fields_and_russian_numbers(self):
        data = parse_account(HTML)
        self.assertEqual(data.account, "00123456")
        self.assertEqual(data.balance, Decimal("-1234.50"))
        self.assertEqual(data.days_left, 7)
        self.assertEqual(data.tariff, "PRO100")
        self.assertEqual(data.tariff_price, Decimal("537.25"))

    def test_missing_optional_fields_are_unknown(self):
        data = parse_account(
            '<img src="account.png"><span>001</span>'
            '<div class="payment-info2-cell2"><strong>0</strong></div>'
        )
        self.assertEqual(data.balance, 0)
        self.assertIsNone(data.days_left)
        self.assertIsNone(data.tariff)
        self.assertIsNone(data.tariff_price)

    def test_missing_balance_does_not_become_zero(self):
        with self.assertRaises(ParseError):
            parse_account(HTML.replace("strong", "b"))

    def test_login_page(self):
        with self.assertRaises(AuthenticationError):
            parse_account('<form><input type="password" name="password"></form>')

    def test_maintenance_page(self):
        with self.assertRaises(ParseError):
            parse_account("<h1>Технические работы</h1>")

    def test_days_fallback(self):
        page = HTML.replace("<span>10</span>", "").replace("<span>7</span>", "")
        self.assertEqual(parse_account(page + '<div id="block-period">0</div>').days_left, 0)

    def test_nested_tags_and_nbsp(self):
        self.assertEqual(
            parse_account(HTML.replace("−1&nbsp;234,50", "<b>-2\u202f345,70</b>")).balance,
            Decimal("-2345.70"),
        )

    def test_external_challenge_rejected(self):
        for path in (
            "https://evil.example/check",
            "//evil.example/check",
            "%2F%2Fevil.example/check",
        ):
            with self.subTest(path=path), self.assertRaises(ParseError):
                challenge_target(CHALLENGE.replace("/check", path))


class Response:
    def __init__(self, text="", status=200, headers=None, charset="cp1251"):
        self.status = status
        self.headers = headers or {}
        self.charset = charset
        self.raw = text.replace("−", "-").encode(charset or "cp1251")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def read(self):
        return self.raw


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.cookie_jar = CookieJar()

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_total_with_dynamic_subscriptions(self):
        page = (
            TARIFF_HTML.replace("950 руб/мес", "... руб/мес")
            + "<script>url: 'ajax/megogo_packages.jsp'</script>"
        )
        session = Session(
            Response(),
            Response(HTML),
            Response(page),
            Response('[{"assigned":"Y","cost":"50.25"},{"assigned":"N","cost":900}]'),
        )
        result = await EskClient(session, "test", "secret").async_fetch()
        self.assertEqual(result.total_monthly_price, Decimal("1000.25"))
        self.assertEqual(session.calls[-1][1], "https://lk.esknet.net/ajax/megogo_packages.jsp")

    async def test_total_no_dynamic_subscriptions(self):
        page = (
            TARIFF_HTML.replace("950 руб/мес", "... руб/мес")
            + "<script>url: 'ajax/megogo_packages.jsp'</script>"
        )
        result = await EskClient(
            Session(Response(), Response(HTML), Response(page), Response("[]")), "test", "secret"
        ).async_fetch()
        self.assertEqual(result.total_monthly_price, Decimal("950"))

    async def test_subscription_failure_preserves_services_not_partial_total(self):
        page = TARIFF_HTML + "<script>url: 'ajax/megogo_packages.jsp'</script>"
        for response in (
            Response(status=500),
            Response("{}"),
            Response('[{"assigned":"Y","cost":"bad"}]'),
            Response("<html>Login</html>"),
        ):
            result = await EskClient(
                Session(Response(), Response(HTML), Response(page), response), "test", "secret"
            ).async_fetch()
            self.assertIsNone(result.total_monthly_price)
            self.assertEqual(len(result.active_services), 1)

    async def test_optional_page_failure_preserves_balance(self):
        for failure in (Response(status=500), TimeoutError(), Response("<h1>Unavailable</h1>")):
            with self.subTest(failure=type(failure).__name__):
                result = await EskClient(
                    Session(Response(), Response(HTML), failure), "test", "secret"
                ).async_fetch()
                self.assertEqual(result.balance, Decimal("-1234.50"))
                self.assertIsNone(result.total_monthly_price)
                self.assertIsNone(result.active_services)

    async def test_optional_page_auth_failure_is_not_hidden(self):
        with self.assertRaises(AuthenticationError):
            await EskClient(
                Session(Response(), Response(HTML), Response('<input type="password">')),
                "test",
                "secret",
            ).async_fetch()

    async def test_service_page_challenge(self):
        session = Session(Response(), Response(HTML), Response(CHALLENGE), Response(TARIFF_HTML))
        result = await EskClient(session, "test", "secret").async_fetch()
        self.assertEqual(result.total_monthly_price, Decimal("950"))
        self.assertEqual(session.calls[2][1], "https://lk.esknet.net/tariff_info.jsp")

    async def test_login_then_fetch(self):
        session = Session(Response(), Response(HTML), Response(TARIFF_HTML))
        result = await EskClient(session, "test", "secret").async_fetch()
        self.assertEqual(result.account, "00123456")
        self.assertEqual(result.total_monthly_price, Decimal("950"))
        self.assertEqual(len(result.active_services), 1)
        self.assertEqual(
            session.calls[0][2]["data"], {"login": "test", "password": "secret", "owner": "ENET"}
        )

    async def test_challenge_sets_cookie(self):
        session = Session(Response(), Response(CHALLENGE), Response(HTML), Response(TARIFF_HTML))
        result = await EskClient(session, "test", "secret").async_fetch()
        self.assertEqual(result.balance, Decimal("-1234.50"))
        self.assertEqual(session.calls[-2][1], "https://lk.esknet.net/check?rs_uri=abc123")
        cookies = session.cookie_jar.filter_cookies(URL("https://lk.esknet.net/"))
        self.assertEqual(cookies["rs_pending"].value, "/check%3Frs_uri%3Dabc123")

    async def test_repeated_challenge_is_bounded(self):
        session = Session(Response(), *[Response(CHALLENGE) for _ in range(3)])
        with self.assertRaises(ParseError):
            await EskClient(session, "test", "secret").async_fetch()
        self.assertEqual(len(session.calls), 4)

    async def test_external_redirect_never_receives_password(self):
        session = Session(Response(status=307, headers={"Location": "https://evil.example/"}))
        with self.assertRaises(CannotConnect):
            await EskClient(session, "test", "secret").async_fetch()
        self.assertEqual(len(session.calls), 1)

    async def test_same_origin_redirect_uses_get(self):
        session = Session(
            Response(status=302, headers={"Location": "/welcome"}),
            Response(),
            Response(HTML),
            Response(TARIFF_HTML),
        )
        await EskClient(session, "test", "secret").async_fetch()
        self.assertEqual(session.calls[1][0], "GET")
        self.assertNotIn("data", session.calls[1][2])

    async def test_http_error_classification(self):
        for status, error in (
            (401, AuthenticationError),
            (403, CannotConnect),
            (429, CannotConnect),
            (500, CannotConnect),
        ):
            with self.subTest(status=status), self.assertRaises(error):
                await EskClient(Session(Response(status=status)), "test", "secret").async_fetch()

    async def test_network_error_is_sanitized(self):
        with self.assertRaises(CannotConnect) as caught:
            await EskClient(
                Session(ClientConnectionError("sensitive")), "test", "secret"
            ).async_fetch()
        self.assertNotIn("sensitive", str(caught.exception))

    async def test_timeout(self):
        with self.assertRaises(CannotConnect):
            await EskClient(Session(TimeoutError()), "test", "secret").async_fetch()

    async def test_utf8_response(self):
        result = await EskClient(
            Session(Response(), Response(HTML, charset="utf-8"), Response(TARIFF_HTML)),
            "test",
            "secret",
        ).async_fetch()
        self.assertEqual(result.tariff, "PRO100")

    async def test_cookies_are_not_shared(self):
        first = Session(Response(), Response(CHALLENGE), Response(HTML), Response(TARIFF_HTML))
        second = Session(Response(), Response(HTML), Response(TARIFF_HTML))
        await EskClient(first, "one", "secret").async_fetch()
        await EskClient(second, "two", "secret").async_fetch()
        self.assertEqual(len(second.cookie_jar), 0)


if __name__ == "__main__":
    unittest.main()
