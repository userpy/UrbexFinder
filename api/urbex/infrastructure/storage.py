from io import BytesIO
import warnings
import boto3
from PIL import Image, UnidentifiedImageError
from urbex.domain.rules import DomainError

MAX_PHOTO_BYTES = 8 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000


def sanitize_photo(data: bytes) -> bytes:
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise DomainError('Размер фотографии: от 1 байта до 8 МБ', 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as im:
                if im.format not in {'JPEG', 'PNG', 'WEBP'} or getattr(im, 'n_frames', 1) != 1:
                    raise DomainError('Разрешены только статические JPEG, PNG и WebP')
                im.load()
                im = im.convert('RGB')
                im.thumbnail((2400, 2400))
                out = BytesIO()
                im.save(out, format='JPEG', quality=88)  # Strip metadata, executable/polyglot content and original names.
                return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise DomainError('Некорректное или слишком большое изображение')


class S3Storage:
    def __init__(self, config):
        from .telegram import TelegramPhotos
        self.telegram = TelegramPhotos(config.telegram_bot_token)
        self.bucket = config.s3_bucket
        self.client = boto3.client('s3', endpoint_url=config.s3_endpoint, aws_access_key_id=config.s3_access_key,
                                   aws_secret_access_key=config.s3_secret_key, region_name='us-east-1')

    def put(self, key, data):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType='image/jpeg')

    def get(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)['Body'].read()

    def get_telegram(self, file_id):
        return self.telegram.get(file_id)
