"""Asynchronous ESK cabinet client, isolated per account."""

import asyncio
import re
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit

from aiohttp import ClientError, ClientSession
from yarl import URL

from .const import BASE_URL
from .parser import AccountData, AuthenticationError, EskError, ParseError, parse_account


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

    async def _request(self, method, url, **kwargs):
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

    async def async_fetch(self) -> AccountData:
        try:
            async with asyncio.timeout(60):
                await self._request(
                    "POST",
                    f"{BASE_URL}/ajax/login.jsp",
                    data={
                        "login": self.username,
                        "password": self.password,
                        "owner": "ENET",
                    },
                )
                html = await self._request("GET", f"{BASE_URL}/index.jsp")
                for _ in range(2):
                    challenge = challenge_target(html)
                    if challenge is None:
                        break
                    target, cookie = challenge
                    self.session.cookie_jar.update_cookies(
                        {"rs_pending": cookie}, response_url=URL(BASE_URL)
                    )
                    html = await self._request("GET", target)
                if challenge_target(html) is not None:
                    raise ParseError("Cabinet challenge was not resolved")
                return parse_account(html)
        except (ClientError, TimeoutError) as err:
            raise CannotConnect("Could not reach ESK cabinet") from err
