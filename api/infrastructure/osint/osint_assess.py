"""Evidence-based, conservative OSINT assessment for UrbexFinder (v2).

Drop-in replacement for ``infrastructure.osint.osint_assess``.

Public API:
    assess_osint_items(items: list[dict]) -> dict

No additional dependencies. Analyses *textual claims* in titles/snippets, not the
physical reality at a location. Unknown and conflicting results are intentional.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import blake2s
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, unquote


SECURITY_LABELS = {
    "high": "Высокая", "medium": "Средняя", "low": "Низкая", "unknown": "Неясно",
}
CONDITION_LABELS = {
    "demolished": "Снесён", "abandoned": "Заброшен", "active": "Действует", "unknown": "Неясно",
}

# None of these is an access recommendation. Low security requires an EXPLICIT
# assertion that guarding is absent; an open gate or broken fence is insufficient.
_SECURITY_RULES = (
    ("low", 3.0, r"\bне\s+охраня(?:ется|лся|лась|лось|ются|ли|ют|ет)\b"),
    ("low", 3.0, r"\b(?:без\s+охраны|охрана\s+отсутствует|нет\s+охраны|охраны\s+нет)\b"),
    ("low", 2.5, r"\b(?:охрану\s+сняли|посты\s+охраны\s+сняты|сторожей\s+нет|нет\s+сторож\w*|охранников\s+нет)\b"),
    ("high", 3.0, r"\b(?:охраняется|охраняют|охраняли|под\s+охраной|дежурит\s+охран[аник]+)\b"),
    ("high", 2.8, r"\b(?:частная\s+охрана|сотрудники\s+охраны|пост\s+охраны|чоп|кпп|сторож\w*|патрул\w*|росгвард\w*)\b"),
    ("medium", 2.0, r"\b(?:пропускн\w*\s+режим|вход\s+запрещ[её]н|проход\s+запрещ[её]н|закрытая\s+территория)\b"),
    ("medium", 1.5, r"\b(?:видеонаблюден\w*|камеры\s+наблюдения|охранная\s+сигнализац\w*)\b"),
)

_CONDITION_RULES = (
    ("demolished", 3.5, r"\b(?:снес[её]н\w*|снесли|снесла|снесло|демонтирован\w*|снос\s+заверш[её]н|снос\s+состоялся)\b"),
    ("demolished", 3.1, r"\b(?:полностью\s+разобран\w*|полностью\s+уничтожен\w*|ст[её]рт\w*\s+с\s+лица\s+земли)\b"),
    ("abandoned", 3.0, r"\b(?:заброшен\w*|заброшк\w*|пустует|пустовал\w*|законсервирован\w*|не\s+используется|выведен\w*\s+из\s+эксплуатации)\b"),
    ("abandoned", 2.2, r"\b(?:руин\w*|развалин\w*|разрушен\w*|полуразрушен\w*|не\s+функционирует|прекратил\w*\s+работу|закрылся)\b"),
    ("active", 3.0, r"\b(?:сейчас\s+действует|сейчас\s+работает|функционирует|действует|работает|принимает\s+детей|открыт\w*\s+для\s+посещен\w*)\b"),
    ("active", 3.2, r"\b(?:восстановлен\w*\s+и\s+открыт\w*|вновь\s+открыт\w*|возобновил\w*\s+работу|после\s+реконструкции\s+открыт\w*)\b"),
)

# Match denial before positive rules, then veto *overlapping* fragments.
# "не снесён" is NOT automatically evidence of an operating facility.
_SECURITY_VETO = (
    r"\bне\s+охраня\w*\b", r"\bбез\s+охраны\b", r"\bнет\s+охраны\b",
    r"\bохрана\s+отсутствует\b", r"\bохраны\s+нет\b",
    r"\bне\s+под\s+охраной\b", r"\bбез\s+видеонаблюдения\b",
    r"\bнет\s+видеонаблюдения\b", r"\bкамер\s+нет\b",
    r"\bнет\s+(?:сторож\w*|охранник\w*)\b",
    r"\b(?:сторож\w*|охранник\w*)\s+нет\b",
    r"\b(?:камеры(?:\s+наблюдения)?|видеонаблюдение|сигнализация)\s+не\s+работа\w*\b",
    r"\b(?:кпп|пост\s+охраны)\s+(?:не\s+работает|закрыт|заброшен\w*)\b",
    r"\b(?:бывш\w*|старый|заброшен\w*)\s+(?:кпп|пост\s+охраны)\b",
)
_CONDITION_VETO = (
    r"\bне\s+снес\w*\b", r"\b(?:не|ещ[её]\s+не)\s+демонтирован\w*\b",
    r"\bснос\s+не\s+(?:состоялся|заверш[её]н|проводился)\b",
    r"\bне\s+заброшен\w*\b", r"\bне\s+пустует\b",
    r"\bне\s+(?:работает|действует|функционирует|открыт\w*)\b",
    r"\bперестал\w*\s+работать\b", r"\bбольше\s+не\s+работает\b",
    r"\bпланируют\s+снести\b", r"\bмогут\s+снести\b",
)

_CLAUSE_SPLIT = re.compile(
    r"(?<=[.!?;])\s+|[\r\n]+|\s+\b(?:но|однако|зато)\b\s+|"
    r",\s*(?=а\s+(?:сейчас|теперь|в\s+(?:19|20)\d{2})\b)", re.I
)
_YEAR_IN_CLAUSE = re.compile(
    r"\b(?:в|с|к|после|до|на)\s+((?:19|20)\d{2})(?:\s*(?:году|года|г\.?))?\b|"
    r"\b((?:19|20)\d{2})\s*(?:году|года|г\.)\b", re.I
)
_CURRENT = re.compile(r"\b(?:сейчас|теперь|ныне|сегодня|в\s+настоящее\s+время|"
                      r"на\s+данный\s+момент|на\s+сегодняшний\s+день)\b", re.I)
_HEDGE = re.compile(r"\b(?:возможно|вероятно|предположительно|якобы|по\s+слухам|"
                    r"вроде\s+бы|может\s+быть|похоже)\b", re.I)
_PAST_ONLY = re.compile(r"\b(?:раньше|ранее|когда-то|в\s+прошлом|прежде)\b", re.I)
_DIRECT_IMAGE = re.compile(r"\.(?:jpe?g|png|gif|webp|bmp|avif)(?:$|[?#])", re.I)
_VK_GROUP = re.compile(r"^(?:club|public|event)\d+$", re.I)
_UTM_KEYS = {"fbclid", "gclid", "yclid", "ref", "ref_src"}


def _compile_rules(specs):
    return tuple((level, strength, re.compile(pattern, re.I))
                 for level, strength, pattern in specs)


SECURITY_RULES = _compile_rules(_SECURITY_RULES)
CONDITION_RULES = _compile_rules(_CONDITION_RULES)
SECURITY_VETO = tuple(re.compile(p, re.I) for p in _SECURITY_VETO)
CONDITION_VETO = tuple(re.compile(p, re.I) for p in _CONDITION_VETO)


@dataclass(frozen=True)
class Claim:
    dimension: str
    level: str
    term: str
    strength: float
    title: str
    url: str
    site: str
    fragment: str
    in_title: bool
    occurred_at: datetime | None
    current_wording: bool
    speculative: bool


def _date_from_value(value) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            v = float(value)
            if abs(v) > 1e11:
                v /= 1000
            return datetime.fromtimestamp(v, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    raw = str(value).strip()
    if not raw:
        return None
    if re.fullmatch(r"(?:19|20)\d{2}", raw):
        return datetime(int(raw), 12, 31, tzinfo=timezone.utc)
    if re.fullmatch(r"\d{10}(?:\.\d+)?|\d{13}", raw):
        return _date_from_value(float(raw))
    try:
        return _date_from_value(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d", "%d.%m.%Y %H:%M"):
        try:
            return _date_from_value(datetime.strptime(raw, fmt))
        except ValueError:
            pass
    try:
        return _date_from_value(parsedate_to_datetime(raw))
    except (ValueError, TypeError, IndexError):
        return None


def _published_at(item: dict) -> datetime | None:
    for key in ("published_at", "published_date", "publication_date", "published", "date", "pubdate", "created_at", "timestamp"):
        dt = _date_from_value(item.get(key))
        if dt:
            return dt
    return None


def _canonical_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
        host = (p.hostname or "").lower().removeprefix("www.")
        if not host:
            return ""
        query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                               if not k.casefold().startswith("utm_") and k.casefold() not in _UTM_KEYS))
        path = unquote(p.path).rstrip("/") or "/"
        return urlunsplit((p.scheme.casefold() or "https", host, path, query, ""))
    except ValueError:
        return ""


def _is_non_article(url: str) -> bool:
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower().removeprefix("www.")
        path = p.path.strip("/")
    except ValueError:
        return True
    if _DIRECT_IMAGE.search(url):
        return True
    if host in {"vk.com", "m.vk.com"} and _VK_GROUP.fullmatch(path):
        return True
    return False


def _source_identity(item: dict, title: str, snippet: str) -> tuple[str, str]:
    url = str(item.get("url") or item.get("source_url") or "").strip()
    clean = _canonical_url(url)
    if clean:
        host = urlsplit(clean).hostname or "unknown"
        return clean, host
    fingerprint = blake2s((title + "\n" + snippet).casefold().encode(), digest_size=12).hexdigest()
    return "unknown:" + fingerprint, "unknown:" + fingerprint


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip()


def _clause_date(fragment: str, published: datetime | None, as_of: datetime) -> datetime | None:
    match = _YEAR_IN_CLAUSE.search(fragment)
    if match:
        year = int(match.group(1) or match.group(2))
        if 1900 <= year <= as_of.year + 1:
            return datetime(year, 12, 31, tzinfo=timezone.utc)
    return published if published and published <= as_of else None


def _extract_claims(items: list[dict], as_of: datetime) -> list[Claim]:
    results: list[Claim] = []
    seen_articles: set[tuple[str, str]] = set()
    seen_copied_text: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()[:300]
        snippet = re.sub(r"\s+", " ", str(item.get("snippet") or "")).strip()[:4000]
        if not title and not snippet:
            continue
        url = str(item.get("url") or item.get("source_url") or "").strip()[:2000]
        if _is_non_article(url):
            continue
        source, site = _source_identity(item, title, snippet)
        text_fingerprint = _normalize(title + " " + snippet)
        if (source, text_fingerprint) in seen_articles or text_fingerprint in seen_copied_text:
            continue
        seen_articles.add((source, text_fingerprint))
        seen_copied_text.add(text_fingerprint)
        published = _published_at(item)
        for content, in_title in ((title, True), (snippet, False)):
            for raw_clause in _CLAUSE_SPLIT.split(content):
                fragment = _normalize(raw_clause)
                if not fragment:
                    continue
                occurred = _clause_date(fragment, published, as_of)
                is_current = bool(_CURRENT.search(fragment))
                speculative = bool(_HEDGE.search(fragment))
                # A formerly guarded/operating site is not necessarily so now.
                # Without an explicit historical date such claims are excluded.
                if (_PAST_ONLY.search(fragment) and not is_current and
                    not _YEAR_IN_CLAUSE.search(fragment)):
                    continue
                for dimension, rules, vetoes in (
                    ("security", SECURITY_RULES, SECURITY_VETO),
                    ("condition", CONDITION_RULES, CONDITION_VETO),
                ):
                    blocked = [m.span() for p in vetoes for m in p.finditer(fragment)]
                    candidates: list[tuple[str, float, re.Match[str]]] = []
                    for level, weight, pattern in rules:
                        for match in pattern.finditer(fragment):
                            if any(match.start() < end and match.end() > start
                                   for start, end in blocked):
                                # BUT "не охраняется" is an explicit *low* claim.
                                # Its own low rule must still be counted.
                                if not (dimension == "security" and level == "low"):
                                    continue
                            candidates.append((level, weight, match))
                    # Overlapping patterns for one event count once, strongest wins.
                    chosen: list[tuple[str, float, re.Match[str]]] = []
                    for candidate in sorted(candidates, key=lambda c: (-c[1], -len(c[2].group()))):
                        m = candidate[2]
                        if any(m.start() < old[2].end() and m.end() > old[2].start()
                               for old in chosen):
                            continue
                        chosen.append(candidate)
                    for level, weight, match in chosen:
                        results.append(Claim(
                            dimension=dimension, level=level, term=match.group(),
                            strength=weight * (0.45 if speculative else 1.0),
                            title=title, url=url, site=site, fragment=raw_clause.strip()[:300],
                            in_title=in_title, occurred_at=occurred,
                            current_wording=is_current, speculative=speculative,
                        ))
    return results


def _best_per_source(claims: list[Claim]) -> list[Claim]:
    """One independent assertion per URL/dimension (prefer latest event)."""
    groups: dict[tuple[str, str], list[Claim]] = defaultdict(list)
    for c in claims:
        source = _canonical_url(c.url) or "no-url:" + blake2s(c.title.encode(), digest_size=10).hexdigest()
        groups[(source, c.dimension)].append(c)
    output = []
    for group in groups.values():
        # Latest explicit event > currently-worded claim > stronger evidence.
        dated = [c for c in group if c.occurred_at]
        if dated:
            max_date = max(c.occurred_at for c in dated)
            group = [c for c in group if c.occurred_at == max_date or
                     (not c.occurred_at and c.current_wording)]
        if any(c.current_wording for c in group):
            group = [c for c in group if c.current_wording]
        best_level = max(group, key=lambda c: (c.strength, not c.in_title)).level
        # If a single source asserts mutually incompatible things in the same
        # time slice, keep evidence of both for an explicit conflict decision.
        by_level: dict[str, Claim] = {}
        for c in group:
            old = by_level.get(c.level)
            if old is None or (c.strength, not c.in_title) > (old.strength, not old.in_title):
                by_level[c.level] = c
        output.extend(by_level.values())
    return output


def _signal(claim: Claim) -> dict:
    return {
        "term": claim.term[:120],
        "url": claim.url,
        "title": claim.title,
        "in_title": claim.in_title,
        "excerpt": claim.fragment,
        "date": claim.occurred_at.date().isoformat() if claim.occurred_at else None,
        "speculative": claim.speculative,
    }


def _decide(dimension: str, all_claims: list[Claim], as_of: datetime) -> dict:
    labels = SECURITY_LABELS if dimension == "security" else CONDITION_LABELS
    dimension_claims = [c for c in all_claims if c.dimension == dimension]
    if not dimension_claims:
        return {"level": "unknown", "label": labels["unknown"], "confidence": "low",
                "signals": [], "conflicting_evidence": False, "stale": False,
                "sources_count": 0, "evidence_date": None}

    dated = [c for c in dimension_claims if c.occurred_at]
    if dated:
        latest = max(c.occurred_at for c in dated)
        # Old statements cannot cancel recent ones. Year-only dates resolve to
        # Dec 31 and are approximate, but still useful for ordering.
        window_days = 730 if dimension == "security" else 1095
        candidates = [c for c in dimension_claims if (
            c.occurred_at and abs((latest - c.occurred_at).days) <= window_days
        ) or (not c.occurred_at and c.current_wording)]
    else:
        latest = None
        candidates = dimension_claims

    # Explicit historical claims about security >2 years old (abandoned/active
    # >5 years old) are not sufficient to assert PRESENT status.
    age_days = (as_of - latest).days if latest else None
    stale = bool(age_days is not None and age_days > (
        730 if dimension == "security" else 1825
    ) and not (dimension == "condition" and any(c.level == "demolished" for c in candidates)))

    # Hearsay alone is not enough for an assertion of present status.
    assertive = [c for c in candidates if not c.speculative]
    if assertive:
        candidates = assertive

    scores: dict[str, float] = defaultdict(float)
    counts: dict[str, set[str]] = defaultdict(set)
    by_level: dict[str, list[Claim]] = defaultdict(list)
    for c in candidates:
        # A single domain may contain multiple pages; cap repeated votes from
        # the same publisher to avoid confidence inflation.
        domain_n = len([p for p in by_level[c.level] if p.site == c.site])
        contribution = c.strength * (1.0 if domain_n == 0 else 0.15)
        if c.in_title and not c.current_wording:
            contribution *= 0.85  # A historical title often outlives a new status.
        scores[c.level] += contribution
        counts[c.level].add(c.site)
        by_level[c.level].append(c)

    ranked = sorted(scores, key=lambda x: scores[x], reverse=True)
    best = ranked[0] if ranked else "unknown"
    second = ranked[1] if len(ranked) > 1 else None
    second_score = scores.get(second, 0) if second else 0
    contradictory = bool(second and second_score >= max(1.1, scores[best] * 0.55))
    if stale or contradictory or not assertive:
        best = "unknown"

    if best == "unknown":
        confidence = "low"
        examples = sorted(candidates, key=lambda c: -c.strength)[:5]
        evidence_domains = {c.site for c in candidates}
    else:
        evidence_domains = counts[best]
        matching = by_level[best]
        has_strong = any(c.strength >= 2.5 and not c.speculative for c in matching)
        recent = latest is not None and age_days is not None and age_days <= (
            365 if dimension == "security" else 1095
        )
        clean = second_score < scores[best] * 0.3
        if len(evidence_domains) >= 2 and recent and has_strong and clean:
            confidence = "high"
        elif (has_strong and recent) or (len(evidence_domains) >= 2 and clean):
            confidence = "medium"
        else:
            confidence = "low"
        examples = sorted(matching, key=lambda c: (not c.current_wording, not bool(c.occurred_at),
                                                   -c.strength))[:5]
    return {
        "level": best,
        "label": labels[best],
        "confidence": confidence,
        "signals": [_signal(c) for c in examples],
        "conflicting_evidence": contradictory,
        "stale": stale,
        "sources_count": len(evidence_domains),
        "evidence_date": latest.date().isoformat() if latest else None,
    }


def assess_osint_items(items: list[dict], *, as_of: datetime | None = None) -> dict:
    """Assess only evidence in titles/snippets. Conservative: unknown is valid.

    ``items`` accepts dicts with ``title``, ``snippet`` and ``url``; optional
    date fields: ``published_at``, ``published_date``, ``date`` and others.
    The returned structure is backward compatible with ``osint_report.py``.
    ``as_of`` supports repeatable tests; normal callers can omit it.
    """
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    if not isinstance(items, list):
        items = []
    claims = _best_per_source(_extract_claims(items, now))
    security = _decide("security", claims, now)
    condition = _decide("condition", claims, now)

    if security["level"] == "unknown" and condition["level"] == "unknown":
        summary = "Достоверных актуальных сведений об охране и состоянии недостаточно."
    else:
        summary = f"Охраняемость: {security['label']}. Состояние: {condition['label']}."
    if security["conflicting_evidence"] or condition["conflicting_evidence"]:
        summary += " В источниках есть противоречия."
    if security["stale"] or condition["stale"]:
        summary += " Часть сведений устарела."
    return {
        "security": security,
        "condition": condition,
        "summary": summary,
        "disclaimer": (
            "Автоматическая оценка по заголовкам и фрагментам открытых источников. "
            "Она не подтверждает фактический режим доступа или текущее состояние объекта. "
            "Отсутствие упоминаний об охране не означает, что охраны нет."
        ),
    }
