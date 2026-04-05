import sys
import socket
import ssl
import argparse
import io
from urllib.parse import urlparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


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
def build_request(host, path):
    return (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"User-Agent: go2web/1.0\r\n"
        f"Accept: text/html\r\n"
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


def http_request(url):
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
    return status, headers, body


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
    print(body)


def cmd_search(term):
    print(f'Searching: "{term}"')
    # TODO: implement search
    print("Not implemented yet.")


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
