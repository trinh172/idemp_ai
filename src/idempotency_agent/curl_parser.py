"""
curl_parser — parse chuỗi curl command thành dict {method, url, headers, body}.

Hỗ trợ: -X, -H/--header, -d/--data/--data-raw/--data-binary,
         -u/--user (basic auth), --compressed, -L, -k, v.v.
"""
import base64
import json
import re
import shlex


class CurlParseError(ValueError):
    """Không thể parse curl command."""


def parse_curl(curl_str: str) -> dict:
    """
    Parse curl command string → {method, url, headers, body}.
    body là dict nếu JSON hợp lệ, string nếu không parse được, None nếu không có.
    Raise CurlParseError nếu không phải curl hoặc thiếu URL.
    """
    # Chuẩn hóa: bỏ line continuation, strip
    normalized = re.sub(r"\\\s*\n\s*", " ", curl_str).strip()

    try:
        tokens = shlex.split(normalized)
    except ValueError as exc:
        raise CurlParseError(f"Không parse được chuỗi: {exc}") from exc

    if not tokens or tokens[0].lower() != "curl":
        raise CurlParseError("Input phải bắt đầu bằng 'curl'")

    method = None  # xác định sau khi biết có -d không
    url: str | None = None
    headers: dict[str, str] = {}
    body_raw: str | None = None

    # Flags có 1 argument đi kèm (bỏ qua giá trị)
    _skip_one = {
        "--connect-timeout", "--max-time", "-m", "--retry",
        "--output", "-o", "--user-agent", "-A", "--referer", "-e",
        "--cert", "--key", "--cacert", "--proxy", "-x",
        "--interface", "--resolve", "--dns-servers",
    }
    # Flags boolean (bỏ qua, không có argument)
    _skip_zero = {
        "--compressed", "--silent", "-s", "--verbose", "-v",
        "--location", "-L", "--insecure", "-k", "--no-keepalive",
        "--http1.1", "--http2", "--ipv4", "-4", "--ipv6", "-6",
        "--fail", "-f", "--include", "-i", "--head", "-I",
        "--no-buffer", "-N", "--digest", "--ntlm", "--anyauth",
        "--globoff", "-g", "--remote-name", "-O",
    }

    i = 1
    while i < len(tokens):
        tok = tokens[i]

        # Method
        if tok in ("-X", "--request"):
            method = tokens[i + 1].upper()
            i += 2

        # Header
        elif tok in ("-H", "--header"):
            raw = tokens[i + 1]
            if ":" in raw:
                k, v = raw.split(":", 1)
                headers[k.strip()] = v.strip()
            i += 2

        # Body
        elif tok in ("-d", "--data", "--data-raw", "--data-binary", "--data-urlencode"):
            val = tokens[i + 1]
            body_raw = val[1:] if val.startswith("@") else val  # @ = file, bỏ @
            if method is None:
                method = "POST"
            i += 2

        # Basic auth → Authorization header
        elif tok in ("-u", "--user"):
            creds = base64.b64encode(tokens[i + 1].encode()).decode()
            headers["Authorization"] = f"Basic {creds}"
            i += 2

        # Skip flags with value
        elif tok in _skip_one:
            i += 2

        # Skip boolean flags
        elif tok in _skip_zero:
            i += 1

        # Unknown --flag=value
        elif tok.startswith("--") and "=" in tok:
            i += 1

        # Unknown -flag with value (single char)
        elif re.match(r"^-[a-zA-Z]$", tok) and i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
            i += 2

        # URL (không phải flag)
        elif not tok.startswith("-"):
            if url is None:
                url = tok
            i += 1

        else:
            i += 1

    if not url:
        raise CurlParseError("Không tìm thấy URL trong curl command")

    if method is None:
        method = "POST" if body_raw else "GET"

    # Parse body
    body = None
    if body_raw:
        try:
            body = json.loads(body_raw)
        except (json.JSONDecodeError, ValueError):
            body = body_raw  # giữ nguyên string

    return {
        "method": method,
        "url": url,
        "headers": headers,
        "body": body,
    }
