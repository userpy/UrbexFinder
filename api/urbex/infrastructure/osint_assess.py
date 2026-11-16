"""Heuristic OSINT assessment: security and physical condition from search snippets."""
from __future__ import annotations
import re
from urbex.infrastructure.osint_description import is_vk_group_url, is_direct_image_url
from collections import defaultdict

# (level, weight, terms)
_SECURITY = (
    (
        'high',
        3,
        (
            'охраняется', 'под охраной', 'частная охрана', 'чоп', 'кпп',
            'видеонаблюдение', 'видеокамера', 'камеры наблюдения', 'сигнализация',
            'патруль', 'вахтёр', 'вахтер', 'сторож', 'пропускной режим',
            'колючая проволока', 'огн', 'росгвардия',
        ),
    ),
    (
        'medium',
        2,
        (
            'охрана', 'забор', 'ограждение', 'шлагбаум', 'ворота закрыт',
            'на замок', 'закрытая территория', 'частная территория',
            'проход запрещён', 'проход запрещен', 'вход запрещён', 'вход запрещен',
            'табличка', 'собак',
        ),
    ),
    (
        'low',
        2,
        (
            'без охраны', 'не охраняется', 'свободный вход', 'свободный доступ',
            'дыра в заборе', 'лаз', 'открытый доступ', 'забор разрушен',
            'калитка открыта', 'можно пройти',
        ),
    ),
)

# Condition: abandoned / active / demolished
_CONDITION = (
    (
        'demolished',
        4,
        (
            'снесён', 'снесен', 'снесена', 'снесено', 'снос ', 'демолир',
            'на месте новострой', 'полностью уничтожен', 'стерт с лица',
            'стёрт с лица',
        ),
    ),
    (
        'abandoned',
        3,
        (
            'заброшен', 'заброшк', 'заброшенн', 'не используется', 'пустован',
            'законсервирован', 'выведен из эксплуатации', 'недействующ',
            'руин', 'развалин', 'обрушил', 'аварийн', 'разрушает', 'разрушен',
            'рухнул', 'обвалил', 'полуразрушен', 'частично разрушен',
            'бывший лагер', 'бывший пионер', 'бывший детск', 'бывш. лагер',
            'здания пуст', 'корпуса пуст', 'пустые корпус', 'пустые здания',
            'продан на аукцион', 'проданы на аукцион', 'продали на аукцион',
            'не функционир', 'закрыт с ', 'закрылся', 'прекратил работ',
        ),
    ),
    (
        'active',
        2,
        (
            'сейчас действует', 'лагерь работает', 'принимает детей',
            'идёт набор', 'идет набор', 'открыт набор', 'работает в сезон',
            'функционирует', 'музей работает', 'открыт для посещ',
            'отремонтирован', 'восстановлен и открыт',
        ),
    ),
)
# Past / ruin cues cancel "active" hits in the same snippet.
_CONDITION_INACTIVE_CONTEXT = (
    'заброшен', 'заброшк', 'бывший', 'бывш', 'руин', 'развалин',
    'пустые', 'пусты', 'аукцион', 'не используется', 'законсервир',
)

_SECURITY_LABELS = {
    'high': 'Высокая',
    'medium': 'Средняя',
    'low': 'Низкая',
    'unknown': 'Неясно',
}

_CONDITION_LABELS = {
    'abandoned': 'Заброшен',
    'active': 'Действует',
    'demolished': 'Снесён',
    'unknown': 'Неясно',
}


def _normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').casefold())


def _collect_signals(
    items: list[dict],
    families: tuple[tuple[str, int, tuple[str, ...]], ...],
    *,
    suppress_active_in_inactive_context: bool = False,
) -> tuple[dict[str, float], dict[str, list[dict]]]:
    scores: dict[str, float] = defaultdict(float)
    signals: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        title = _normalize(str(item.get('title') or ''))
        snippet = _normalize(str(item.get('snippet') or ''))
        blob = f'{title} {snippet}'.strip()
        if not blob:
            continue
        url = str(item.get('url') or '')
        inactive_context = suppress_active_in_inactive_context and any(
            cue in blob for cue in _CONDITION_INACTIVE_CONTEXT
        )
        for level, weight, terms in families:
            if inactive_context and level == 'active':
                continue
            for term in terms:
                needle = term.casefold().strip()
                if not needle or needle not in blob:
                    continue
                in_title = needle in title
                hit_weight = weight * (1.6 if in_title else 1.0)
                scores[level] += hit_weight
                bucket = signals[level]
                if not any(row['term'] == term and row['url'] == url for row in bucket):
                    bucket.append({
                        'term': term.strip(),
                        'url': url[:2000],
                        'title': str(item.get('title') or '')[:300],
                        'in_title': in_title,
                    })
    return scores, signals


def _pick_level(
    scores: dict[str, float],
    signals: dict[str, list[dict]],
    order: tuple[str, ...],
    *,
    prefer_abandoned: bool = False,
) -> tuple[str, str, list[dict]]:
    if not scores:
        return 'unknown', 'low', []
    # Urbex prior: when both «работает» noise and abandonment cues fire, trust ruin.
    if prefer_abandoned:
        abandoned = scores.get('abandoned', 0)
        active = scores.get('active', 0)
        if abandoned > 0 and active > 0 and abandoned >= active * 0.5:
            scores = dict(scores)
            scores['active'] = 0
    best = max(order, key=lambda level: (scores.get(level, 0), -order.index(level)))
    best_score = scores.get(best, 0)
    if best_score <= 0:
        return 'unknown', 'low', []
    runner = max((scores.get(level, 0) for level in order if level != best), default=0)
    if best_score >= 6 and best_score >= runner * 1.4:
        confidence = 'high'
    elif best_score >= 3:
        confidence = 'medium'
    else:
        confidence = 'low'
    examples = sorted(
        signals.get(best, []),
        key=lambda row: (not row['in_title'], row['term']),
    )[:5]
    return best, confidence, examples


def assess_osint_items(items: list[dict]) -> dict:
    items = [item for item in items
             if not is_vk_group_url(str(item.get('url') or ''))
             and not is_direct_image_url(str(item.get('url') or ''))]
    security_scores, security_signals = _collect_signals(items, _SECURITY)
    condition_scores, condition_signals = _collect_signals(
        items, _CONDITION, suppress_active_in_inactive_context=True,
    )

    security_level, security_confidence, security_examples = _pick_level(
        security_scores, security_signals, ('high', 'medium', 'low'),
    )
    condition_level, condition_confidence, condition_examples = _pick_level(
        condition_scores,
        condition_signals,
        ('demolished', 'abandoned', 'active'),
        prefer_abandoned=True,
    )

    security_label = _SECURITY_LABELS[security_level]
    condition_label = _CONDITION_LABELS[condition_level]
    if security_level == 'unknown' and condition_level == 'unknown':
        summary = 'По открытым источникам явных сигналов об охране и состоянии не найдено.'
    else:
        summary = f'Охраняемость: {security_label}. Состояние: {condition_label}.'

    return {
        'security': {
            'level': security_level,
            'label': security_label,
            'confidence': security_confidence,
            'signals': security_examples,
        },
        'condition': {
            'level': condition_level,
            'label': condition_label,
            'confidence': condition_confidence,
            'signals': condition_examples,
        },
        'summary': summary,
        'disclaimer': (
            'Эвристика по заголовкам и сниппетам открытых источников. '
            'Не заменяет проверку на месте и может устареть.'
        ),
    }
