import sys
import socket
import ssl
import argparse
import json
import os
import hashlib
import time
import io
from urllib.parse import urlparse, quote_plus, parse_qs

from bs4 import BeautifulSoup

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# file-based HTTP cache
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".go2web_cache")


def _cache_key(url):
    return hashlib.sha256(url.encode()).hexdigest()


def cache_get(url):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, _cache_key(url))
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        max_age = entry.get("max_age", 300)
        if time.time() - entry["timestamp"] > max_age:
            os.remove(path)
            return None
        return entry["headers"], entry["body"]
    except Exception:
        return None


def cache_put(url, headers, body):
    os.makedirs(CACHE_DIR, exist_ok=True)
    max_age = 300
    cc = headers.get("cache-control", "")
    if "no-store" in cc or "no-cache" in cc:
        return
    for part in cc.split(","):
        part = part.strip()
        if part.startswith("max-age="):
            try:
                max_age = int(part.split("=", 1)[1])
            except ValueError:
                pass
    entry = {
        "timestamp": time.time(),
        "max_age": max_age,
        "headers": headers,
        "body": body,
    }
    path = os.path.join(CACHE_DIR, _cache_key(url))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f)


HELP_TEXT = """go2web (request and search)

Usage:
  go2web -u <URL>           Make an HTTP request to the specified URL and print the response
  go2web -s <search-term>   Search the term and print top 10 results
  go2web -h                 Show this help

Examples:
  go2web -u https://example.com
  go2web -s "python programming"
"""


# raw http over tcp sockets
def build_request(host, path, accept="text/html,application/json;q=0.9,*/*;q=0.8"):
    return (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"User-Agent: go2web/1.0\r\n"
        f"Accept: {accept}\r\n"
        f"Accept-Encoding: identity\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )


def recv_all(sock):
    chunks = []
    while True:
        try:
            chunk = sock.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
        except socket.timeout:
            break
    return b"".join(chunks)


def decode_chunked(data):
    result = []
    idx = 0
    while idx < len(data):
        line_end = data.find(b"\r\n", idx)
        if line_end == -1:
            break
        size_str = data[idx:line_end].decode("ascii", errors="replace").strip()
        if not size_str:
            idx = line_end + 2
            continue
        if ";" in size_str:
            size_str = size_str.split(";")[0]
        try:
            chunk_size = int(size_str, 16)
        except ValueError:
            break
        if chunk_size == 0:
            break
        chunk_start = line_end + 2
        chunk_end = chunk_start + chunk_size
        result.append(data[chunk_start:chunk_end])
        idx = chunk_end + 2
    return b"".join(result)


def parse_response(raw):
    header_end = raw.find(b"\r\n\r\n")
    if header_end == -1:
        header_end = raw.find(b"\n\n")
        if header_end == -1:
            return 0, {}, raw.decode("utf-8", errors="replace")
        header_bytes = raw[:header_end]
        body_bytes = raw[header_end + 2:]
    else:
        header_bytes = raw[:header_end]
        body_bytes = raw[header_end + 4:]

    header_text = header_bytes.decode("utf-8", errors="replace")
    lines = header_text.split("\r\n") if "\r\n" in header_text else header_text.split("\n")

    status_line = lines[0]
    try:
        status_code = int(status_line.split(" ", 2)[1])
    except (IndexError, ValueError):
        status_code = 0

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, val = line.split(":", 1)
            headers[key.strip().lower()] = val.strip()

    if headers.get("transfer-encoding", "").lower() == "chunked":
        body_bytes = decode_chunked(body_bytes)

    content_type = headers.get("content-type", "")
    encoding = "utf-8"
    if "charset=" in content_type:
        encoding = content_type.split("charset=")[-1].split(";")[0].strip()

    body = body_bytes.decode(encoding, errors="replace")
    return status_code, headers, body


def http_request(url, max_redirects=10, use_cache=True):
    for _ in range(max_redirects):
        # check cache
        if use_cache:
            cached = cache_get(url)
            if cached:
                print(f"[cache hit] {url}")
                return 200, cached[0], cached[1]

        parsed = urlparse(url)
        scheme = parsed.scheme or "http"
        host = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(15)

        try:
            sock.connect((host, port))

            if scheme == "https":
                context = ssl.create_default_context()
                sock = context.wrap_socket(sock, server_hostname=host)

            request = build_request(host, path)
            sock.sendall(request.encode("utf-8"))

            raw = recv_all(sock)
        finally:
            sock.close()

        status, headers, body = parse_response(raw)

        # follow redirects
        if status in (301, 302, 303, 307, 308) and "location" in headers:
            new_url = headers["location"]
            if new_url.startswith("/"):
                new_url = f"{scheme}://{host}{new_url}"
            elif not new_url.startswith("http"):
                new_url = f"{scheme}://{host}/{new_url}"
            print(f"[redirect {status}] -> {new_url}")
            url = new_url
            continue

        # cache successful responses
        if use_cache and status == 200:
            cache_put(url, headers, body)

        return status, headers, body

    print("Error: Too many redirects")
    return 0, {}, ""


# content rendering
def render_html(html_text):
    soup = BeautifulSoup(html_text, "html.parser")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    lines = []
    prev_blank = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            if not prev_blank:
                lines.append("")
                prev_blank = True
        else:
            lines.append(line)
            prev_blank = False

    return "\n".join(lines)


def render_json(json_text):
    try:
        data = json.loads(json_text)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        return json_text


def render_response(headers, body):
    content_type = headers.get("content-type", "")
    if "application/json" in content_type:
        print("[Content-Type: JSON]")
        return render_json(body)
    elif "text/html" in content_type:
        return render_html(body)
    else:
        try:
            json.loads(body)
            return render_json(body)
        except (json.JSONDecodeError, ValueError):
            if "<html" in body.lower() or "<body" in body.lower():
                return render_html(body)
            return body


def cmd_url(url):
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url

    print(f"Fetching: {url}\n")
    status, headers, body = http_request(url)

    if status == 0:
        print("Error: Could not connect to server.")
        return

    print(f"Status: {status}")
    print("-" * 60)
    print(render_response(headers, body))


# search engine
def search(term):
    query = quote_plus(term)
    url = f"https://html.duckduckgo.com/html/?q={query}"

    status, headers, body = http_request(url, use_cache=False)
    if status == 0:
        print("Error: Could not reach search engine.")
        return []

    soup = BeautifulSoup(body, "html.parser")
    results = []

    for result_div in soup.select(".result"):
        title_tag = result_div.select_one(".result__a")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")

        if "uddg=" in href:
            parsed_href = urlparse(href)
            qs = parse_qs(parsed_href.query)
            if "uddg" in qs:
                href = qs["uddg"][0]

        snippet_tag = result_div.select_one(".result__snippet")
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

        if title and href and href.startswith("http"):
            results.append((title, href, snippet))
        if len(results) >= 10:
            break

    return results


def cmd_search(term):
    print(f'Searching: "{term}"\n')
    results = search(term)

    if not results:
        print("No results found.")
        return

    for i, (title, url, snippet) in enumerate(results, 1):
        print(f"{i}. {title}")
        print(f"   {url}")
        if snippet:
            print(f"   {snippet}")
        print()

    # interactive link access
    print("-" * 60)
    print("Enter a result number to visit the link (or press Enter to exit):")
    try:
        choice = input("> ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(results):
                title, url, snippet = results[idx]
                print(f"\nFetching: {url}\n")
                status, headers, body = http_request(url)
                if status == 0:
                    print("Error: Could not connect.")
                else:
                    print(f"Status: {status}")
                    print("-" * 60)
                    print(render_response(headers, body))
            else:
                print("Invalid number.")
    except (EOFError, KeyboardInterrupt):
        pass


def main():
    if len(sys.argv) < 2:
        print(HELP_TEXT)
        sys.exit(0)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("-u", type=str, default=None)
    parser.add_argument("-s", nargs="+", default=None)

    args = parser.parse_args()

    if args.help:
        print(HELP_TEXT)
    elif args.u:
        cmd_url(args.u)
    elif args.s:
        term = " ".join(args.s)
        cmd_search(term)
    else:
        print(HELP_TEXT)


if __name__ == "__main__":
    main()
