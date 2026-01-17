#!/usr/bin/env python3
"""Test script for Ticketmaster API integration"""

import asyncio
import httpx
from simple_calendar import TICKETMASTER_API_KEY, TICKETMASTER_API_BASE

async def test_search(description, params):
    """Run a test search with given parameters"""
    print(f"\n{'='*60}")
    print(f"Test: {description}")
    print(f"{'='*60}")
    
    params["apikey"] = TICKETMASTER_API_KEY
    
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
                print(f"✅ Found {len(events)} events\n")
                
                for i, event in enumerate(events[:3], 1):
                    print(f"Event {i}: {event.get('name')}")
                    
                    # Get date
                    dates_info = event.get("dates", {}).get("start", {})
                    date = dates_info.get("localDate", "N/A")
                    time = dates_info.get("localTime", "")
                    print(f"  📅 Date: {date} {time}")
                    
                    # Get venue
                    if "_embedded" in event and "venues" in event["_embedded"]:
                        venue = event["_embedded"]["venues"][0]
                        city = venue.get("city", {}).get("name", "")
                        state = venue.get("state", {}).get("stateCode", "")
                        print(f"  📍 Venue: {venue.get('name')} ({city}, {state})")
                    
                    # Get category/genre
                    classifications = event.get("classifications", [])
                    if classifications:
                        genre = classifications[0].get("genre", {}).get("name")
                        category = classifications[0].get("segment", {}).get("name")
                        print(f"  🎵 Category: {category}, Genre: {genre}")
                    
                    # Get price
                    price_ranges = event.get("priceRanges", [])
                    if price_ranges:
                        pr = price_ranges[0]
                        print(f"  💰 Price: ${pr.get('min')} - ${pr.get('max')} {pr.get('currency', 'USD')}")
                    print()
            else:
                print("⚠️  No events found")
                
    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP Error: {e.status_code}")
        print(f"Response: {e.response.text[:200]}")
    except Exception as e:
        print(f"❌ Error: {e}")

async def main():
    """Run multiple test scenarios"""
    
    if not TICKETMASTER_API_KEY:
        print("❌ Error: Ticketmaster API key not set!")
        return
    
    print(f"Testing Ticketmaster API Integration")
    print(f"API Key: {TICKETMASTER_API_KEY[:10]}...")
    
    # Test 1: Search by location
    await test_search(
        "Search for events in San Francisco, CA",
        {"city": "San Francisco", "stateCode": "CA", "size": 5}
    )
    
    # Test 2: Search by genre
    await test_search(
        "Search for Rock concerts",
        {"genreName": "Rock", "classificationName": "Music", "size": 5}
    )
    
    # Test 3: Search by keyword and location
    await test_search(
        "Search for comedy shows in New York",
        {"keyword": "comedy", "city": "New York", "size": 5}
    )
    
    # Test 4: Search by category (Sports)
    await test_search(
        "Search for sports events",
        {"classificationName": "Sports", "size": 5}
    )

if __name__ == "__main__":
    asyncio.run(main())
