"""Parse the legacy ESK cabinet without inventing missing values."""

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
class AccountData:
    account: str
    balance: Decimal
    days_left: int | None
    tariff: str | None
    tariff_price: Decimal | None


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
