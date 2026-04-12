# tests/test_product_hunt.py
import asyncio
import json
import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport

# Add project root to path for imports.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load environment variables from .env file in the project root
dotenv_path = Path(__file__).parent.parent / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)
    print(f"Loaded environment variables from: {dotenv_path}")
else:
    print(
        f"Warning: .env file not found at {dotenv_path}. Environment variables might be missing."
    )

# --- Configuration ---
PRODUCT_HUNT_API_URL = "https://api.producthunt.com/v2/api/graphql"

# --- Get Credentials ---
dev_token = os.environ.get("PRODUCT_HUNT_DEVELOPER_TOKEN")

if not dev_token:
    print("Error: Missing required environment variable.")
    print(
        "Please ensure PRODUCT_HUNT_DEVELOPER_TOKEN is set in your .env file or environment."
    )
    sys.exit(1)


# --- Async Function for GraphQL Query (Modified for Dev Token) ---
async def fetch_daily_products(token: str) -> dict | None:
    """Product Hunt API v2 (GraphQL) を使用して今日のトップ製品を取得する。"""
    print("\nAttempting to fetch daily products via GraphQL using Developer Token...")
    headers = {
        "Authorization": f"Bearer {token}",  # Use the passed developer token
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    }
    transport = AIOHTTPTransport(url=PRODUCT_HUNT_API_URL, headers=headers)
    client = Client(transport=transport, fetch_schema_from_transport=False)

    query = gql("""
        query DailyPosts($postedBefore: DateTime, $postedAfter: DateTime) {
          posts(order: VOTES, postedBefore: $postedBefore, postedAfter: $postedAfter, first: 10) { # Fetch fewer posts for test
            edges {
              node {
                id
                name
                tagline
                description
                website
                url # PH URL
                votesCount
                thumbnail {
                  url
                }
              }
            }
            totalCount
          }
        }
    """)
    now_utc = datetime.utcnow()
    # Calculate start and end of the *previous* UTC day
    today_start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start_utc = today_start_utc - timedelta(days=1)
    yesterday_end_utc = today_start_utc - timedelta(
        microseconds=1
    )  # End of previous day

    variables = {
        "postedAfter": yesterday_start_utc.isoformat() + "Z",
        "postedBefore": yesterday_end_utc.isoformat() + "Z",
    }

    try:
        print(
            f"Fetching daily top products from Product Hunt API (since {yesterday_start_utc.isoformat()}Z)..."
        )
        async with client as session:  # Use context manager for gql client session
            # Pass query as the first positional argument
            data = await session.execute(query, variable_values=variables)
        print("Successfully fetched data from Product Hunt GraphQL API.")
        return data
    except Exception as e:
        print(f"Error fetching data from Product Hunt GraphQL API: {e}")
        traceback.print_exc()
        return None


# --- Main Execution (Modified for Dev Token) ---
def main():
    """
    Runs the Product Hunt API calls directly for testing using Developer Token.
    """
    print("\nStarting Product Hunt API direct test (using Developer Token)...")
    print("=" * 50)
    print(f"Product Hunt Developer Token: {'Set' if dev_token else 'Not Set'}")
    print("-" * 50)

    # Run the async GraphQL fetch function using the developer token
    graphql_data = asyncio.run(fetch_daily_products(dev_token))

    if graphql_data:
        print("\n--- Fetched GraphQL Data ---")
        # Pretty print the first few results for verification
        try:
            posts = graphql_data.get("posts", {}).get("edges", [])
            print(f"Total posts fetched (max 10): {len(posts)}")
            for i, edge in enumerate(posts[:3]):  # Print details of first 3
                node = edge.get("node", {})
                print(f"\nProduct {i + 1}:")
                print(f"  Name: {node.get('name')}")
                print(f"  Votes: {node.get('votesCount')}")
                print(f"  Tagline: {node.get('tagline')}")
                print(f"  Website: {node.get('website')}")
                print(f"  PH URL: {node.get('url')}")
        except Exception as e:
            print(f"Error processing GraphQL data for display: {e}")
            print("Raw data:")
            print(json.dumps(graphql_data, indent=2))  # Print raw if processing fails

    else:
        print("\nNo data received from GraphQL query or an error occurred.")

    print("\n" + "=" * 50)
    print("Direct API test finished.")


if __name__ == "__main__":
    main()
