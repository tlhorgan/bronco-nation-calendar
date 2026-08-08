import re
import hashlib
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from icalendar import Calendar, Event


BASE_URL = "https://thebronconation.com"
EVENTS_URL = "https://thebronconation.com/events/"
OUTPUT_FILE = "bronco-nation.ics"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/130 Safari/537.36"
    )
}


def get_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def find_event_urls():
    """
    Find Bronco Nation event URLs.

    Bronco Nation's events page is dynamically generated, so this function
    searches the returned markup for links matching individual event URLs.
    """
    html = get_page(EVENTS_URL)

    pattern = r'https?://thebronconation\.com/events/[^"\'<> ]+'
    urls = set(re.findall(pattern, html))

    soup = BeautifulSoup(html, "html.parser")

    for link in soup.find_all("a", href=True):
        href = link["href"]

        if "/events/" not in href:
            continue

        url = urljoin(BASE_URL, href)

        # Don't include the event index itself.
        if url.rstrip("/") == EVENTS_URL.rstrip("/"):
            continue

        urls.add(url)

    return sorted(urls)


def extract_text_after_label(text, label, next_labels):
    start = text.find(label)

    if start == -1:
        return None

    start += len(label)
    remainder = text[start:].strip()

    end = len(remainder)

    for next_label in next_labels:
        pos = remainder.find(next_label)

        if pos != -1:
            end = min(end, pos)

    return remainder[:end].strip()


def parse_event(url):
    html = get_page(url)
    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text(" ", strip=True)

    # Title
    title = None

    if soup.find("h1"):
        title = soup.find("h1").get_text(" ", strip=True)

    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
        title = title.replace(" - Bronco Nation", "").strip()

    # Location generally appears near the top of the page.
    location = ""

    address_pattern = re.compile(
        r'([0-9]+[^|]{3,100},\s*[A-Za-z .]+,\s*[A-Z]{2}\s+[0-9]{5}(?:,\s*USA)?)'
    )

    address_match = address_pattern.search(text)

    if address_match:
        location = address_match.group(1).strip()

    # Dates
    start_match = re.search(
        r'START DATE\s+(.+?)\s+END DATE',
        text,
        re.IGNORECASE
    )

    end_match = re.search(
        r'END DATE\s+(.+?)(?:\s+Event Type|\s+About the event|\s+Event details)',
        text,
        re.IGNORECASE
    )

    if not start_match or not end_match:
        print(f"Skipping; could not parse dates: {url}")
        return None

    try:
        start = date_parser.parse(start_match.group(1), fuzzy=True)
        end = date_parser.parse(end_match.group(1), fuzzy=True)
    except Exception as exc:
        print(f"Date error for {url}: {exc}")
        return None

    # Description
    description = ""

    about_match = re.search(
        r'About the event\s+(.+?)(?:\s+Event details|\s+Tickets|\s+Media|\s+Attendees)',
        text,
        re.IGNORECASE
    )

    if about_match:
        description = about_match.group(1).strip()

    return {
        "title": title or "Bronco Nation Event",
        "start": start,
        "end": end,
        "location": location,
        "description": description,
        "url": url,
    }


def make_uid(url):
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return f"{digest}@bronco-nation-calendar"


def create_calendar(events):
    cal = Calendar()

    cal.add("prodid", "-//Bronco Nation Calendar//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", "Bronco Nation Events")

    for item in events:
        event = Event()

        event.add("uid", make_uid(item["url"]))
        event.add("summary", item["title"])
        event.add("dtstart", item["start"])
        event.add("dtend", item["end"])
        event.add("dtstamp", datetime.now(timezone.utc))

        if item["location"]:
            event.add("location", item["location"])

        description = item["description"]

        if description:
            description += "\n\n"

        description += f"Bronco Nation event page:\n{item['url']}"

        event.add("description", description)
        event.add("url", item["url"])

        cal.add_component(event)

    return cal


def main():
    print("Finding Bronco Nation events...")

    event_urls = find_event_urls()

    print(f"Found {len(event_urls)} candidate event pages.")

    events = []

    for url in event_urls:
        print(f"Reading {url}")

        try:
            event = parse_event(url)

            if event:
                events.append(event)
        except Exception as exc:
            print(f"Error reading {url}: {exc}")

    # Sort chronologically
    events.sort(key=lambda x: x["start"])

    calendar = create_calendar(events)

    with open(OUTPUT_FILE, "wb") as f:
        f.write(calendar.to_ical())

    print(f"Wrote {len(events)} events to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
