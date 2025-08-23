#!/usr/bin/env python3
"""
Test script to verify AI results flow.
Creates a minimal positions file and triggers AI processing to test POST to Go.
"""

import os
import tempfile

# Set up environment
os.environ["GO_SERVER_API_ENDPOINT"] = "http://localhost:8080/api/v1"
os.environ["GOOGLE_API_KEY"] = "test_key_for_demo"  # Will fail but should trigger POST attempt

def test_ai_task_trigger():
    """Test that AI task gets queued and attempts to POST results."""
    
    # Create a test positions file
    with tempfile.NamedTemporaryFile(mode='w', suffix='_positions.md', delete=False) as f:
        f.write("""
# Тендер: Тестовый тендер
## Лот 1: Земляные работы

### Позиции:
1. Разработка котлована - 1000 м³
2. Устройство временных ограждений - 100 м
3. Планировка территории - 500 м²
        """)
        positions_file = f.name
    
    try:
        # Import and trigger the task
        from app.workers.gemini.tasks import process_tender_positions
        
        print(f"🚀 Triggering AI task with file: {positions_file}")
        
        # Queue the task
        task = process_tender_positions.delay(
            tender_id="134",
            lot_id="134", 
            positions_file_path=positions_file,
            api_key="test_key_for_demo"
        )
        
        print(f"✅ Task queued with ID: {task.id}")
        print("📝 Check worker logs for POST attempt to:")
        print("   http://localhost:8080/api/v1/tenders/134/lots/134/ai-results")
        print("💾 If Go is down, check: pending_sync_json/ai_results/134_134.json")
        
        return task.id
        
    finally:
        # Clean up
        try:
            os.unlink(positions_file)
        except Exception:
            pass

if __name__ == "__main__":
    test_ai_task_trigger()
