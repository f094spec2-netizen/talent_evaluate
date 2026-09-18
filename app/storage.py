import hashlib
import os
import re
import tempfile
from pathlib import Path

import boto3


class Storage:
    def __init__(self, settings):
        self.settings = settings
        self.client = None
        if settings.storage_backend == "s3":
            self.client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
                aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
                region_name=settings.s3_region,
            )

    def put(self, company: str, content: bytes) -> tuple[str, str]:
        digest = hashlib.sha256(content).hexdigest()
        scope = hashlib.sha256(company.encode()).hexdigest()[:32]
        key = f"raw/{scope}/{digest}"
        if self.client:
            self.client.put_object(
                Bucket=self.settings.s3_bucket_name,
                Key=key,
                Body=content,
                ContentType="application/octet-stream",
            )
        else:
            path = self.path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic replacement prevents a crashed write exposing a truncated shared object.
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temp_path = stream.name
                stream.write(content)
            try:
                os.replace(temp_path, path)
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
        return key, digest

    def path(self, key: str) -> Path:
        if not re.fullmatch(r"raw/[a-f0-9]{32}/[a-f0-9]{64}", key):
            raise ValueError("Invalid storage key")
        return self.settings.local_storage_path.resolve() / key

    def get(self, key: str) -> bytes:
        self.path(key)  # Validate keys for both storage providers.
        if self.client:
            response = self.client.get_object(Bucket=self.settings.s3_bucket_name, Key=key)
            with response["Body"] as body:
                content = body.read(self.settings.max_upload_bytes + 1)
        else:
            with self.path(key).open("rb") as stream:
                content = stream.read(self.settings.max_upload_bytes + 1)
        if len(content) > self.settings.max_upload_bytes:
            raise ValueError("Stored object exceeds upload limit")
        if hashlib.sha256(content).hexdigest() != key.rsplit("/", 1)[1]:
            raise ValueError("Stored object checksum mismatch")
        return content
