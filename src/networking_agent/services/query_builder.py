"""Generates diverse search-query strings for the Discovery Agent.

Deliberately varies phrasing/operators so discovery doesn't depend on one
search-engine query shape (per design doc: "Do not rely on one search
engine query format"). Pure functions -- no I/O -- so they're easy to unit
test independently of any SearchProvider.
"""
from __future__ import annotations

import itertools
import random

UT_PHRASES = [
    '"University of Texas at Austin"',
    '"UT Austin"',
    '"Texas Exes"',
    '"McCombs School of Business"',
    '"UT Austin alumni"',
]

CRE_KEYWORDS = ["capital markets", "commercial real estate", "investment sales", "acquisitions"]


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def build_tech_sales_queries(
    titles: list[str], companies: list[str], location: str | None, limit: int = 25
) -> list[str]:
    queries: list[str] = []
    for ut_phrase, title, company in itertools.product(UT_PHRASES, titles, companies):
        q = f'{ut_phrase} "{title}" "{company}"'
        if location:
            q += f' "{location}"'
        queries.append(q)
    for company in companies:
        queries.append(f'site:{_guess_domain(company)} "University of Texas at Austin"')
    for ut_phrase, title in itertools.product(UT_PHRASES, titles):
        q = f'{ut_phrase} "{title}" technology sales'
        if location:
            q += f' "{location}"'
        queries.append(q)
    random.shuffle(queries)
    return _dedupe_preserve_order(queries)[:limit]


def build_cre_queries(
    titles: list[str], companies: list[str], location: str | None, limit: int = 25
) -> list[str]:
    queries: list[str] = []
    for ut_phrase, title, company in itertools.product(UT_PHRASES, titles, companies):
        q = f'{ut_phrase} "{title}" "{company}"'
        if location:
            q += f' "{location}"'
        queries.append(q)
    for ut_phrase, keyword in itertools.product(UT_PHRASES, CRE_KEYWORDS):
        q = f'{ut_phrase} "{keyword}"'
        if location:
            q += f' "{location}"'
        queries.append(q)
    for company in companies:
        queries.append(f'site:{_guess_domain(company)} "University of Texas at Austin"')
    random.shuffle(queries)
    return _dedupe_preserve_order(queries)[:limit]


def build_queries(category: str, titles: list[str], companies: list[str], location: str | None, limit: int = 25) -> list[str]:
    if category == "cre":
        return build_cre_queries(titles, companies, location, limit)
    return build_tech_sales_queries(titles, companies, location, limit)


def _guess_domain(company_name: str) -> str:
    cleaned = (
        company_name.lower()
        .replace(" & ", "")
        .replace("&", "")
        .replace(",", "")
        .replace(".", "")
        .split(" (")[0]
    )
    cleaned = "".join(ch for ch in cleaned if ch.isalnum())
    return f"{cleaned}.com"
