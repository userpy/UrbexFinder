"""Optional local BGE-M3 and cross-encoder ranking for OSINT candidates."""
import logging

import httpx

_log = logging.getLogger(__name__)
_MAX_CANDIDATES = 32


def _place_text(place: dict) -> str:
    parts = (
        place.get('name'),
        place.get('category_name') or place.get('category'),
        place.get('full_address'),
        place.get('region'),
        place.get('description'),
    )
    return '\n'.join(str(part).strip() for part in parts if part)[:1500]


def _candidate_text(candidate: dict) -> str:
    parts = (
        candidate.get('title'),
        candidate.get('snippet'),
        candidate.get('url'),
    )
    return '\n'.join(str(part).strip() for part in parts if part)[:2000]


def rank_candidates(endpoint: str, place: dict, candidates: list[dict]) -> list[dict]:
    """Rank without filtering; hard source verification remains authoritative."""
    if not endpoint or not candidates:
        return candidates
    batch = candidates[:_MAX_CANDIDATES]
    documents = [_candidate_text(candidate) for candidate in batch]
    if not any(documents):
        return candidates
    try:
        with httpx.Client(timeout=httpx.Timeout(90, connect=2)) as client:
            response = client.post(
                f'{endpoint.rstrip("/")}/rank',
                json={'query': _place_text(place), 'documents': documents},
            )
            response.raise_for_status()
            scores = response.json()['scores']
        if len(scores) != len(batch):
            raise ValueError('Semantic service returned a mismatched score count')
        ranked = []
        for candidate, score in zip(batch, scores, strict=True):
            ranked.append({
                **candidate,
                'embedding_score': float(score['embedding_score']),
                'reranker_score': float(score['reranker_score']),
            })
        ranked.sort(
            key=lambda row: (
                -row['reranker_score'],
                -row['embedding_score'],
            ),
        )
        return ranked + candidates[len(batch):]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        _log.warning('Local semantic ranking unavailable; keeping search-engine order: %s', exc)
        return candidates
