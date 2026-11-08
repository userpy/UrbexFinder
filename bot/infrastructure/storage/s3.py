"""S3 operations used by the bot and background workers."""

import asyncio

import boto3

from infrastructure.core.settings import AppSettings


class S3Storage:
    def __init__(self, settings: AppSettings):
        self.settings = settings

    async def delete_object(self, key: str) -> None:
        await asyncio.to_thread(self._delete_object, key)

    def _client(self):
        return boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            region_name="us-east-1",
        )

    def _delete_object(self, key: str) -> None:
        client = self._client()
        try:
            client.delete_object(Bucket=self.settings.s3_bucket, Key=key)
        finally:
            client.close()

    async def get_object(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get_object, key)

    def _get_object(self, key: str) -> bytes:
        client = self._client()
        try:
            body = client.get_object(Bucket=self.settings.s3_bucket, Key=key)['Body']
            try:
                return body.read()
            finally:
                body.close()
        finally:
            client.close()
