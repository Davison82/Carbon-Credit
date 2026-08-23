import pandas as pd
import sqlite3
import os
from datetime import date

# --- CONFIG ---
UNIVERSE_CSV = "tokenisation_universe.csv"
VERRA_CSV = "Verra Database 2026 04.csv"
DB_PATH = "onchain_audit.db"
OUTPUT_CSV = "mismatch_results.csv"

def load_verra_status(verra_csv):
    """
    Load project status and key metadata from Verra CSV.
    Returns dictionary: project_id -> status info
    """
    df = pd.read_csv(verra_csv, low_memory=False)

    id_col = next((c for c in df.columns 
                   if c.strip().lower() == "project id"), None)
    name_col = next((c for c in df.columns 
                     if "project name" in c.lower()), None)
    status_col = next((c for c in df.columns 
                       if "voluntary status" in c.lower()), None)
    country_col = next((c for c in df.columns 
                        if c.strip().lower() == "country"), None)
    type_col = next((c for c in df.columns 
                     if c.strip().lower() == "type"), None)
    issued_col = next((c for c in df.columns 
                       if "total credits" in c.lower() 
                       and "issued" in c.lower()), None)
    retired_col = next((c for c in df.columns 
                        if "total credits" in c.lower() 
                        and "retired" in c.lower()), None)

    verra_data = {}

    for _, row in df.iterrows():
        raw_id = str(row.get(id_col, "")).strip()
        if not raw_id.startswith("VCS"):
            continue

        project_id = "VCS-" + raw_id.replace("VCS", "")

        def safe_float(val):
            try:
                return float(str(val).replace(",", "").strip())
            except:
                return 0.0

        verra_data[project_id] = {
            "name": str(row.get(name_col, "")).strip() if name_col else "",
            "status": str(row.get(status_col, "")).strip() if status_col else "",
            "country": str(row.get(country_col, "")).strip() if country_col else "",
            "type": str(row.get(type_col, "")).strip() if type_col else "",
            "verra_issued": safe_float(row.get(issued_col, 0)) if issued_col else 0.0,
            "verra_retired": safe_float(row.get(retired_col, 0)) if retired_col else 0.0,
        }

    return verra_data

def run_mismatch_alert(universe_csv, verra_csv):
    """
    Core mismatch check:
    For every tokenised project, check Verra status.
    Flag anything that is not cleanly Registered.
    """
    print("\n" + "="*65)
    print("MISMATCH ALERT — VERRA STATUS vs ON-CHAIN ACTIVITY")
    print("Feature 1: Is this project tokenised and trading")
    print("           while Verra has flagged it?")
    print("="*65)

    if not os.path.exists(universe_csv):
        print(f"ERROR: Cannot find {universe_csv} — run MasterTokenisation.py first")
        return None

    if not os.path.exists(verra_csv):
        print(f"ERROR: Cannot find {verra_csv}")
        return None

    # Load data
    print("\nLoading data...")
    universe_df = pd.read_csv(universe_csv)
    verra_data = load_verra_status(verra_csv)
    today = date.today().isoformat()

    # Get unique VCS projects from universe
    vcs_tokens = universe_df[universe_df["standard"] == "VCS"].copy()
    vcs_tokens["project_id_clean"] = (
        "VCS-" + vcs_tokens["project_id"]
        .astype(str).str.split(".").str[0].str.strip()
    )

    unique_projects = vcs_tokens["project_id_clean"].unique()
    print(f"Tokenised VCS projects to check: {len(unique_projects)}")

    results = []
    findings = []
    red_count = 0
    green_count = 0
    unknown_count = 0

    print(f"\n{'Project ID':<12} {'Status':<30} {'Tokens':<8} "
          f"{'Retired (t)':<14} {'Chains':<20} {'Alert'}")
    print("-" * 100)

    for project_id in sorted(unique_projects):

        # Get blockchain summary for this project
        proj_tokens = vcs_tokens[
            vcs_tokens["project_id_clean"] == project_id
        ]

        token_count = len(proj_tokens)
        total_retired = proj_tokens["total_retired_tonnes"].sum()
        total_active = proj_tokens.get(
            "active_supply_tonnes", pd.Series([0])
        ).sum()
        chains = ", ".join(sorted(proj_tokens["chain"].unique()))
        pools = proj_tokens[
            ~proj_tokens["pool_assignment"].isin(
                ["ERC20 Raw TCO2", "Unknown", ""]
            )
        ]["pool_assignment"].unique()
        pool_str = ", ".join(pools) if len(pools) > 0 else "None"

        # Get Verra status
        verra_info = verra_data.get(project_id, None)

        if verra_info is None:
            status = "NOT IN VERRA DB"
            alert = "⚠️  UNKNOWN"
            certificate = "AMBER"
            unknown_count += 1
        else:
            status = verra_info["status"]
            verra_issued = verra_info["verra_issued"]
            verra_retired = verra_info["verra_retired"]

            # Determine alert level
            status_lower = status.lower()

            if "on hold" in status_lower:
                alert = "🔴 ON HOLD — STILL TRADING"
                certificate = "RED"
                red_count += 1
            elif "late to verify" in status_lower:
                alert = "🔴 LATE TO VERIFY — NO ISSUED CREDITS"
                certificate = "RED"
                red_count += 1
            elif "under review" in status_lower:
                alert = "🔴 UNDER REVIEW"
                certificate = "RED"
                red_count += 1
            elif "suspended" in status_lower:
                alert = "🔴 SUSPENDED"
                certificate = "RED"
                red_count += 1
            elif "registered" in status_lower:
                alert = "🟢 Clean"
                certificate = "GREEN"
                green_count += 1
            elif "completed" in status_lower:
                alert = "⚠️  COMPLETED — check if tokens valid"
                certificate = "AMBER"
                unknown_count += 1
            else:
                alert = f"⚠️  STATUS: {status[:30]}"
                certificate = "AMBER"
                unknown_count += 1

        print(f"{project_id:<12} {status[:28]:<30} {token_count:<8} "
              f"{total_retired:<14,.2f} {chains[:18]:<20} {alert}")

        results.append({
            "project_id": project_id,
            "project_name": verra_info["name"] if verra_info else "Unknown",
            "verra_status": status,
            "certificate": certificate,
            "token_count": token_count,
            "total_retired_tonnes": round(total_retired, 4),
            "total_active_tonnes": round(total_active, 4),
            "chains": chains,
            "pools": pool_str,
            "verra_issued": verra_info["verra_issued"] if verra_info else 0,
            "verra_retired": verra_info["verra_retired"] if verra_info else 0,
            "alert": alert,
            "date_checked": today
        })

        # Log finding if RED or AMBER
        if certificate in ["RED", "AMBER"]:
            findings.append({
                "project_id": project_id,
                "vintage": "All",
                "chain": chains,
                "finding_type": "Mismatch Alert",
                "finding_detail": f"Verra Status: {status}. "
                                  f"Tokens active on {chains}. "
                                  f"Pools: {pool_str}",
                "tonnes_affected": total_retired,
                "confidence": "Confirmed" if "on hold" in status.lower() 
                              or "late to verify" in status.lower() 
                              else "Signal",
                "certificate": certificate,
                "date_found": today,
                "verified_against": "Berkeley CSV",
                "notes": f"{token_count} token contracts. "
                         f"Retired: {total_retired:,.2f}t. "
                         f"Active: {total_active:,.2f}t"
            })

    # Export CSV
    results_df = pd.DataFrame(results)

    results_df["priority"] = results_df["total_retired_tonnes"].apply(
        lambda x: "Low Priority" if x == 0.0 else "Actionable"
    )

    results_df.to_csv(OUTPUT_CSV, index=False)
    print(f"  Actionable findings: {(results_df['priority']=='Actionable').sum()}")
    print(f"  Low priority (zero tonnes): {(results_df['priority']=='Low Priority').sum()}")

    # Summary
    print(f"\n{'='*65}")
    print(f"MISMATCH ALERT — COMPLETE")
    print(f"{'='*65}")
    print(f"Projects checked: {len(unique_projects)}")
    print(f"🔴 RED (non-Registered status): {red_count}")
    print(f"🟢 GREEN (Registered): {green_count}")
    print(f"⚠️  AMBER (Unknown/Completed): {unknown_count}")

    if findings:
        print(f"\n🔴 RED / ⚠️  AMBER FINDINGS:")
        for f in findings:
            if f["certificate"] == "RED":
                print(f"\n  {f['project_id']} — {f['finding_detail'][:60]}")
                print(f"  Tonnes retired on-chain: {f['tonnes_affected']:,.2f}t")
                print(f"  Confidence: {f['confidence']}")

    print(f"\nResults exported to {OUTPUT_CSV}")
    print(f"{'='*65}\n")

    return findings

def update_database(findings):
    """Write Mismatch Alert findings to the database"""
    if not findings:
        return

    if not os.path.exists(DB_PATH):
        print("WARNING: Database not found — run BuildDatabase.py first")
        return

    conn = sqlite3.connect(DB_PATH)

    # Remove previous mismatch alert findings
    conn.execute("""
        DELETE FROM audit_findings 
        WHERE finding_type = 'Mismatch Alert'
    """)

    # Insert new findings
    conn.executemany("""
        INSERT INTO audit_findings
        (project_id, vintage, chain, finding_type,
         finding_detail, tonnes_affected, confidence,
         certificate, date_found, verified_against, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, [(
        f["project_id"], f["vintage"], f["chain"],
        f["finding_type"], f["finding_detail"],
        f["tonnes_affected"], f["confidence"],
        f["certificate"], f["date_found"],
        f["verified_against"], f["notes"]
    ) for f in findings])

    conn.commit()
    print(f"✅ {len(findings)} Mismatch Alert findings written to database")

    # Verify VCS-981 is now in the database
    result = conn.execute("""
        SELECT project_id, finding_type, certificate, notes
        FROM audit_findings
        WHERE project_id = 'VCS-981'
    """).fetchall()

    if result:
        print(f"\n✅ VCS-981 confirmed in database:")
        for r in result:
            print(f"   {r[0]} | {r[1]} | {r[2]}")
            print(f"   {r[3]}")

    conn.close()

# --- MAIN ---
if __name__ == "__main__":
    findings = run_mismatch_alert(UNIVERSE_CSV, VERRA_CSV)
    if findings:
        update_database(findings)
