import os
import platform
from io import BytesIO

from google.cloud import storage
from google.oauth2 import service_account
from fastapi.concurrency import run_in_threadpool
from ..utils.logger import logger


class GcsOss:

    def __init__(self):
        self.credentials = service_account.Credentials.from_service_account_file(
            os.getenv("GSC_CREDENTIALS"))
        self.bucket_name = os.getenv("GSC_BUCKET_NAME")
        self.client = storage.Client(credentials=self.credentials)
        self.bucket = self.client.bucket(self.bucket_name)
        self.project_id = os.getenv("GSC_PROJECT_ID")
        self.location = os.getenv("GSC_LOCATION")

    def _upload_file_sync(self, file_path, file_name):
        """
        上传文件到指定的 GCS bucket 路径下。

        :param bucket_name: GCS 中的 bucket 名称
        :param source_file_path: 本地文件路径
        :param destination_blob_path: GCS 中的目标路径（包括文件名）
        """
        blob = self.bucket.blob(file_name)

        blob.upload_from_filename(file_path)

        # 设置公开访问（可选）
        # blob.make_public()

        # print(f"上传成功: gs://{self.bucket_name}/{destination_blob_path}")
        # print(f"公开访问链接: {blob.public_url}")
        return blob.public_url

    async def upload_file_public_read(self, file_path, file_name):
        return await run_in_threadpool(self._upload_file_sync, file_path, file_name)

    def _upload_byte_sync(self, file: bytes, file_name: str,
                          content_type: str = "application/octet-stream"):
        """
        上传字节流到 Google Cloud Storage

        :param bucket_name: GCS bucket 名称
        :param byte_data: 需要上传的字节流数据
        :param destination_blob_path: GCS 中的路径（包括文件名）
        :param content_type: 上传内容的 MIME 类型
        """
        blob = self.bucket.blob(file_name)

        # 包装成 BytesIO 流上传
        try:
            byte_stream = BytesIO(file)
        except Exception as e:
            byte_stream = file
        blob.upload_from_file(byte_stream, content_type=content_type)
        # blob.make_public()  # 设置公开访问

        # print(f"上传成功: gs://{self.bucket_name}/{destination_blob_path}")
        # print(f"公开链接: {blob.public_url}")
        return blob.public_url

    async def og_upload_file_byte_public_read(self, file, file_name):
        return await run_in_threadpool(self._upload_byte_sync, file, file_name)