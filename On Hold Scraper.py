import pandas as pd
import requests
import time

API_KEY = "d562d03c4b1c92f7e710eff9b01cc6d0"
SUBGRAPH_URL = f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/FU5APMSSCqcRy9jy56aXJiGV3PQmFQHg2tzukvSJBgwW"

def check_project_tokens(project_id):
    query = """
    {
      tco2Tokens(where: {symbol_contains: "VCS-%s"}) {
        id
        name
        symbol
        totalSupply
      }
    }
    """ % project_id
    
    response = requests.post(
        SUBGRAPH_URL,
        json={"query": query},
        headers={"Content-Type": "application/json"}
    )
    data = response.json()
    tokens = data.get("data", {}).get("tco2Tokens", [])
    return tokens

# Load On Hold projects
df = pd.read_csv("on_hold_audit_queue.csv")
id_col = next((c for c in df.columns if "project id" in c.lower()), None)
name_col = next((c for c in df.columns if "project name" in c.lower()), None)

results = []
findings = []

print(f"{'Project ID':<12} {'Name':<35} {'Tokens Found':<8} {'Total Active Supply'}")
print("-" * 80)

for _, row in df.iterrows():
    raw_id = str(row[id_col]).strip()
    numeric_id = raw_id.replace("VCS-", "").strip()
    name = str(row[name_col])[:33] if name_col else "N/A"
    
    tokens = check_project_tokens(numeric_id)
    
    # Filter out zero supply tokens
    active_tokens = [t for t in tokens if int(t.get("totalSupply", 0)) > 0]
    total_supply = sum(int(t.get("totalSupply", 0)) for t in active_tokens) / 1e18
    
    if active_tokens:
        flag = " *** FINDING ***"
        print(f"{raw_id:<12} {name:<35} {len(active_tokens):<8} {total_supply:,.2f}{flag}")
        findings.append({"project_id": raw_id, "name": name, "tokens": active_tokens})
    else:
        print(f"{raw_id:<12} {name:<35} {'0':<8} No active tokens")
    
    results.append({
        "project_id": raw_id,
        "name": name,
        "active_tokens": len(active_tokens),
        "total_supply_tonnes": total_supply
    })
    
    time.sleep(0.5)

# Export
pd.DataFrame(results).to_csv("subgraph_screen_results.csv", index=False)

print(f"\n{'='*80}")
print(f"COMPLETE — {len(findings)} On Hold projects with active tokens")
for f in findings:
    print(f"  {f['project_id']}")
