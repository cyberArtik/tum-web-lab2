import sys
import argparse


HELP_TEXT = """go2web (request and search)

Usage:
  go2web -u <URL>           Make an HTTP request to the specified URL and print the response
  go2web -s <search-term>   Search the term and print top 10 results
  go2web -h                 Show this help

Examples:
  go2web -u https://example.com
  go2web -s "python programming"
"""


def cmd_url(url):
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
    print(f"Fetching: {url}")
    # TODO: implement HTTP request
    print("Not implemented yet.")


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
