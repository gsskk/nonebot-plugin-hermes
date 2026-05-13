"""ImageFetcher 单元测试。"""

from __future__ import annotations

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nonebot_plugin_hermes.core.message_buffer import BufferedMessage
from nonebot_plugin_hermes.core.storage.image_cache import ImageCache
from nonebot_plugin_hermes.core.storage.image_fetcher import ImageFetcher
from nonebot_plugin_hermes.core.storage.message_store import MessageStore


@pytest.fixture
def store_and_cache(tmp_path):
    store = MessageStore(db_path=tmp_path / "m.db")
    cache = ImageCache(cache_dir=tmp_path / "imgs", quota_bytes=10 * 1024 * 1024)
    yield store, cache
    store.close()


def _make_async_client_factory(response_mock):
    """构造 patch httpx.AsyncClient 的工厂,async ctx + .get() 都 mock 出来。"""
    client_mock = MagicMock()
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=None)
    if isinstance(response_mock, Exception):
        client_mock.get = AsyncMock(side_effect=response_mock)
    else:
        client_mock.get = AsyncMock(return_value=response_mock)

    def factory(*args, **kwargs):
        return client_mock

    return factory, client_mock


@pytest.mark.asyncio
async def test_fetcher_success_updates_store_and_cache(store_and_cache):
    store, cache = store_and_cache
    msg = BufferedMessage(
        ts=100,
        adapter="ob11",
        group_id="g1",
        user_id="u1",
        nickname="u1",
        content="hi",
        image_urls=["http://x.test/a.jpg"],
    )
    store.append(msg)

    fake_bytes = b"\xff\xd8\xff\xe0" + b"FAKE_JPG" * 16
    response = MagicMock()
    response.status_code = 200
    response.content = fake_bytes
    response.headers = {"content-type": "image/jpeg"}
    response.raise_for_status = MagicMock(return_value=None)

    factory, _client = _make_async_client_factory(response)

    fetcher = ImageFetcher(store=store, cache=cache, timeout_s=5, max_attempts=2)
    with patch(
        "nonebot_plugin_hermes.core.storage.image_fetcher.httpx.AsyncClient",
        side_effect=factory,
    ):
        await fetcher.start()
        fetcher.submit(msg.id, ["http://x.test/a.jpg"])
        # 等 worker 消费
        for _ in range(20):
            if fetcher.queue_size() == 0:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.05)  # 给 update_image_sha 时间提交
        await fetcher.stop()

    expected_sha = hashlib.sha256(fake_bytes).hexdigest()
    metas = store.get_message_images_meta([msg.id])
    assert metas[msg.id][0]["sha256"] == expected_sha
    assert metas[msg.id][0]["mime_type"] == "image/jpeg"
    payload = cache.get_bytes(expected_sha)
    assert payload is not None
    bytes_, mime = payload
    assert bytes_ == fake_bytes
    assert mime == "image/jpeg"


@pytest.mark.asyncio
async def test_fetcher_failure_after_max_attempts_leaves_sha_null(store_and_cache):
    store, cache = store_and_cache
    msg = BufferedMessage(
        ts=100,
        adapter="ob11",
        group_id="g1",
        user_id="u1",
        nickname="u1",
        content="hi",
        image_urls=["http://x.test/a.jpg"],
    )
    store.append(msg)

    factory, _client = _make_async_client_factory(Exception("simulated network error"))

    fetcher = ImageFetcher(store=store, cache=cache, timeout_s=1, max_attempts=2)
    with patch(
        "nonebot_plugin_hermes.core.storage.image_fetcher.httpx.AsyncClient",
        side_effect=factory,
    ):
        await fetcher.start()
        fetcher.submit(msg.id, ["http://x.test/a.jpg"])
        for _ in range(30):
            if fetcher.queue_size() == 0:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)
        await fetcher.stop()

    metas = store.get_message_images_meta([msg.id])
    assert metas[msg.id][0]["sha256"] is None
    assert metas[msg.id][0]["mime_type"] is None


@pytest.mark.asyncio
async def test_fetcher_queue_overflow_drops_oldest(store_and_cache):
    """队列上限达到时,新入队会挤掉最老的任务。"""
    store, cache = store_and_cache
    fetcher = ImageFetcher(store=store, cache=cache, timeout_s=1, max_attempts=1, queue_max=3)
    # 不 start worker,队列堆积观察
    for i in range(10):
        fetcher.submit(i, [f"http://x.test/{i}.jpg"])
    # 队列上限是 3,前 7 个应被丢
    assert fetcher.queue_size() == 3


@pytest.mark.asyncio
async def test_fetcher_non_image_content_type_skipped(store_and_cache):
    """content-type 不是 image/* 且字节头也不像图(html)时,不写 cache。"""
    store, cache = store_and_cache
    msg = BufferedMessage(
        ts=100,
        adapter="ob11",
        group_id="g1",
        user_id="u1",
        nickname="u1",
        content="hi",
        image_urls=["http://x.test/a.jpg"],
    )
    store.append(msg)

    response = MagicMock()
    response.status_code = 200
    response.content = b"<html></html>"
    response.headers = {"content-type": "text/html"}
    response.raise_for_status = MagicMock(return_value=None)

    factory, _client = _make_async_client_factory(response)

    fetcher = ImageFetcher(store=store, cache=cache, timeout_s=1, max_attempts=2)
    with patch(
        "nonebot_plugin_hermes.core.storage.image_fetcher.httpx.AsyncClient",
        side_effect=factory,
    ):
        await fetcher.start()
        fetcher.submit(msg.id, ["http://x.test/a.jpg"])
        for _ in range(20):
            if fetcher.queue_size() == 0:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.05)
        await fetcher.stop()

    metas = store.get_message_images_meta([msg.id])
    assert metas[msg.id][0]["sha256"] is None


@pytest.mark.asyncio
async def test_fetcher_accepts_octet_stream_when_bytes_sniff_image(store_and_cache):
    """Telegram CDN 常返回 application/octet-stream;只要字节头匹配 JPEG/PNG/WebP/GIF
    魔数,应该接受并按嗅探到的真 MIME 入 cache。这是 Telegram 路径能跑通的关键。"""
    store, cache = store_and_cache
    msg = BufferedMessage(
        ts=100,
        adapter="telegram",
        group_id="g1",
        user_id="u1",
        nickname="u1",
        content="hi",
        image_urls=["https://api.telegram.org/file/bot.../photo.jpg"],
    )
    store.append(msg)

    # 真 JPEG 字节头(SOI 0xFFD8 + APP0 0xFFE0),后面任意填充
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"FAKE_JPEG_PAYLOAD" * 8
    response = MagicMock()
    response.status_code = 200
    response.content = jpeg_bytes
    # 关键:Content-Type 是 octet-stream,旧代码会拒收
    response.headers = {"content-type": "application/octet-stream"}
    response.raise_for_status = MagicMock(return_value=None)

    factory, _client = _make_async_client_factory(response)

    fetcher = ImageFetcher(store=store, cache=cache, timeout_s=1, max_attempts=2)
    with patch(
        "nonebot_plugin_hermes.core.storage.image_fetcher.httpx.AsyncClient",
        side_effect=factory,
    ):
        await fetcher.start()
        fetcher.submit(msg.id, msg.image_urls)
        for _ in range(20):
            if fetcher.queue_size() == 0:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.05)
        await fetcher.stop()

    metas = store.get_message_images_meta([msg.id])
    # sha 应该写入,mime 应该是嗅探出的 image/jpeg(不是 octet-stream)
    assert metas[msg.id][0]["sha256"] is not None
    assert metas[msg.id][0]["mime_type"] == "image/jpeg"
    payload = cache.get_bytes(metas[msg.id][0]["sha256"])
    assert payload is not None
    bytes_back, mime_back = payload
    assert bytes_back == jpeg_bytes
    assert mime_back == "image/jpeg"


def test_sniff_image_mime_recognizes_known_formats():
    """字节嗅探:JPEG/PNG/GIF/WebP 各家魔数都识别。"""
    from nonebot_plugin_hermes.core.storage.image_fetcher import _sniff_image_mime

    assert _sniff_image_mime(b"\xff\xd8\xff\xe0xxx") == "image/jpeg"
    assert _sniff_image_mime(b"\x89PNG\r\n\x1a\n more") == "image/png"
    assert _sniff_image_mime(b"GIF87a more bytes") == "image/gif"
    assert _sniff_image_mime(b"GIF89a") == "image/gif"
    # WebP: RIFF........WEBP....
    assert _sniff_image_mime(b"RIFF\x00\x00\x00\x00WEBP_____") == "image/webp"
    # 非图字节
    assert _sniff_image_mime(b"<html><body>") is None
    assert _sniff_image_mime(b"") is None
