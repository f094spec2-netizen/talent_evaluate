import re
import time
from urllib.parse import quote

import httpx

from app.parsers import InvalidFile


class TelegramError(RuntimeError):
    pass


class Telegram:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.token = settings.telegram_bot_token.get_secret_value()
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)

    def call(self, method, payload):
        if not self.token:
            raise TelegramError("TELEGRAM_NOT_CONFIGURED")
        try:
            response = self.client.post(
                f"https://api.telegram.org/bot{self.token}/{method}", json=payload
            )
            response.raise_for_status()
            value = response.json()
            if not value.get("ok"):
                raise TelegramError("TELEGRAM_API_ERROR")
            return value["result"]
        except (httpx.HTTPError, ValueError, KeyError):
            # HTTP exception strings contain the token-bearing URL; never propagate them.
            raise TelegramError("TELEGRAM_REQUEST_FAILED") from None

    def download(self, file_id):
        info = self.call("getFile", {"file_id": file_id})
        if info.get("file_size", 0) > self.settings.max_upload_bytes:
            raise InvalidFile("EMPTY_OR_OVERSIZED_FILE")
        path = info.get("file_path", "")
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", path) or path.startswith("/") or ".." in path:
            raise TelegramError("INVALID_TELEGRAM_FILE_PATH")
        chunks, size, started = [], 0, time.monotonic()
        try:
            with self.client.stream(
                "GET", f"https://api.telegram.org/file/bot{self.token}/{quote(path, safe='/')}"
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        raise InvalidFile("EMPTY_OR_OVERSIZED_FILE")
                    if time.monotonic() - started > 60:
                        raise TelegramError("DOWNLOAD_TIME_LIMIT")
                    chunks.append(chunk)
        except httpx.HTTPError:
            raise TelegramError("TELEGRAM_DOWNLOAD_FAILED") from None
        return b"".join(chunks)

    def send(self, chat_id, text):
        self.call("sendMessage", {"chat_id": chat_id, "text": text[:4000]})

    def close(self):
        self.client.close()


def receipt_message(receipt) -> str:
    names = {
        "received": "已收件，等待下载",
        "queued": "已收件，等待解析",
        "normalized": "资料已解析归档（尚未核实个人贡献）",
        "awaiting_confirmation": "已收件，待确认；请核对期间／版本后重新上传",
        "duplicate": "重复提交，未重复计算",
        "rejected": "文件无法处理，请依问题代码修正",
        "processing_failed": "处理失败，需管理员检查并重试",
    }
    result = receipt.result or {}
    parts = [f"收件编号：{receipt.id}", names.get(receipt.status, receipt.status)]
    if result.get("period_start"):
        parts.append(f"期间候选：{result['period_start']} ～ {result['period_end']}")
    if result.get("issues"):
        parts.append("需处理：" + ", ".join(result["issues"]))
    return "\n".join(parts)
