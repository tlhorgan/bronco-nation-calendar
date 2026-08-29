from pathlib import Path
from icalendar import Calendar

SOURCE = Path("bronco-nation.ics")
OTHER = Path("other-bronco-events.ics")


def new_calendar(name):
    cal = Calendar()
    cal.add("prodid", "-//Bronco Events Calendar//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", name)
    return cal


def classify(component):
    desc = str(component.get("DESCRIPTION", ""))
    url = str(component.get("URL", ""))
    text = (desc + " " + url).lower()

    # Northeast Bronco Nation belongs in the separate New England off-road feed.
    if "northeast bronco nation" in text or "northeastbronconation.com" in text:
        return "new-england"

    # Supplemental national sources outside New England belong in Other Bronco Events.
    if (
        "bronco driver" in text
        or "broncodriver.com" in text
        or "wild horses" in text
        or "wildhorses4x4.com" in text
    ):
        return "other"

    return "bronco-nation"


def main():
    if not SOURCE.exists():
        raise RuntimeError(f"{SOURCE} does not exist")

    combined = Calendar.from_ical(SOURCE.read_bytes())
    bronco_nation = new_calendar("Bronco Nation Events")
    other = new_calendar("Other Bronco Events")

    counts = {"bronco-nation": 0, "new-england": 0, "other": 0}

    for component in combined.walk("VEVENT"):
        bucket = classify(component)
        counts[bucket] += 1
        if bucket == "bronco-nation":
            bronco_nation.add_component(component)
        elif bucket == "other":
            other.add_component(component)

    if counts["bronco-nation"] == 0:
        raise RuntimeError("No Bronco Nation events found; refusing to overwrite feed")

    SOURCE.write_bytes(bronco_nation.to_ical())
    OTHER.write_bytes(other.to_ical())

    print(f"Bronco Nation: {counts['bronco-nation']} events")
    print(f"New England events excluded for New England feed: {counts['new-england']}")
    print(f"Other Bronco Events: {counts['other']} events")


if __name__ == "__main__":
    main()
