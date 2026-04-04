"""
Setup script for Strategic Context database.
Run once to add properties and seed entries.
Idempotent — safe to re-run.
"""

from notion_client import update_database, query_database, parse_page_properties, create_page, build_page_properties
from config import STRATEGIC_CONTEXT_DB_ID
import time

def main():
    print("=== Strategic Context Setup ===\n")

    if not STRATEGIC_CONTEXT_DB_ID:
        print("Error: STRATEGIC_CONTEXT_DB_ID not set in .env")
        return

    print(f"Using database: {STRATEGIC_CONTEXT_DB_ID}\n")

    # --- PHASE 1: Add properties (idempotent) ---
    print("Step 1: Adding properties to database...")
    try:
        update_database(STRATEGIC_CONTEXT_DB_ID, {
            "Category": {
                "select": {
                    "options": [
                        {"name": "Framework", "color": "blue"},
                        {"name": "Entity", "color": "green"},
                        {"name": "India Context", "color": "yellow"},
                        {"name": "Noise Filter", "color": "red"},
                        {"name": "Signal Indicator", "color": "purple"},
                    ]
                }
            },
            "Content": {"rich_text": {}},
            "Not Using Anymore": {"checkbox": {}},
        })
        print("  Properties added successfully.")
    except Exception as e:
        err_msg = str(e).lower()
        if "already exists" in err_msg or "database_identifier_in_use" in err_msg or "conflict" in err_msg:
            print("  Properties already exist — skipping PATCH.")
        else:
            print(f"  PATCH failed: {e}")
            raise

    print()

    # --- PHASE 2: Seed entries (idempotent) ---
    print("Step 2: Seeding entries...")

    entries = [
        {
            "name": "Four Schools of Physical AI",
            "category": "Framework",
            "content": "School 1: Simulation-first (NVIDIA Isaac, digital twins → physical deployment). School 2: Data-first (Tesla FSD approach, massive real-world data collection). School 3: Foundation model (Physical Intelligence π, general-purpose robot models). School 4: Vertical-specific (Halter for livestock, specialized closed-loop systems)."
        },
        {
            "name": "GTM Plays",
            "category": "Framework",
            "content": "Play 1: Pick-and-place automation for Indian manufacturing. Play 2: Autonomous inspection and quality control. Play 3: Last-mile logistics robotics. Play 4: Agriculture and food processing automation. Play 5: Construction site automation. Play 6: Warehouse robotics-as-a-service."
        },
        {
            "name": "Tech Stack",
            "category": "Framework",
            "content": "9-layer tech stack from Layer 1 (Sensors) through Layer 9 (Application). When an article mentions a component, note which layer it maps to."
        },
        {
            "name": "High Priority Companies",
            "category": "Entity",
            "content": "NVIDIA, Boston Dynamics, Physical Intelligence (π), Halter, Tesla (FSD/Optimus), Agility Robotics, Figure AI, 1X Technologies, Covariant, Symbotic, Locus Robotics"
        },
        {
            "name": "India Companies",
            "category": "Entity",
            "content": "Addverb Technologies, Gridbots, Systemantics, Miko Robotics, Invento Robotics, hi-Tech Robotic Systemz"
        },
        {
            "name": "Investors",
            "category": "Entity",
            "content": "Andreessen Horowitz, Khosla Ventures, Sequoia, Tiger Global, Accel India, Kalaari Capital"
        },
        {
            "name": "Government Bodies",
            "category": "Entity",
            "content": "DPIIT, MoRTH, NITI Aayog, BIS (for robotics standards)"
        },
        {
            "name": "India Context",
            "category": "India Context",
            "content": "Robot density: ~7 per 10,000 manufacturing workers (global avg ~162). NDAA Section 889 creates opportunity for non-Chinese robotics suppliers. MoRTH March 2024 directive on autonomous vehicle testing. Closed-loop data flywheel is the core defensible moat thesis. India manufacturing labor cost advantage makes ROI calculation different from US/China."
        },
        {
            "name": "Noise Filters",
            "category": "Noise Filter",
            "content": "Generic 'AI will change everything' opinion pieces. AI ethics debates without policy/regulatory action. Pure software AI (LLMs, chatbots) with no physical-world component. Social media influencer hot takes. Product reviews of consumer gadgets."
        },
        {
            "name": "High Signal Indicators",
            "category": "Signal Indicator",
            "content": "Any funding round >$10M in Physical AI/robotics. Government policy directly affecting robotics deployment. New partnerships between tracked companies. Research breakthroughs in sim-to-real transfer, manipulation, or locomotion. India-specific robotics infrastructure developments. Competitive moves by School 1-4 companies."
        },
    ]

    for entry in entries:
        # Check if entry already exists by Name
        try:
            existing = query_database(
                STRATEGIC_CONTEXT_DB_ID,
                filter={"property": "Name", "title": {"equals": entry["name"]}},
                page_size=1,
            )
            if existing:
                print(f"  Skipping (exists): {entry['name']}")
                continue

            props = build_page_properties(
                title=entry["name"],
                title_property_name="Name",
                select_fields={"Category": entry["category"]},
                rich_text_fields={"Content": entry["content"]},
            )
            create_page(STRATEGIC_CONTEXT_DB_ID, props)
            print(f"  Added: {entry['name']}")
            time.sleep(0.35)
        except Exception as e:
            print(f"  Failed to add '{entry['name']}': {e}")

    print("\n=== Strategic Context Setup Complete ===")


if __name__ == "__main__":
    main()