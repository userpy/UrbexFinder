"""Read place exports without importing foreign IDs, ratings or moderation state."""
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path


def read_places(path):
    csv.field_size_limit(10 * 1024 * 1024)
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        header = stream.readline()
        stream.seek(0)
        reader = csv.DictReader(stream, delimiter=';' if header.count(';') > header.count(',') else ',')
        fields = set(reader.fieldnames or [])
        if 'name' not in fields or not ({'latitude','longitude'} <= fields or {'lat','lon'} <= fields):
            raise ValueError('CSV requires name, latitude, longitude (or lat, lon) columns')
        for row in reader:
            line = reader.line_num
            try:
                name = (row.get('name') or '').strip()
                lat = Decimal((row.get('latitude') or row.get('lat') or '').strip().replace(',','.'))
                lon = Decimal((row.get('longitude') or row.get('lon') or '').strip().replace(',','.'))
                if not name or not lat.is_finite() or not lon.is_finite() or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError('name or coordinates')
                yield dict(name=name, description=row.get('description') or '', type=row.get('type') or 'Point',
                           latitude=lat.quantize(Decimal('.000001')), longitude=lon.quantize(Decimal('.000001')),
                           category=(row.get('category') or 'Другое').strip() or 'Другое',
                           full_address=(row.get('full_address') or row.get('address') or '').strip())
            except (InvalidOperation, ValueError) as error:
                raise ValueError(f'Invalid CSV record at line {line}: {error}') from error
