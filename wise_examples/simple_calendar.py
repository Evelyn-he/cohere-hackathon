import asyncio
import httpx
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import Context
from north_mcp_python_sdk import NorthMCPServer
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Dict, Optional

load_dotenv()

# update all the mcp tool functions to be <firstname_lastname>_<tool>
# since mcp tool names MUST be unique

mcp = NorthMCPServer(
    name="Google Calendar",
    host="0.0.0.0",
    port=3002
)

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

TICKETMASTER_API_KEY = "gpMqpLqs1VDGhY1mgRhT0UOSh1EgHSM1"
TICKETMASTER_API_BASE = "https://app.ticketmaster.com/discovery/v2"

def _get_google_token():
    return os.getenv("ACCESS_TOKEN")


async def _fetch_calendar_data(access_token: str, url: str, params: dict = None):
    """Helper function for GET requests to Google Calendar API"""
    # Authorization header authenticates with Google using OAuth2 bearer token
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # Using async/await for non-blocking I/O - allows the server to handle multiple
    # calendar requests concurrently while waiting for Google API responses
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        # raise_for_status() converts HTTP errors (401, 404, 500, etc.) into exceptions
        # immediately, preventing attempts to parse error responses as valid JSON
        response.raise_for_status()
        return response.json()


async def _modify_calendar_data(access_token: str, url: str, method: str, json_payload: dict = None):
    """Helper function for POST/DELETE requests to Google Calendar API"""
    # Authorization header authenticates with Google using OAuth2 bearer token
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # Content-Type header tells Google the payload format (only needed when sending data)
    if json_payload:
        headers["Content-Type"] = "application/json"
    
    async with httpx.AsyncClient() as client:
        # json_payload is the request body containing data to send (e.g., event details
        # for creating/updating events). It's automatically serialized to JSON format.
        response = await client.request(
            method,
            url,
            headers=headers,
            json=json_payload
        )
        response.raise_for_status()
        
        # 204 = "No Content" - request succeeded but no response body (typical for DELETE)
        # Return success dict instead of trying to parse empty response as JSON
        if response.status_code == 204:
            return {"success": True}
        
        return response.json()



def format_event_to_document(event):
    """Convert a calendar event to a well-formatted document"""
    summary = event.get("summary", "(No title)")
    description = event.get("description", "")
    location = event.get("location", "")
    html_link = event.get("htmlLink", "")
    
    # Format start and end times
    # Google Calendar has two event types:
    # - Timed events: {"start": {"dateTime": "2026-01-15T10:00:00Z"}}
    # - All-day events: {"start": {"date": "2026-01-15"}}
    start = event.get("start", {})
    end = event.get("end", {})
    # Nested fallback: try dateTime first (timed events), then date (all-day), then default
    start_time = start.get("dateTime", start.get("date", "Not specified"))
    end_time = end.get("dateTime", end.get("date", "Not specified"))
    
    # Format attendees
    attendees = event.get("attendees", [])
    attendees_formatted = []
    for attendee in attendees:
        name = attendee.get("displayName", attendee.get("email", "Unknown"))
        status = attendee.get("responseStatus", "needsAction")
        organizer = " (Organizer)" if attendee.get("organizer") else ""
        attendees_formatted.append(f"{name} - {status}{organizer}")
    
    # Format conference data
    # Entry points are different ways to join a meeting: video link, phone dial-in, SIP address
    # We filter for "video" type to get the clickable URL (Google Meet/Zoom link)
    conference_link = ""
    conference_data = event.get("conferenceData", {})
    if conference_data:
        entry_points = conference_data.get("entryPoints", [])
        for entry in entry_points:
            # Only extract video conference link (e.g., meet.google.com/abc-defg-hij)
            if entry.get("entryPointType") == "video":
                conference_link = entry.get("uri", "")
                break  # Stop after finding the first video link
    
    
    # Build formatted content
    content = f"# {summary}\n\n"
    
    if description:
        content += f"**Description:** {description}\n\n"
    
    content += f"**Start:** {start_time}\n"
    content += f"**End:** {end_time}\n\n"
    
    if location:
        content += f"**Location:** {location}\n\n"
    if attendees_formatted:
        content += f"**Attendees ({len(attendees_formatted)}):**\n"
        for attendee in attendees_formatted:
            content += f"  - {attendee}\n"
        content += "\n"
    
    if conference_link:
        content += f"**Video Conference:** {conference_link}\n\n"
    status = event.get("status", "confirmed")
    content += f"**Status:** {status}\n"
    
    if html_link:
        content += f"**Link:** {html_link}\n"
    
    return {
        "id": event.get("id"),
        "kind": event.get("kind", "calendar#event"),
        "title": summary,
        "url": html_link,
        "content": content.strip(),
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "attendees_count": len(attendees)
    }


def parse_event_datetime(event):
    dates_info = event.get("dates", {}).get("start", {})
    date_str = dates_info.get("localDate")
    time_str = dates_info.get("localTime", "00:00:00")

    if not date_str:
        return None, None

    start_datetime = datetime.fromisoformat(
        f"{date_str}T{time_str}"
    ).replace(tzinfo=timezone.utc)

    end_info = event.get("dates", {}).get("end", {})
    end_date_str = end_info.get("localDate")
    end_time_str = end_info.get("localTime")

    if end_date_str and end_time_str:
        end_datetime = datetime.fromisoformat(
            f"{end_date_str}T{end_time_str}"
        ).replace(tzinfo=timezone.utc)
    else:
        end_datetime = start_datetime + timedelta(hours=3)

    return start_datetime, end_datetime

def extract_event_details(event) -> Dict:
    """
    Extract key details from a Ticketmaster event:
    - Concert start/end times
    - Public ticket sale start/end times
    """
    details = {
        "name": event.get("name", "N/A"),
        "url": event.get("url", "N/A")
    }
    
    # Concert start/end times
    start_dt, end_dt = parse_event_datetime(event)
    details["concert_start"] = start_dt.isoformat() if start_dt else "N/A"
    details["concert_end"] = end_dt.isoformat() if end_dt else "N/A"
    
    # Venue info
    if "_embedded" in event and "venues" in event["_embedded"]:
        venue = event["_embedded"]["venues"][0]
        details["venue_name"] = venue.get("name", "N/A")
        
        # Full address
        address_parts = []
        if venue.get("address", {}).get("line1"):
            address_parts.append(venue["address"]["line1"])
        if venue.get("city", {}).get("name"):
            address_parts.append(venue["city"]["name"])
        if venue.get("state", {}).get("stateCode"):
            address_parts.append(venue["state"]["stateCode"])
        if venue.get("postalCode"):
            address_parts.append(venue["postalCode"])
        if venue.get("country", {}).get("countryCode"):
            address_parts.append(venue["country"]["countryCode"])
        details["venue_address"] = ", ".join(address_parts) if address_parts else "N/A"
    else:
        details["venue_name"] = "N/A"
        details["venue_address"] = "N/A"
    
    # Category/genre info
    classifications = event.get("classifications", [])
    if classifications:
        details["category"] = classifications[0].get("segment", {}).get("name", "N/A")
        details["genre"] = classifications[0].get("genre", {}).get("name", "N/A")
        details["subgenre"] = classifications[0].get("subGenre", {}).get("name", "N/A")
    else:
        details["category"] = "N/A"
        details["genre"] = "N/A"
        details["subgenre"] = "N/A"
    
    # Price info
    price_ranges = event.get("priceRanges", [])
    if price_ranges:
        pr = price_ranges[0]
        details["price_min"] = pr.get("min", "N/A")
        details["price_max"] = pr.get("max", "N/A")
        details["currency"] = pr.get("currency", "USD")
    else:
        details["price_min"] = "N/A"
        details["price_max"] = "N/A"
        details["currency"] = "N/A"
    
    # Public ticket sale info
    public_sale = event.get("sales", {}).get("public", {})
    details["onsale_start"] = public_sale.get("startDateTime", "N/A")
    details["onsale_end"] = public_sale.get("endDateTime", "N/A")
    details["sale_status"] = public_sale.get("startTBD", False)
    
    return details


def event_falls_within_time_ranges(event, time_ranges: List[Tuple[datetime, datetime]]) -> bool:
    """
    Check if event falls completely within any of the specified time ranges.
    
    Args:
        event: Event data from Ticketmaster API
        time_ranges: List of (start_datetime, end_datetime) tuples
    
    Returns:
        True if event falls completely within at least one time range
    """
    event_start, event_end = parse_event_datetime(event)
    
    if not event_start or not event_end:
        return False
    
    for range_start, range_end in time_ranges:
        # Check if event falls completely within this time range
        if range_start <= event_start and event_end <= range_end:
            return True
    
    return False

async def get_concerts_in_time_ranges(
    city: str,
    state_code: str,
    time_ranges: List[Tuple[datetime, datetime]],
    genre: str = None
) -> List[Dict]:
    """
    Get concerts that fall completely within specified time ranges,
    as well as the times that the tickets for said concerts become
    available.
    
    Args:
        city: City name (e.g., "San Francisco")
        state_code: Two-letter state code (e.g., "CA")
        time_ranges: List of (start_datetime, end_datetime) tuples
        genre: Optional genre filter
    
    Returns:
        List of dictionaries containing event details (such as when the 
        concert starts and ends, when ticket sales begin and end, location
        of the concert, etc.)
    """
    if not time_ranges:
        return []

    # Find the overall min and max dates to query API efficiently
    all_starts = [start for start, _ in time_ranges]
    all_ends = [end for _, end in time_ranges]
    overall_start = min(all_starts)
    overall_end = max(all_ends)
    
    params = {
        "apikey": TICKETMASTER_API_KEY,
        "city": city,
        "stateCode": state_code,
        "startDateTime": overall_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": overall_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "classificationName": "Music",
        "sort": "relevance,desc",
        "size": 30
    }
    
    if genre:
        params["genreName"] = genre
    
    filtered_events = []
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{TICKETMASTER_API_BASE}/events",
                params=params,
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            
            if "_embedded" in data and "events" in data["_embedded"]:
                events = data["_embedded"]["events"]
                
                # Filter events to only those that fall completely within time ranges
                for event in events:
                    if event_falls_within_time_ranges(event, time_ranges):
                        event_details = extract_event_details(event)
                        filtered_events.append(event_details)
            
            return filtered_events
            
    except Exception as e:
        print(f"❌ Error fetching events: {e}")
        return []

async def get_concerts(start_date: datetime, end_date: datetime, city: str = "Toronto", state_code: str = "ON"):
    
    time_ranges = [
        (
            start_date,
            end_date
        ),
    ]
    
    concerts = await get_concerts_in_time_ranges(
        city=city,
        state_code=state_code,
        time_ranges=time_ranges
    )
    
    return concerts

@mcp.tool()
async def e100_h100_get_ticketmaster_concerts(
    start_time: str,
    end_time: str,
) -> list:
    """
    Given a start date/time and end date/time, this function will check
    Ticketmaster for any concerts which fall into that timeframe, and
    return information of those concerts in a dictionary.
    
    :param start_time: The start of the range to look for concerts
    :type start_time: str
    :param end_time: The end of the range to look for concerts
    :type end_time: str
    :return: List
    :rtype: A list of entries containing information of concerts which fall into the time frame (including price, location, time, venue, etc.)
    """
    start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
    return await get_concerts(start_dt, end_dt)


@mcp.tool()
async def e100_h100_cohere_hackathon_list_calendar_events(
    ctx: Context,
    max_results: int = 10,
    time_min: str = None,
    time_max: str = None,
    search_query: str = None
):
    """List events from the user's primary calendar with optional filtering
    Args:
        ctx: Request context
        max_results: Maximum number of events to return (default: 10)
        time_min: Lower bound for event start time (RFC3339 format, e.g., "2024-01-15T00:00:00Z")
        time_max: Upper bound for event end time (RFC3339 format)
        search_query: Free text search to find events matching keywords
    Returns:
        List of formatted calendar events with detailed information
    """
    token = _get_google_token()
    
    # Build query parameters for Google Calendar API
    params = {
        "maxResults": max_results,
        "singleEvents": True,  # Expand recurring events into individual instances
        "orderBy": "startTime"  # Sort chronologically (requires singleEvents=True)
    }
    
    # Add optional filters if provided
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max
    if search_query:
        params["q"] = search_query  # Free text search across event fields
    
    # Fetch events from the user's primary calendar
    response = await _fetch_calendar_data(
        token,
        f"{CALENDAR_API_BASE}/calendars/primary/events",
        params=params
    )
    
    # Convert raw API response items to formatted documents
    events = [format_event_to_document(item) for item in response.get("items", [])]
    
    result = {
        "events": events,
        "total_returned": len(events)
    }
    
    # Handle pagination - Google splits large result sets across multiple requests
    # If there are more events beyond maxResults, Google returns a nextPageToken
    # (e.g., "CiQKGjBhaWs...XyZ") that can be used to fetch the next batch of events
    # To get the next page, pass this token as the 'pageToken' parameter in a new request
    if response.get("nextPageToken"):
        result["next_page_token"] = response["nextPageToken"]
        result["has_more"] = True  # Signal to caller that more data is available
    
    return result


# destructiveHint=True triggers safety prompts, asking the user to confirm
# before creating a calendar event (prevents accidental data modifications)
@mcp.tool(annotations={"destructiveHint": True})
async def e100_h100_cohere_hackathon_create_calendar_event(
    ctx: Context,
    title: str,
    start_time: str,
    end_time: str,
    description: str = "",
    location: str = "",
    attendees: str = None,
    timezone: str = "America/New_York"  # Hardcoded EST
):
    """
    Create a new calendar event with optional attendees, location, and reminder.
    Times are assumed to be in the calendar's timezone (EST).
    """
    token = _get_google_token()

    # Remove 'Z' suffix if present
    start_time_clean = start_time.rstrip('Z') if start_time.endswith('Z') else start_time
    end_time_clean = end_time.rstrip('Z') if end_time.endswith('Z') else end_time

    event_data = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_time_clean, "timeZone": timezone},
        "end": {"dateTime": end_time_clean, "timeZone": timezone}
    }

    if location:
        event_data["location"] = location

    if attendees:
        email_list = [email.strip() for email in attendees.split(",")]
        event_data["attendees"] = [{"email": email} for email in email_list]

    response = await _modify_calendar_data(
        token,
        f"{CALENDAR_API_BASE}/calendars/primary/events",
        method="POST",
        json_payload=event_data
    )

    return format_event_to_document(response)


@mcp.tool()
async def e100_h100_cohere_hackathon_get_calendar_event(ctx: Context, event_id: str):
    """Get detailed information about a specific calendar event
    Args:
        ctx: Request context
        event_id: The ID of the event to retrieve
    Returns:
        Detailed event information with formatted content
    """
    token = _get_google_token()
    response = await _fetch_calendar_data(
        token,
        f"{CALENDAR_API_BASE}/calendars/primary/events/{event_id}"
    )
    
    return format_event_to_document(response)


# destructiveHint=True triggers safety prompts, asking the user to confirm
# before deleting a calendar event (prevents accidental data loss)
@mcp.tool(annotations={"destructiveHint": True})
async def e100_h100_cohere_hackathon_delete_calendar_event(ctx: Context, event_id: str):
    """Delete a calendar event by ID
    Args:
        ctx: Request context
        event_id: The ID of the event to delete
    Returns:
        Success confirmation
    """
    token = _get_google_token()
    await _modify_calendar_data(
        token,
        f"{CALENDAR_API_BASE}/calendars/primary/events/{event_id}",
        method="DELETE"
    )
    
    return {"success": True, "message": f"Event {event_id} deleted successfully"}


# destructiveHint=True triggers safety prompts, asking the user to confirm
# before updating a calendar event (prevents accidental data modifications)
@mcp.tool(annotations={"destructiveHint": True})
async def e100_h100_cohere_hackathon_update_calendar_event(
    ctx: Context,
    event_id: str,
    title: str = None,
    start_time: str = None,
    end_time: str = None,
    description: str = None,
    location: str = None,
    attendees: str = None,
    timezone: str = "America/New_York"  # Hardcoded EST
):
    """
    Update an existing calendar event.
    Times are assumed to be in EST if provided.
    """
    token = _get_google_token()

    # Fetch current event
    current_event = await _fetch_calendar_data(
        token,
        f"{CALENDAR_API_BASE}/calendars/primary/events/{event_id}"
    )

    # Update only provided fields
    if title is not None:
        current_event["summary"] = title
    if description is not None:
        current_event["description"] = description
    if location is not None:
        current_event["location"] = location
    if start_time is not None:
        start_time_clean = start_time.rstrip('Z') if start_time.endswith('Z') else start_time
        current_event["start"] = {"dateTime": start_time_clean, "timeZone": timezone}
    if end_time is not None:
        end_time_clean = end_time.rstrip('Z') if end_time.endswith('Z') else end_time
        current_event["end"] = {"dateTime": end_time_clean, "timeZone": timezone}
    if attendees is not None:
        email_list = [email.strip() for email in attendees.split(",")]
        current_event["attendees"] = [{"email": email} for email in email_list]

    response = await _modify_calendar_data(
        token,
        f"{CALENDAR_API_BASE}/calendars/primary/events/{event_id}",
        method="PUT",
        json_payload=current_event
    )

    return format_event_to_document(response)

@mcp.tool()
async def e100_h100_search_ticketmaster_events(
    ctx: Context,
    keyword: str = None,
    city: str = None,
    state: str = None,
    postal_code: str = None,
    country_code: str = "US",
    category: str = None,
    genre: str = None,
    start_date: str = None,
    end_date: str = None,
    size: int = 10
):
    """Search for events on Ticketmaster based on location, category, and preferences
    Args:
        ctx: Request context
        keyword: Search keyword for event name/artist (optional)
        city: City name (e.g., "Los Angeles", "New York") (optional)
        state: State code (e.g., "CA", "NY") (optional)
        postal_code: Postal/ZIP code (optional)
        country_code: Country code (default: "US") (optional)
        category: Event category - Music, Sports, Arts & Theatre, Film, Miscellaneous (optional)
        genre: Event genre - Rock, Pop, Hip-Hop/Rap, Country, Jazz, Classical, etc. (optional)
        start_date: Start date for events in YYYY-MM-DD format (optional)
        end_date: End date for events in YYYY-MM-DD format (optional)
        size: Number of results to return (default: 10, max: 200)
    Returns:
        List of matching events from Ticketmaster with details including name, date, venue, and pricing
    """
    api_key = TICKETMASTER_API_KEY
    
    if not api_key:
        return {"error": "Ticketmaster API key not set. Please add your API key to TICKETMASTER_API_KEY at the top of simple_calendar.py"}
    
    params = {
        "apikey": api_key,
        "size": min(size, 200),  # Cap at 200 per API limit
        "countryCode": country_code
    }
    
    # Add optional search filters
    if keyword:
        params["keyword"] = keyword
    if city:
        params["city"] = city
    if state:
        params["stateCode"] = state
    if postal_code:
        params["postalCode"] = postal_code
    if category:
        params["classificationName"] = category
    if genre:
        params["genreName"] = genre
    if start_date:
        params["startDateTime"] = f"{start_date}T00:00:00Z"
    if end_date:
        params["endDateTime"] = f"{end_date}T23:59:59Z"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{TICKETMASTER_API_BASE}/events",
                params=params,
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract and format events from the response
            events = []
            if "_embedded" in data and "events" in data["_embedded"]:
                for event in data["_embedded"]["events"]:
                    # Extract genre and category info
                    classifications = event.get("classifications", [])
                    genre_name = None
                    category_name = None
                    if classifications:
                        genre = classifications[0].get("genre", {})
                        category = classifications[0].get("segment", {})
                        genre_name = genre.get("name") if genre else None
                        category_name = category.get("name") if category else None
                    
                    # Extract date info
                    dates_info = event.get("dates", {}).get("start", {})
                    event_date = dates_info.get("localDate", "N/A")
                    event_time = dates_info.get("localTime", "")
                    
                    # Extract price info
                    price_info = None
                    price_ranges = event.get("priceRanges", [])
                    if price_ranges:
                        pr = price_ranges[0]
                        price_info = {
                            "min": pr.get("min"),
                            "max": pr.get("max"),
                            "currency": pr.get("currency", "USD")
                        }
                    
                    event_info = {
                        "id": event.get("id"),
                        "name": event.get("name"),
                        "url": event.get("url"),
                        "date": event_date,
                        "time": event_time,
                        "category": category_name,
                        "genre": genre_name,
                        "status": event.get("status", {}).get("code"),
                        "price_info": price_info,
                    }
                    
                    # Extract venue information
                    if "_embedded" in event and "venues" in event["_embedded"]:
                        venue = event["_embedded"]["venues"][0]
                        event_info["venue"] = {
                            "name": venue.get("name"),
                            "city": venue.get("city", {}).get("name"),
                            "state": venue.get("state", {}).get("stateCode"),
                            "country": venue.get("country", {}).get("countryCode"),
                            "address": venue.get("address", {}).get("line1")
                        }
                    
                    events.append(event_info)
            
            return {
                "events": events,
                "total_returned": len(events),
                "total_available": data.get("page", {}).get("totalElements", 0)
            }
    
    except httpx.HTTPError as e:
        return {"error": f"Failed to search Ticketmaster events: {str(e)}"}


# Use streamable-http transport to enable streaming responses over HTTP.
# This allows the server to send data to the client incrementally (in chunks),
# improving responsiveness for long-running or large operations.
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
