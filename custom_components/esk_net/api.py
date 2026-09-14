"""Asynchronous ESK cabinet client, isolated per account."""

import asyncio
import re
from dataclasses import replace
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit

from aiohttp import ClientError, ClientSession
from yarl import URL

from .const import BASE_URL
from .parser import (
    AccountData,
    AuthenticationError,
    EskError,
    ParseError,
    parse_account,
    parse_tariff_info,
)
from .sbp import decode_qr, validate_amount


class CannotConnect(EskError):
    """Network or HTTP failure."""


def challenge_target(html: str) -> tuple[str, str] | None:
    """Handle the legacy rs_pending challenge, only on the cabinet origin."""
    iframe = re.search(r"rs_ifr\s*=\s*['\"]([^'\"]+)['\"]", html)
    token = re.search(r"rs_uri\s*=\s*['\"]([^'\"]+)['\"]", html)
    if not iframe or not token:
        return None
    path = unquote(iframe[1])
    target = urljoin(BASE_URL + "/", path)
    parsed = urlsplit(target)
    if (parsed.scheme, parsed.netloc) != ("https", "lk.esknet.net") or "\\" in path:
        raise ParseError("Unexpected challenge origin")
    target += ("&" if parsed.query else "?") + urlencode({"rs_uri": token[1]})
    cookie = quote(f"{path}?rs_uri={token[1]}", safe="@*_+-./")
    return target, cookie


class EskClient:
    def __init__(self, session: ClientSession, username: str, password: str):
        self.session = session
        self.username = username
        self.password = password
        self._lock = asyncio.Lock()

    async def _request(self, method, url, *, follow_redirects=True, **kwargs):
        # Follow redirects ourselves to keep credentials/cookies on the expected origin.
        for _ in range(5):
            async with self.session.request(
                method,
                url,
                allow_redirects=False,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "X-Requested-With": "XMLHttpRequest",
                },
                **kwargs,
            ) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    if not follow_redirects:
                        raise CannotConnect("Unexpected redirect while generating QR")
                    location = response.headers.get("Location")
                    if not location:
                        raise CannotConnect("Redirect without location")
                    url = urljoin(url, location)
                    parsed = urlsplit(url)
                    if (parsed.scheme, parsed.netloc) != ("https", "lk.esknet.net"):
                        raise CannotConnect("Unexpected redirect origin")
                    if response.status == 303 or (
                        response.status in {301, 302} and method == "POST"
                    ):
                        method, kwargs = "GET", {}
                    continue
                if response.status == 401:
                    raise AuthenticationError("Authentication rejected")
                if response.status >= 400:
                    raise CannotConnect(f"Cabinet HTTP {response.status}")
                raw = await response.read()
                # The supplied script explicitly uses Windows-1251. Honor UTF-8 when declared.
                charset = response.charset or "cp1251"
                try:
                    return raw.decode(charset, errors="replace")
                except LookupError:
                    return raw.decode("cp1251", errors="replace")
        raise CannotConnect("Too many redirects")

    async def _page(self, path):
        html = await self._request("GET", f"{BASE_URL}{path}")
        for _ in range(2):
            challenge = challenge_target(html)
            if challenge is None:
                return html
            target, cookie = challenge
            self.session.cookie_jar.update_cookies(
                {"rs_pending": cookie}, response_url=URL(BASE_URL)
            )
            html = await self._request("GET", target)
        if challenge_target(html) is not None:
            raise ParseError("Cabinet challenge was not resolved")
        return html

    async def async_fetch(self) -> AccountData:
        async with self._lock:
            return await self._fetch()

    async def async_generate_qr(self, amount, expected_account: str) -> bytes:
        amount = validate_amount(amount)
        async with self._lock:
            try:
                async with asyncio.timeout(60):
                    await self._request(
                        "POST",
                        f"{BASE_URL}/ajax/login.jsp",
                        data={"login": self.username, "password": self.password, "owner": "ENET"},
                    )
                    data = parse_account(await self._page("/index.jsp"))
                    if data.account != expected_account:
                        raise AuthenticationError("Account changed; check credentials")
                    # Exactly one QR request. Do not retry an ambiguous response.
                    response = await self._request(
                        "GET", f"{BASE_URL}/ajax/sbp.jsp?payment={amount}", follow_redirects=False
                    )
                    return decode_qr(response)
            except (ClientError, TimeoutError) as err:
                raise CannotConnect("Could not obtain SBP QR") from err

    async def _fetch(self) -> AccountData:
        try:
            async with asyncio.timeout(90):
                await self._request(
                    "POST",
                    f"{BASE_URL}/ajax/login.jsp",
                    data={
                        "login": self.username,
                        "password": self.password,
                        "owner": "ENET",
                    },
                )
                data = parse_account(await self._page("/index.jsp"))
                try:
                    async with asyncio.timeout(30):
                        total, services = parse_tariff_info(await self._page("/tariff_info.jsp"))
                except (CannotConnect, ParseError, ClientError, TimeoutError):
                    # An optional page failure must not hide a fresh balance or keep stale prices.
                    return data
                return replace(data, total_monthly_price=total, active_services=services)
        except (ClientError, TimeoutError) as err:
            raise CannotConnect("Could not reach ESK cabinet") from err
