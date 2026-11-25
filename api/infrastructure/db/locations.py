"""Suggest geographic address components by prefix from the public catalog.

Bounds describe the catalog's places, not official administrative boundaries.
No external geocoder, hardcoded city list or fuzzy surname matching is used.
"""
import re
from sqlalchemy import select, text
from urbex_shared.catalog import published_filter
from .models import Place

NON_LOCATION = re.compile(r'\b(улица|ул\.|проспект|переулок|шоссе|проезд|набережная|тупик|площадь|храм|церковь|усадьба|завод|фабрика|парк|санаторий|лагерь)\b', re.I)


def normalize(value):
    value = value.strip().lower().replace('ё', 'е')
    return re.sub(r'^(город\s+|г\.\s*)', '', value)


def component_filter(value, prefix=False):
    comparison = "starts_with(component, :locality)" if prefix else "component = :locality"
    return text(r"""EXISTS (SELECT 1 FROM (
        SELECT regexp_replace(trim(part), '^(город\s+|г\.\s*)', '') AS component
        FROM regexp_split_to_table(lower(replace(
            coalesce(nullif(full_address,''),region), 'ё','е')), '\s*,\s*') AS part
    ) address_parts WHERE """ + comparison + ")").bindparams(locality=normalize(value))


def resolve_locations(session, query):
    term = normalize(query)
    if len(term) < 2 or not any(c.isalpha() for c in term) or NON_LOCATION.search(term):
        return {'items': []}
    rows = session.execute(select(Place.full_address, Place.region, Place.latitude, Place.longitude).where(
        published_filter(Place), component_filter(term, prefix=True),
        Place.latitude.between(-85,85), Place.longitude.between(-180,180),
    )).mappings()
    groups = {}
    for row in rows:
        parts = [p.strip() for p in (row['full_address'] or row['region']).split(',')]
        normalized = [normalize(p) for p in parts]
        for position, candidate in enumerate(normalized):
            if not candidate.startswith(term) or NON_LOCATION.search(candidate):
                continue
            tail = parts[position+1:]
            # A building name preceding a street is not a city/area name.
            if any(NON_LOCATION.search(part) for part in tail):
                continue
            scope = [p for p in tail if not p.isdigit() and 'федеральный округ' not in p.lower()]
            key = (candidate, *(normalize(p) for p in scope))
            lon, lat = float(row['longitude']), float(row['latitude'])
            if key not in groups:
                label = ', '.join([parts[position], *scope])
                groups[key] = {'name':parts[position], 'label':label, 'query':candidate,
                               'bbox':[lon,lat,lon,lat], 'count':0, 'source':'catalog'}
            group = groups[key]
            group['count'] += 1
            b = group['bbox']
            group['bbox'] = [min(b[0],lon),min(b[1],lat),max(b[2],lon),max(b[3],lat)]
    items = sorted(groups.values(), key=lambda g: (g['query'] != term, -g['count'],g['label']))
    for group in items:
        west,south,east,north = group['bbox']
        group['bbox'] = [max(-180,west-.003),max(-85,south-.003),min(180,east+.003),min(85,north+.003)]
    return {'items':items[:20]}
