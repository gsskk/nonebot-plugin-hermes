"""异步 HTTP 抓取 worker。

perception 把 (msg_id, urls) submit 进来,内部 single-worker 协程消费;
失败重试至 max_attempts,最终失败时只让 message_images.sha256 留 NULL,
log warning,不抛 —— perception 路径不能因为图抓不到而崩。
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import List, Optional, Tuple

import httpx
from nonebot import logger

from .image_cache import ImageCache
from .message_store import MessageStore


# 图片字节魔数 → 标准 MIME。用于 Telegram CDN 这类返回
# `application/octet-stream` 的源 —— Content-Type 不可信,从字节头识别。
_MAGIC_TO_MIME: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]


def _sniff_image_mime(data: bytes) -> Optional[str]:
    """Return a normalized image MIME if the byte head matches a known magic,
    else None. WebP needs both RIFF header + WEBP at offset 8.
    """
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for magic, mime in _MAGIC_TO_MIME:
        if data.startswith(magic):
            return mime
    return None


class ImageFetcher:
    """单 worker 协程消费 queue;失败重试 max_attempts 次。

    queue 用 collections.deque 而非 asyncio.Queue,因为我们需要在 overflow 时
    丢老元素(asyncio.Queue 没有这能力)。submit() 必须非阻塞 / 同步可调,
    perception handler 不应 await。
    """

    def __init__(
        self,
        *,
        store: MessageStore,
        cache: ImageCache,
        timeout_s: int = 10,
        max_attempts: int = 2,
        queue_max: int = 1000,
    ) -> None:
        self._store = store
        self._cache = cache
        self._timeout = timeout_s
        self._max_attempts = max(1, max_attempts)
        self._queue_max = queue_max
        self._queue: deque[Tuple[int, int, str]] = deque()
        self._wake: asyncio.Event = asyncio.Event()
        self._stop: asyncio.Event = asyncio.Event()
        self._worker: Optional[asyncio.Task] = None

    def submit(self, message_id: int, urls: List[str]) -> None:
        """把每张图作为单独任务入 queue。overflow 时丢最老,log warning。"""
        for idx, url in enumerate(urls):
            while len(self._queue) >= self._queue_max:
                dropped = self._queue.popleft()
                logger.warning(f"[image_fetcher] queue full, dropped task {dropped}")
            self._queue.append((message_id, idx, url))
        self._wake.set()

    def queue_size(self) -> int:
        return len(self._queue)

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._stop.clear()
        self._worker = asyncio.create_task(self._run(), name="hermes-image-fetcher")

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._stop.set()
        self._wake.set()
        try:
            await asyncio.wait_for(self._worker, timeout=5)
        except asyncio.TimeoutError:
            self._worker.cancel()
            logger.warning("[image_fetcher] worker did not stop within 5s; cancelled")
        self._worker = None
        if self._queue:
            logger.info(f"[image_fetcher] {len(self._queue)} pending tasks dropped on shutdown")
        self._queue.clear()

    async def _run(self) -> None:
        while not self._stop.is_set():
            if not self._queue:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=1)
                except asyncio.TimeoutError:
                    continue
            if self._stop.is_set():
                break
            if not self._queue:
                continue
            message_id, idx, url = self._queue.popleft()
            await self._fetch_one(message_id, idx, url)

    async def _fetch_one(self, message_id: int, idx: int, url: str) -> None:
        last_err: Optional[str] = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    bytes_ = resp.content
                    mime = self._resolve_mime(resp.headers.get("content-type"), bytes_)
                    if mime is None:
                        # Content-Type 不是 image,字节头也不是已知图片格式 → 真不是图
                        last_err = (
                            f"non-image: ct={resp.headers.get('content-type')!r} "
                            f"head={bytes_[:16].hex() if bytes_ else 'empty'}"
                        )
                        break
                    sha = self._cache.put(bytes_, mime)
                    self._store.update_image_sha(message_id, idx, sha, mime)
                    return
            except Exception as exc:
                last_err = repr(exc)
                if attempt < self._max_attempts:
                    await asyncio.sleep(0.2 * attempt)  # 简单线性退避
        logger.warning(
            f"[image_fetcher] fetch failed m={message_id} idx={idx} url={url[:80]} "
            f"after {self._max_attempts} attempts: {last_err}"
        )

    @staticmethod
    def _resolve_mime(content_type: Optional[str], bytes_: bytes) -> Optional[str]:
        """信任顺序:
        1. Content-Type 是 image/* → 直接用
        2. Content-Type 是 application/octet-stream(Telegram CDN 典型行为)
           或缺失 → 嗅探字节魔数
        3. 字节嗅探命中已知图片格式 → 用嗅探结果
        4. 都不是 → 返回 None,表示真不是图
        """
        ct = (content_type or "").split(";", 1)[0].strip().lower()
        if ct.startswith("image/"):
            return ct
        # octet-stream / 缺失 / 其他 → 字节嗅探
        sniffed = _sniff_image_mime(bytes_)
        return sniffed
