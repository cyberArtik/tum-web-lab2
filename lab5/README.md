# Lab 5 — go2web

CLI that does HTTP/HTTPS over raw TCP sockets. No `requests`, no `urllib`, no `http.client` — only `socket` + `ssl`. Written in Python because I wanted something readable and `argparse` + `BeautifulSoup` made the non-network parts way faster to write.

## What it does

- `go2web -u <URL>` — fetches a URL and prints it as readable text (HTML stripped, JSON pretty-printed).
- `go2web -s <search-term>` — searches DuckDuckGo, prints the top 10 results, and lets me open one of them.
- `go2web -h` — help.

## Run it

I'm on Windows, so I use the `.bat` shim. PowerShell doesn't load executables from the current directory by default, so I have to prefix with `.\`:

```powershell
.\go2web.bat -h
.\go2web.bat -u https://example.com
.\go2web.bat -u https://jsonplaceholder.typicode.com/todos/1
.\go2web.bat -s python programming
```

On Linux / macOS / Git Bash:

```bash
chmod +x ./go2web
./go2web -h
./go2web -u https://example.com
./go2web -s python programming
```

You need Python 3 + BeautifulSoup. 

```
pip install beautifulsoup4
```

## What's in this folder

| File | What it is |
|------|-----------|
| `go2web.py` | the actual program — everything is in here |
| `go2web` | bash wrapper for Linux/macOS (just calls `python3 go2web.py`) |
| `go2web.bat` | Windows wrapper |
| `.go2web_cache/` | created at runtime — one file per cached URL, named with sha256(url) |

## How it works (short version)

1. Parse URL with `urllib.parse.urlparse` (this isn't a network call, just string stuff — allowed).
2. Open a TCP socket: `socket.socket(AF_INET, SOCK_STREAM)`.
3. If it's HTTPS, wrap the socket with `ssl.create_default_context().wrap_socket(...)` — TLS handshake.
4. Send a hand-built HTTP request like:
   ```
   GET / HTTP/1.1\r\n
   Host: example.com\r\n
   Accept: text/html,application/json;q=0.9,*/*;q=0.8\r\n
   Connection: close\r\n
   \r\n
   ```
5. Read everything until the server closes the socket (`Connection: close` makes that easy).
6. Split on `\r\n\r\n` → headers vs body.
7. If `Transfer-Encoding: chunked`, decode the chunks (this is the most annoying part — each chunk has its size in hex on its own line).
8. Look at `Content-Type`: HTML → BeautifulSoup strips tags → `get_text()`. JSON → `json.dumps(..., indent=2)`. That's the content negotiation part.

## The tricky parts (where I spent time)

**Chunked transfer encoding.** First I just printed `body_bytes.decode()` and got garbage with random hex numbers between paragraphs. Took me a minute to realize those were chunk sizes. The format is `<size in hex>\r\n<bytes>\r\n<size>\r\n<bytes>\r\n…\r\n0\r\n\r\n`. There's a function `decode_chunked` for this.

**HTTPS.** I thought I'd have to implement TLS too, but `ssl.wrap_socket` is fine — TLS is transport, not HTTP. After the wrap, I read/write plain HTTP text and the lib encrypts it for me. The only catch: pass `server_hostname=host` or modern servers reject the handshake (SNI).

**DuckDuckGo links.** Every search result is wrapped in a redirect URL like `//duckduckgo.com/l/?uddg=https%3A%2F%2Frealsite.com…`. If I had used those directly, "open result 3" would just hit DuckDuckGo again. I parse the `uddg=` query param to get the real link.

**Redirects.** Some sites (`http://github.com`) immediately bounce you with a `301 Location: https://github.com/`. I handle 301/302/303/307/308 in a loop, capped at 10 hops so a redirect cycle can't kill the program. Relative `Location` headers (`/path` or `path`) are joined back onto the current host.

## The cache

This is the part the lab gives +2 points for and I think it's the most useful thing in the program — second `-u` on the same URL is instant.

- It lives in `.go2web_cache/`, next to `go2web.py`.
- One file per URL. The filename is `sha256(url)` because URLs have `/`, `?`, `:` in them and Windows hates those in file names.
- Each file is JSON: `{ timestamp, max_age, headers, body }`.
- Default TTL is **300 seconds** (5 minutes). If the response has `Cache-Control: max-age=N` I respect that instead.
- If the response says `no-store` or `no-cache` I just skip writing the file.
- On the next request, if the file exists and `time.time() - timestamp <= max_age`, I return the cached body and print `[cache hit] <url>`. If it's expired, I delete the file and refetch.

For the search engine call I disabled the cache (`use_cache=False`) — search results should always be fresh, otherwise you can't really tell the program is doing anything.

## Demo I do for the prof

```
.\go2web.bat -h                                              # show help
.\go2web.bat -u https://example.com                          # fetch + render HTML
.\go2web.bat -u https://example.com                          # run again → "[cache hit]"
.\go2web.bat -u https://jsonplaceholder.typicode.com/todos/1 # JSON pretty-print
.\go2web.bat -u http://github.com                            # see "[redirect 301]"
.\go2web.bat -s traduceri bulgara                           # 10 results, type "3" → opens the page
```

## Points checklist

- [x] `-h`, `-u`, `-s` (+6)
- [x] Search results are visitable (+1)
- [x] Redirect handling (+1)
- [x] HTTP cache (+2)
- [x] Content negotiation HTML + JSON (+2)

## Why DuckDuckGo and not Google

Google blocks anything that doesn't look like a real Chrome session — I'd need to fake half a dozen headers and probably solve a CAPTCHA anyway. DuckDuckGo has a plain HTML endpoint at `html.duckduckgo.com/html/?q=…` that just works. Bing or Yandex would also work but DDG was first thing I tried and it parsed cleanly.
