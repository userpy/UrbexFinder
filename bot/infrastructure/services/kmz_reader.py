import asyncio
import zipfile
import xml.etree.ElementTree as ET

from infrastructure.db.PgDb import AsyncDatabase

KML_NS = {'kml': 'http://www.opengis.net/kml/2.2'}


class Placemark:
    def __init__(self, element: ET.Element, category: str):
        self.element = element
        self.category = category
        self.type = self._get_type()
        self.name = self._get_text('name')
        self.description = self._get_text('description')
        self.coordinates = self._get_coordinates()
        self.latitude = self.coordinates[0][1] if self.coordinates else None
        self.longitude = self.coordinates[0][0] if self.coordinates else None
        self.location_name = None  # Здесь будет название населённого пункта

    def _get_type(self):
        if self.element.find('kml:Point', KML_NS) is not None:
            return 'Point'
        if self.element.find('kml:LineString', KML_NS) is not None:
            return 'LineString'
        if self.element.find('kml:Polygon', KML_NS) is not None:
            return 'Polygon'
        if self.element.find('kml:MultiGeometry', KML_NS) is not None:
            return 'MultiGeometry'
        return 'Unknown'

    def _get_text(self, tag):
        el = self.element.find(f'kml:{tag}', KML_NS)
        return el.text.strip() if el is not None and el.text else None

    def _get_coordinates(self):
        coords_el = self.element.find('.//kml:coordinates', KML_NS)
        if coords_el is None or not coords_el.text:
            return []
        coords = []
        for part in coords_el.text.strip().split():
            lon, lat, *rest = part.split(',')
            alt = float(rest[0]) if rest else None
            coords.append((float(lon), float(lat), alt))
        return coords

    async def save_to_db(self, db: AsyncDatabase):
        # Сначала получаем название населённого пункта
        if db is not None:
            await db.places.add_or_update_place(
                name=self.name,
                description=self.description,
                type_=self.type,
                latitude=self.latitude,
                longitude=self.longitude,
                category=self.category
            )

class KmzReader:
    def __init__(
        self,
        file_path: str,
        db: AsyncDatabase,
        max_concurrent_writes: int = 5,
    ):
        self.file_path = file_path
        self.db = db
        self.max_concurrent_writes = max(1, max_concurrent_writes)

    async def read(self):
        root = await asyncio.to_thread(self._read_kmz_sync)
        semaphore = asyncio.Semaphore(self.max_concurrent_writes)
        tasks = []

        for folder in root.findall('.//kml:Folder', KML_NS):
            folder_name_el = folder.find('kml:name', KML_NS)
            category = folder_name_el.text if folder_name_el is not None else None

            for placemark_el in folder.findall('.//kml:Placemark', KML_NS):
                placemark = Placemark(placemark_el, category)
                tasks.append(asyncio.create_task(self._save_with_limit(placemark, semaphore)))

        if tasks:
            await asyncio.gather(*tasks)

    async def _save_with_limit(self, placemark: Placemark, semaphore: asyncio.Semaphore):
        async with semaphore:
            await placemark.save_to_db(self.db)

    def _read_kmz_sync(self):
        with zipfile.ZipFile(self.file_path, 'r') as kmz:
            kml_files = [n for n in kmz.namelist() if n.endswith('.kml')]
            if not kml_files:
                raise ValueError("KML файл не найден")

            kml_filename = 'doc.kml' if 'doc.kml' in kml_files else kml_files[0]

            with kmz.open(kml_filename) as kml_file:
                root = ET.parse(kml_file).getroot()
        return root
