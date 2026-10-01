from bale import encode_multipart, file_url, method_url, parse_api_response, redact_url
from bale import BaleError


def test_urls_do_not_insert_a_slash_before_the_token():
    assert method_url("123:abc", "sendMessage") == "https://tapi.bale.ai/bot123:abc/sendMessage"
    assert file_url("123:abc", "documents/file.xlsx") == (
        "https://tapi.bale.ai/file/bot123:abc/documents/file.xlsx"
    )
    assert redact_url(method_url("123:abc", "getFile")) == "https://tapi.bale.ai/bot<token>/getFile"


def test_multipart_contains_fields_and_file_bytes():
    body, content_type = encode_multipart(
        [("chat_id", "99"), ("caption", "سلام\nخط دوم")],
        [("document", "sheet.txt", "name\tamount\n".encode(), "text/plain")],
    )
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="chat_id"' in body
    assert b"99" in body
    assert "سلام\nخط دوم".encode() in body
    assert b'filename="sheet.txt"' in body
    assert b"name\tamount\n" in body
    assert body.endswith(b"--\r\n")


def test_parse_telegram_style_envelope():
    result = parse_api_response(200, '{"ok": true, "result": {"message_id": 4}}')
    assert result == {"message_id": 4}
    try:
        parse_api_response(400, '{"ok": false, "description": "bad request"}')
    except BaleError as exc:
        assert "bad request" in str(exc)
        return
    raise AssertionError("expected BaleError")
