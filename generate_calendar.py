import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from icalendar import Calendar, Event


API_URL = "https://api.thebronconation.com/events"
OUTPUT_FILE = "bronco-nation.ics"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "BroncoNationCalendar/1.0",
    "Origin": "https://thebronconation.com",
    "Referer": "https://thebronconation.com/events/",
}


def slugify(text):
    """Convert an event title into the format used in Bronco Nation URLs."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def get_event_page_url(title, thread_id):
    slug = slugify(title)

    return (
        f"https://thebronconation.com/events/"
        f"{slug}-t.{thread_id}/"
    )


def get_events():
    """
    Retrieve all upcoming, non-cancelled Bronco Nation events.
    """

    events = []
    page = 1

    while True:
        print(f"Requesting event page {page}...")

        params = {
            "past_events": 0,
            "page": page,
            "cancelled_events": 0,
            "region": "",
            "vehicle_type_id": 0,
        }

        response = requests.get(
            API_URL,
            params=params,
            headers=HEADERS,
            timeout=30,
        )

        # Bronco Nation returns HTTP 422 when we request
        # a page beyond the last available page.
        if response.status_code == 422:
            print(f"No more event pages after page {page - 1}.")
            break

        response.raise_for_status()

        data = response.json()

        threads = data.get("threads", [])

        if not threads:
            break

        print(f"Found {len(threads)} events on page {page}")

        for thread in threads:
            event_data = thread.get("Event")

            if event_data:
                events.append(
                    {
                        "thread": thread,
                        "event": event_data,
                    }
                )

        page += 1

    return events


def unix_to_datetime(timestamp, timezone_name):
    """
    Convert a Unix timestamp into an aware datetime using the event's
    declared timezone.
    """

    if not timestamp:
        return None

    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        print(
            f"Unknown timezone '{timezone_name}'. "
            "Falling back to UTC."
        )
        tz = timezone.utc

    return datetime.fromtimestamp(timestamp, tz=tz)


def build_calendar(items):
    cal = Calendar()

    cal.add("prodid", "-//Bronco Nation Calendar//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "Bronco Nation Events")

    for item in items:
        thread = item["thread"]
        data = item["event"]

        title = data.get("title", "Bronco Nation Event")

        start_timestamp = data.get("start_date")
        end_timestamp = data.get("end_date")

        timezone_name = data.get("timezone", "UTC")

        start = unix_to_datetime(
            start_timestamp,
            timezone_name,
        )

        end = unix_to_datetime(
            end_timestamp,
            timezone_name,
        )

        if not start:
            print(f"Skipping '{title}' because it has no start date.")
            continue

        # If the API happens to omit an end time, use the start time.
        if not end:
            end = start

        thread_id = thread.get("thread_id")

        event_page_url = ""

        if thread_id:
            event_page_url = get_event_page_url(
                title,
                thread_id,
            )

        meetup = data.get("Meetup") or {}

        location = meetup.get("location_name", "")
        region = meetup.get("region", "")

        description = data.get("short_description", "") or ""

        register_url = data.get("register_url")

        description_parts = []

        if description:
            description_parts.append(description)

        if region:
            description_parts.append(
                f"Region: {region}"
            )

        if event_page_url:
            description_parts.append(
                f"Bronco Nation event:\n{event_page_url}"
            )

        if register_url:
            description_parts.append(
                f"Registration:\n{register_url}"
            )

        full_description = "\n\n".join(description_parts)

        event = Event()

        event_id = data.get("event_id", thread_id)

        event.add(
            "uid",
            f"bronco-nation-{event_id}@thebronconation.com",
        )

        event.add("summary", title)
        event.add("dtstart", start)
        event.add("dtend", end)
        event.add("dtstamp", datetime.now(timezone.utc))

        if location:
            event.add("location", location)

        if full_description:
            event.add("description", full_description)

        if event_page_url:
            event.add("url", event_page_url)

        cal.add_component(event)

        print(
            f"Added: {title} "
            f"({start.strftime('%Y-%m-%d %H:%M %Z')})"
        )

    return cal


def main():
    print("Downloading Bronco Nation events...")

    items = get_events()

    print(f"Total events retrieved: {len(items)}")

    calendar = build_calendar(items)

    with open(OUTPUT_FILE, "wb") as file:
        file.write(calendar.to_ical())

    print(f"Calendar written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
