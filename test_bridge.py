#!/usr/bin/env python3
"""Quick smoke tests for onebot_bridge parsing utilities."""

from onebot_bridge import extract_text_and_images, extract_response_media


def test_cq_code_string():
    text, imgs, at = extract_text_and_images("[CQ:at,qq=12345] 你好世界", "12345")
    assert text == "你好世界", f"text={text!r}"
    assert at is True
    assert imgs == []
    print("  ✓ CQ code string parsing")


def test_cq_no_at():
    text, imgs, at = extract_text_and_images("普通消息", "12345")
    assert text == "普通消息"
    assert at is False
    print("  ✓ No @mention detection")


def test_cq_image():
    msg = "看这个[CQ:image,file=abc.jpg,url=https://example.com/1.jpg]"
    text, imgs, at = extract_text_and_images(msg, "12345")
    assert text == "看这个"
    assert imgs == ["https://example.com/1.jpg"]
    assert at is False
    print("  ✓ CQ image extraction")


def test_array_format():
    msg = [
        {"type": "at", "data": {"qq": "12345"}},
        {"type": "text", "data": {"text": " 帮我看看这张图"}},
        {"type": "image", "data": {"url": "https://example.com/1.jpg"}},
    ]
    text, imgs, at = extract_text_and_images(msg, "12345")
    assert text == "帮我看看这张图", f"text={text!r}"
    assert at is True
    assert imgs == ["https://example.com/1.jpg"]
    print("  ✓ Array format parsing")


def test_response_media_markdown():
    resp = "这是结果\n![chart](https://img.com/a.png)\n完毕"
    cleaned, urls = extract_response_media(resp)
    assert "https://img.com/a.png" in urls
    assert "![" not in cleaned
    print("  ✓ Markdown image extraction")


def test_response_media_tag():
    resp = "文件已生成 MEDIA:/tmp/output.png 请查看"
    cleaned, urls = extract_response_media(resp)
    assert "/tmp/output.png" in urls
    assert "MEDIA:" not in cleaned
    print("  ✓ MEDIA: tag extraction")


def test_at_all():
    text, imgs, at = extract_text_and_images("[CQ:at,qq=all] 通知", "12345")
    assert at is True
    assert text == "通知"
    print("  ✓ @all detection")


if __name__ == "__main__":
    print("Running onebot_bridge tests...")
    test_cq_code_string()
    test_cq_no_at()
    test_cq_image()
    test_array_format()
    test_response_media_markdown()
    test_response_media_tag()
    test_at_all()
    print("\n✅ All tests passed!")
