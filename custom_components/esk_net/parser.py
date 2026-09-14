"""Parse the legacy ESK cabinet without inventing missing values."""

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser


class EskError(Exception):
    """Base error with no credentials or response bodies."""


class AuthenticationError(EskError):
    """The cabinet still asks for credentials."""


class ParseError(EskError):
    """The expected cabinet layout is absent."""


@dataclass
class Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list = field(default_factory=list)

    @property
    def text(self):
        return "".join(c.text if isinstance(c, Node) else c for c in self.children)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()


class Document(HTMLParser):
    """Small tree sufficient for the cabinet's table/div markup."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


@dataclass(frozen=True)
class ActiveService:
    name: str
    monthly_price: Decimal | None


@dataclass(frozen=True)
class AccountData:
    account: str
    balance: Decimal
    days_left: int | None
    tariff: str | None
    tariff_price: Decimal | None
    total_monthly_price: Decimal | None = None
    active_services: tuple[ActiveService, ...] | None = None


def has_class(node: Node, name: str) -> bool:
    return name in (node.attrs.get("class") or "").split()


def total_with_subscriptions(base: Decimal | None, response: str) -> Decimal | None:
    """Match tariff_info.jsp's final total: hidden sum plus assigned Megogo packages."""
    try:
        packages = json.loads(response)
        if not isinstance(packages, list):
            raise ValueError
        extra = Decimal(0)
        for package in packages:
            if not isinstance(package, dict) or "assigned" not in package:
                raise ValueError
            if package["assigned"] == "Y":
                price = Decimal(str(package["cost"]))
                if not price.is_finite() or price < 0:
                    raise ValueError
                extra += price
        return base + extra if base is not None else None
    except (ValueError, KeyError, InvalidOperation) as err:
        raise ParseError("Invalid subscription cost response") from err


def parse_tariff_info(html: str) -> tuple[Decimal | None, tuple[ActiveService, ...] | None]:
    """Read the authoritative total and the activated section of tariff_info.jsp."""
    nodes = list(Document(html).root.walk())
    if any(n.tag == "input" and (n.attrs.get("type") or "").lower() == "password" for n in nodes):
        raise AuthenticationError("Cabinet requires authentication")
    total = None
    for node in nodes:
        if has_class(node, "base-payment"):
            total = next(
                (
                    value
                    for child in node.walk()
                    if child.tag == "strong" and (value := number(child.text)) is not None
                ),
                None,
            )
            if total is None:
                total = next(
                    (number(child.text) for child in node.walk() if child.attrs.get("id") == "sum"),
                    None,
                )
            break

    # Only a service-list following the activated-services heading is authoritative.
    # Other lists may advertise services which have not been activated.
    listing = None
    for parent in nodes:
        children = [c for c in parent.children if isinstance(c, Node)]
        for index, child in enumerate(children[:-1]):
            if (
                child.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
                and (" ".join(child.text.split()).rstrip(":").casefold() == "активированные услуги")
                and has_class(children[index + 1], "service-list")
            ):
                listing = children[index + 1]
                break
        if listing is not None:
            break
    if listing is None:
        return total, None
    services = []
    for item in listing.walk():
        if not has_class(item, "service-item"):
            continue
        title = next(
            (" ".join(n.text.split()) for n in item.walk() if has_class(n, "serv-itm-title")), ""
        )
        if not title:
            return total, None  # Do not report a misleading partial count.
        price = next((number(n.text) for n in item.walk() if has_class(n, "serv-itm-price")), None)
        services.append(ActiveService(title, price))
    if not services and listing.text.strip():
        return total, None  # Unknown replacement markup is not an empty list.
    return total, tuple(services)


def number(text):
    """Accept Russian thousands separators and decimal commas."""
    match = re.search(r"[+\-−]?\s*\d[\d\s]*(?:[.,]\d+)?", text)
    if not match:
        return None
    try:
        return Decimal(re.sub(r"\s", "", match[0]).replace(",", ".").replace("−", "-"))
    except InvalidOperation:
        return None


def parse_account(html: str) -> AccountData:
    nodes = list(Document(html).root.walk())
    cells = [n for n in nodes if "payment-info2-cell2" in (n.attrs.get("class") or "").split()]
    balances = [number(c.text) for n in cells for c in n.walk() if c.tag == "strong"]
    balance = next((b for b in balances if b is not None), None)
    account = None
    # The original script identifies the account by the account.png icon.
    for index, node in enumerate(nodes):
        if node.tag == "img" and "account.png" in (node.attrs.get("src") or ""):
            for following in nodes[index + 1 : index + 12]:
                if following.tag == "span" and (match := re.search(r"\b\d+\b", following.text)):
                    account = match[0]
                    break
            if account:
                break
    if balance is None or account is None:
        if any(
            n.tag == "input" and (n.attrs.get("type") or "").lower() == "password" for n in nodes
        ):
            raise AuthenticationError("Cabinet requires authentication")
        raise ParseError("Account or balance missing in cabinet response")
    days = [
        int(c.text.strip())
        for n in cells
        for c in n.walk()
        if c.tag == "span" and re.fullmatch(r"\d+", c.text.strip())
    ]
    if not days:
        days = [
            int(m[0])
            for n in nodes
            if n.attrs.get("id") == "block-period" and (m := re.match(r"\d+", n.text.strip()))
        ]
    tariff = re.search(r"«([^»]+)»", Document(html).root.text)
    prices = [number(n.text) for n in nodes if "price" in (n.attrs.get("class") or "").split()]
    return AccountData(
        account,
        balance,
        days[-1] if days else None,
        tariff[1].strip() if tariff else None,
        next((p for p in prices if p is not None), None),
    )
