import pytest

from idempotency_agent.curl_parser import CurlParseError, parse_curl

pytestmark = pytest.mark.unit


def test_basic_post_with_header_and_body():
    result = parse_curl(
        'curl -X POST https://api.example.com/orders '
        '-H "Content-Type: application/json" '
        '-d \'{"product_id": "abc", "qty": 1}\''
    )
    assert result["method"] == "POST"
    assert result["url"] == "https://api.example.com/orders"
    assert result["headers"]["Content-Type"] == "application/json"
    assert result["body"] == {"product_id": "abc", "qty": 1}


def test_multiline_curl_with_backslash():
    curl = (
        "curl -X POST https://api.example.com/pay \\\n"
        "  -H 'Idempotency-Key: key-001' \\\n"
        "  -H 'Authorization: Bearer tok123' \\\n"
        "  -d '{\"amount\": 100}'"
    )
    result = parse_curl(curl)
    assert result["method"] == "POST"
    assert result["headers"]["Idempotency-Key"] == "key-001"
    assert result["headers"]["Authorization"] == "Bearer tok123"
    assert result["body"] == {"amount": 100}


def test_get_request_no_body():
    result = parse_curl("curl https://api.example.com/users")
    assert result["method"] == "GET"
    assert result["url"] == "https://api.example.com/users"
    assert result["body"] is None


def test_implicit_post_from_data_flag():
    result = parse_curl('curl https://api.example.com/orders -d \'{"x":1}\'')
    assert result["method"] == "POST"


def test_data_raw_flag():
    result = parse_curl("curl -X POST https://x.com/api --data-raw '{\"k\":\"v\"}'")
    assert result["body"] == {"k": "v"}


def test_compressed_and_silent_flags_ignored():
    result = parse_curl(
        "curl --compressed --silent -X GET https://api.example.com/items"
    )
    assert result["method"] == "GET"
    assert result["url"] == "https://api.example.com/items"


def test_missing_url_raises():
    with pytest.raises(CurlParseError, match="URL"):
        parse_curl("curl -X POST -H 'Content-Type: application/json'")


def test_not_curl_raises():
    with pytest.raises(CurlParseError, match="curl"):
        parse_curl("wget https://example.com")


def test_non_json_body_kept_as_string():
    result = parse_curl("curl -X POST https://x.com -d 'plain text body'")
    assert result["body"] == "plain text body"
