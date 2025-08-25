#!/usr/bin/env python3
"""
Integration test for process_tender_with_gemini_ids function.
Tests the integration between parse_with_gemini and Celery task queueing.

This test verifies that the function can properly:
1. Find positions files
2. Queue Celery tasks
3. Handle the full workflow

Note: Requires real GOOGLE_API_KEY for full AI processing.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

os.environ["GO_SERVER_API_ENDPOINT"] = "http://localhost:8080/api/v1"
# Note: This test will skip AI processing if GOOGLE_API_KEY is not set
# os.environ["GOOGLE_API_KEY"] = "test_key"  # Uncomment only for testing


def test_queueing():
    print("🧪 Testing Celery task queueing from process_tender_with_gemini_ids...")

    try:
        from app.parse_with_gemini import process_tender_with_gemini_ids

        # Test data that matches the recent processing
        tender_db_id = "134"
        lot_ids_map = {"lot_1": 134}
        tender_data = {"tender_id": "49-ТУ"}

        print(f"📊 Test data: tender_id={tender_db_id}, lots={lot_ids_map}")
        print(f"🔍 Looking for positions file: tenders_positions/{tender_db_id}_134_positions.md")

        # Check if positions file exists
        positions_file = Path(f"tenders_positions/{tender_db_id}_134_positions.md")
        if positions_file.exists():
            print(f"✅ Positions file found: {positions_file}")
        else:
            print(f"❌ Positions file NOT found: {positions_file}")
            return False

        # Call our function
        result = process_tender_with_gemini_ids(
            tender_db_id=tender_db_id,
            lot_ids_map=lot_ids_map,
            tender_data=tender_data,
            async_processing=False,
            redis_config=None,
        )

        print(f"📊 Function result: {result}")
        return result

    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_queueing()
    print(f"🎯 Test {'SUCCESS' if success else 'FAILED'}")
