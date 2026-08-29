import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from icalendar import Calendar, Event


API_URL = "https://api.thebronconation.com/events"
OUTPUT_FILE = "bronco-nation.ics"

HEADERS = {
    "Accept": "application/json,text/html,application/xhtml+xml",
    "User-Agent": "Mozilla/5.0 (compatible; BroncoEventsCalendar/2.0)",
    "Origin": "https://thebronconation.com",
    "Referer": "https://thebronconation.com/events/",
}

NEBN_URL = "https://www.northeastbronconation.com/events-1"
BRONCO_DRIVER_SUPER_URL = "https://www.broncodriver.com/index.php/super-celebrations/"
BRONCO_DRIVER_OTHER_URL = "https://www.broncodriver.com/index.php/peaceful-haven-events/other-events/"
WILD_HORSES_ROUNDUP_URL = "https://www.wildhorses4x4.com/wh-roundup-2026"

CURRENT_YEAR = datetime.now().year


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).strip()


def slugify(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def get_event_page_url(title, thread_id):
    return f"https://thebronconation.com/events/{slugify(title)}-t.{thread_id}/"


def get_events():
    """Retrieve all upcoming, non-cancelled Bronco Nation events."""
    events = []
    page = 1

    while True:
        print(f"Requesting Bronco Nation event page {page}...")
        params = {
            "past_events": 0,
            "page": page,
            "cancelled_events": 0,
            "region": "",
            "vehicle_type_id": 0,
        }
        response = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)

        # The API returns 422 when page is beyond the final result page.
        if response.status_code == 422:
            print(f"No more Bronco Nation pages after page {page - 1}.")
            break
        response.raise_for_status()
        data = response.json()
        threads = data.get("threads", [])
        if not threads:
            break

        print(f"Found {len(threads)} Bronco Nation events on page {page}")
        for thread in threads:
            event_data = thread.get("Event")
            if event_data:
                events.append({"thread": thread, "event": event_data})
        page += 1

    return events


def unix_to_datetime(timestamp, timezone_name):
    if not timestamp:
        return None
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = timezone.utc
    return datetime.fromtimestamp(timestamp, tz=tz)


def bronco_nation_records(items):
    records = []
    for item in items:
        thread = item["thread"]
        data = item["event"]
        title = clean(data.get("title")) or "Bronco Nation Event"
        start = unix_to_datetime(data.get("start_date"), data.get("timezone", "UTC"))
        end = unix_to_datetime(data.get("end_date"), data.get("timezone", "UTC"))
        if not start:
            continue
        if not end:
            end = start + timedelta(hours=2)

        thread_id = thread.get("thread_id")
        event_page_url = get_event_page_url(title, thread_id) if thread_id else ""
        meetup = data.get("Meetup") or {}
        location = clean(meetup.get("location_name"))
        region = clean(meetup.get("region"))
        description_parts = []
        if clean(data.get("short_description")):
            description_parts.append(clean(data.get("short_description")))
        if region:
            description_parts.append(f"Region: {region}")
        if event_page_url:
            description_parts.append(f"Bronco Nation event:\n{event_page_url}")
        if data.get("register_url"):
            description_parts.append(f"Registration:\n{data['register_url']}")

        records.append({
            "title": title,
            "start": start,
            "end": end,
            "location": location,
            "description": "\n\n".join(description_parts),
            "url": event_page_url,
            "source": "Bronco Nation",
            "source_id": f"bronco-nation-{data.get('event_id', thread_id)}",
        })
    return records


def fetch_soup(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser"), response.url


def parse_date_range(text_value, year=None):
    """Parse strings such as 'September 9-12 2026' or 'November 8'."""
    text_value = clean(text_value).replace("–", "-").replace("—", "-")
    year = year or CURRENT_YEAR

    m = re.search(
        r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(?P<start>\d{1,2})(?:\s*-\s*(?P<end>\d{1,2}))?(?:,)?\s*(?P<year>20\d{2})?",
        text_value,
        re.I,
    )
    if not m:
        return None, None

    y = int(m.group("year") or year)
    month_num = datetime.strptime(m.group("month")[:3], "%b").month
    start_day = int(m.group("start"))
    end_day = int(m.group("end") or start_day)
    start = datetime(y, month_num, start_day, 9, 0)
    end = datetime(y, month_num, end_day, 17, 0)
    return start, end


def future_enough(start):
    day = start.date() if isinstance(start, datetime) else start
    return day >= datetime.now().date() - timedelta(days=1)


def parse_nebn():
    """Parse the Northeast Bronco Nation annual events page."""
    try:
        soup, final_url = fetch_soup(NEBN_URL)
    except Exception as exc:
        print(f"Northeast Bronco Nation unavailable: {exc}")
        return []

    # Wix pages expose readable text in the rendered HTML response.  Pair each
    # event heading with the first date/location lines that follow it.
    lines = [clean(x) for x in soup.stripped_strings if clean(x)]
    records = []
    month_names = {
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    }

    # Known calendar-event titles are represented as headings on the page.
    for i, line in enumerate(lines):
        if len(line) < 5 or len(line) > 100:
            continue
        if line.lower() in month_names or "2026 nebn events" in line.lower():
            continue

        window = lines[i + 1:i + 8]
        date_line = next((x for x in window if re.search(
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}", x, re.I)), None)
        if not date_line:
            continue
        start, end = parse_date_range(date_line, CURRENT_YEAR)
        if not start or not future_enough(start):
            continue

        # Skip navigational/call-to-action text that happens to precede a date.
        if any(x in line.lower() for x in ("join ", "sign up", "get muddy", "cruise with", "leaf peeping", "hit the beach", "get festive")):
            continue

        location = ""
        for x in window:
            if x == date_line:
                continue
            if re.search(r"\b[A-Z]{2}\b", x) and len(x) <= 80:
                location = x
                break

        title = line
        if not any(k in title.lower() for k in (
            "bronco", "may-it", "catskill", "rhode island", "maine lighthouse",
            "fall foliage", "acadia", "feud", "sunday ride", "lobster trap"
        )):
            continue

        records.append({
            "title": title,
            "start": start,
            "end": end,
            "location": location,
            "description": f"Northeast Bronco Nation event.\nSource: {final_url}",
            "url": final_url,
            "source": "Northeast Bronco Nation",
            "source_id": f"nebn-{slugify(title)}-{start.date().isoformat()}",
        })

    print(f"Northeast Bronco Nation: {len(records)} future events")
    return records


def parse_bronco_driver_super():
    """Parse Bronco Driver's official Super Celebrations summary."""
    try:
        soup, final_url = fetch_soup(BRONCO_DRIVER_SUPER_URL)
    except Exception as exc:
        print(f"Bronco Driver Super Celebrations unavailable: {exc}")
        return []

    text = clean(soup.get_text(" ", strip=True))
    pattern = re.compile(
        r"(April\s+15-18\s+2026)\s+Townsend,\s*TN|"
        r"(May\s+14-16\s+2026)\s+Wisconsin|"
        r"(Sept(?:ember)?\s+9-12\s+2026)\s+Buena\s+Vista,\s*CO|"
        r"(Oct(?:ober)?\s+15-17\s+2026)\s+Carson\s+City,\s*NV",
        re.I,
    )

    definitions = [
        ("Bronco Super Celebration East", "April 15-18 2026", "Townsend, TN"),
        ("Bronco Super Celebration Wisconsin", "May 14-16 2026", "La Crosse, WI"),
        ("Bronco Super Celebration West", "September 9-12 2026", "Buena Vista, CO"),
        ("Bronco Super Celebration Nevada", "October 15-17 2026", "Carson City, NV"),
    ]
    records = []
    # Only emit the known entries if the current official page still contains
    # the corresponding date/location text.
    for title, dates, location in definitions:
        start, end = parse_date_range(dates, 2026)
        if start and future_enough(start) and pattern.search(text):
            records.append({
                "title": title,
                "start": start,
                "end": end,
                "location": location,
                "description": f"Official Bronco Driver Super Celebration.\nSource: {final_url}",
                "url": final_url,
                "source": "Bronco Driver",
                "source_id": f"bronco-driver-{slugify(title)}-{start.date().isoformat()}",
            })
    print(f"Bronco Driver Super Celebrations: {len(records)} future events")
    return records


def parse_bronco_driver_other():
    """Parse Bronco Driver's official table of other Bronco events."""
    try:
        soup, final_url = fetch_soup(BRONCO_DRIVER_OTHER_URL)
    except Exception as exc:
        print(f"Bronco Driver other events unavailable: {exc}")
        return []

    records = []
    for row in soup.select("table tr"):
        cells = [clean(c.get_text(" ", strip=True)) for c in row.find_all(["th", "td"])]
        if len(cells) < 3 or cells[0].lower() == "date":
            continue
        date_text, title, state = cells[:3]
        start, end = parse_date_range(date_text, 2026)
        if not start or not future_enough(start):
            continue
        if not title or "bronco" not in (title + " " + clean(row.get_text())).lower():
            continue

        link = row.find("a", href=True)
        url = urljoin(final_url, link["href"]) if link else final_url
        records.append({
            "title": title,
            "start": start,
            "end": end,
            "location": state,
            "description": f"Listed on Bronco Driver's 2026 national Bronco event schedule.\nSource: {final_url}",
            "url": url,
            "source": "Bronco Driver Other Events",
            "source_id": f"bronco-driver-other-{slugify(title)}-{start.date().isoformat()}",
        })

    print(f"Bronco Driver other events: {len(records)} future events")
    return records


def parse_jsonld_events(url, source_name):
    """Generic Event JSON-LD parser used for vendor/club event pages."""
    try:
        soup, final_url = fetch_soup(url)
    except Exception as exc:
        print(f"{source_name} unavailable: {exc}")
        return []

    records = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop()
            if not isinstance(obj, dict):
                continue
            graph = obj.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            typ = obj.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if not any("event" in str(t).lower() for t in types if t):
                continue
            title = clean(obj.get("name"))
            start_raw = obj.get("startDate")
            if not title or not start_raw:
                continue
            try:
                start = dtparser.parse(str(start_raw))
                end = dtparser.parse(str(obj.get("endDate"))) if obj.get("endDate") else start + timedelta(hours=3)
            except Exception:
                continue
            if not future_enough(start):
                continue

            loc = obj.get("location") or {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            location = ""
            if isinstance(loc, dict):
                parts = [clean(loc.get("name"))]
                address = loc.get("address")
                if isinstance(address, dict):
                    parts.extend(clean(address.get(k)) for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode"))
                elif isinstance(address, str):
                    parts.append(clean(address))
                location = ", ".join(x for x in parts if x)
            elif isinstance(loc, str):
                location = clean(loc)

            event_url = clean(obj.get("url")) or final_url
            records.append({
                "title": title,
                "start": start,
                "end": end,
                "location": location,
                "description": f"{source_name} event.\nSource: {final_url}",
                "url": event_url,
                "source": source_name,
                "source_id": f"{slugify(source_name)}-{slugify(title)}-{start.date().isoformat()}",
            })
    print(f"{source_name}: {len(records)} JSON-LD events")
    return records


def parse_wild_horses_roundup():
    records = parse_jsonld_events(WILD_HORSES_ROUNDUP_URL, "Wild Horses 4x4")
    if records:
        return records

    # Fallback for the current Wild Horses page if it omits Event JSON-LD.
    try:
        soup, final_url = fetch_soup(WILD_HORSES_ROUNDUP_URL)
        text = clean(soup.get_text(" ", strip=True))
    except Exception as exc:
        print(f"Wild Horses Roundup unavailable: {exc}")
        return []

    if "May 16-17, 2026" not in text and "May 16-17 2026" not in text:
        return []
    start, end = parse_date_range("May 16-17 2026", 2026)
    if not future_enough(start):
        return []
    return [{
        "title": "Wild Horses Bronco Roundup 2026",
        "start": start,
        "end": end,
        "location": "1045 S. Cherokee Lane, Lodi, CA 95240",
        "description": f"Wild Horses 4x4 Bronco Roundup and trail weekend.\nSource: {final_url}",
        "url": final_url,
        "source": "Wild Horses 4x4",
        "source_id": f"wild-horses-roundup-{start.date().isoformat()}",
    }]


def same_event(a, b):
    ad = a["start"].date() if isinstance(a["start"], datetime) else a["start"]
    bd = b["start"].date() if isinstance(b["start"], datetime) else b["start"]
    if ad != bd:
        return False
    ta, tb = norm(a["title"]), norm(b["title"])
    if ta == tb:
        return True
    if ta in tb or tb in ta:
        shorter, longer = min(len(ta), len(tb)), max(len(ta), len(tb))
        return shorter >= 10 and shorter / max(longer, 1) >= 0.72
    # Common cross-source naming differences.
    tokens_a = set(ta.split())
    tokens_b = set(tb.split())
    overlap = tokens_a & tokens_b
    return len(overlap) >= 3 and len(overlap) / max(min(len(tokens_a), len(tokens_b)), 1) >= 0.65


def dedupe(records):
    priority = {
        "Bronco Nation": 0,
        "Northeast Bronco Nation": 1,
        "Bronco Driver": 2,
        "Bronco Driver Other Events": 3,
        "Wild Horses 4x4": 4,
    }
    kept = []
    for record in sorted(records, key=lambda r: (r["start"], priority.get(r["source"], 9))):
        match = next((x for x in kept if same_event(x, record)), None)
        if match:
            # Keep richer location/description and preserve source attribution.
            if len(record.get("location", "")) > len(match.get("location", "")):
                match["location"] = record["location"]
            if record["source"] not in match.get("description", ""):
                match["description"] = clean(match.get("description")) + f"\n\nAlso listed by: {record['source']}"
            continue
        kept.append(record)
    return kept


def build_calendar(records):
    cal = Calendar()
    cal.add("prodid", "-//Bronco Events Calendar//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "Bronco Nation Events")

    for item in sorted(records, key=lambda r: r["start"]):
        event = Event()
        uid_seed = item.get("source_id") or f"{item['title']}|{item['start']}|{item.get('location', '')}"
        uid = hashlib.sha256(uid_seed.encode()).hexdigest()[:30] + "@bronco-events"
        event.add("uid", uid)
        event.add("summary", item["title"])
        event.add("dtstart", item["start"])
        event.add("dtend", item["end"])
        event.add("dtstamp", datetime.now(timezone.utc))
        if item.get("location"):
            event.add("location", item["location"])
        if item.get("description"):
            event.add("description", item["description"])
        if item.get("url"):
            event.add("url", item["url"])
        cal.add_component(event)
        print(f"Added [{item['source']}]: {item['title']} ({item['start'].date()})")
    return cal


def main():
    records = []

    print("Downloading Bronco Nation events...")
    try:
        bn_items = get_events()
        records.extend(bronco_nation_records(bn_items))
        print(f"Bronco Nation records: {len(records)}")
    except Exception as exc:
        print(f"Bronco Nation API failed: {exc}")

    print("Downloading supplemental Bronco calendars...")
    records.extend(parse_nebn())
    records.extend(parse_bronco_driver_super())
    records.extend(parse_bronco_driver_other())
    records.extend(parse_wild_horses_roundup())

    unique = dedupe(records)
    print(f"Collected {len(records)} records; {len(unique)} unique events after deduplication")
    if not unique:
        raise RuntimeError("No Bronco events were collected from any source")

    calendar = build_calendar(unique)
    with open(OUTPUT_FILE, "wb") as file:
        file.write(calendar.to_ical())
    print(f"Calendar written to {OUTPUT_FILE} with {len(unique)} events")


if __name__ == "__main__":
    main()
