import requests
import json

API_KEY = "d562d03c4b1c92f7e710eff9b01cc6d0"

SUBGRAPH_ID = "FU5APMSSCqcRy9jy56aXJiGV3PQmFQHg2tzukvSJBgwW"

url = (
    f"https://gateway-arbitrum.network.thegraph.com/api/"
    f"{API_KEY}/subgraphs/id/{SUBGRAPH_ID}"
)

headers = {"Content-Type": "application/json"}

# Connectivity test
test_query = """
{
  __typename
}
"""

try:
    response = requests.post(
        url,
        json={"query": test_query},
        headers=headers,
        timeout=20,
    )

    print("=" * 80)
    print("STATUS:", response.status_code)
    print("=" * 80)

    try:
        print(json.dumps(response.json(), indent=2))
    except Exception:
        print(response.text)

    # Query TCO2 tokens
    query = """
    {
      tco2Tokens(first: 5) {
        id
        name
        symbol
      }
    }
    """

    print("\n" + "=" * 80)
    print("RUNNING TCO2 QUERY")
    print("=" * 80)

    response = requests.post(
        url,
        json={"query": query},
        headers=headers,
        timeout=20,
    )

    try:
        print(json.dumps(response.json(), indent=2))
    except Exception:
        print(response.text)

except Exception as e:
    print("ERROR:", e)
