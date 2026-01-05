#!/usr/bin/env python3
"""
Test script to measure REopt API response times and determine optimal timeout values.
"""
import asyncio
import httpx
import time
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Test with a known job UUID
TEST_JOB_UUID = "1e186ce3-c020-47aa-b114-ecabdb080715"
API_KEY = os.getenv("NREL_API_KEY", "DEMO_KEY")

BASE_URL = "https://developer.nrel.gov/api/reopt/v3"
RESULTS_URL = f"{BASE_URL}/job/{TEST_JOB_UUID}/results"

async def test_timeout(timeout_value: float):
    """Test fetching results with a specific timeout."""
    print(f"\n{'='*60}")
    print(f"Testing with timeout: {timeout_value} seconds")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        timeout_config = httpx.Timeout(
            connect=30.0,
            read=timeout_value,
            write=30.0,
            pool=30.0
        )
        
        async with httpx.AsyncClient() as client:
            params = {
                "api_key": API_KEY,
                "format": "json"
            }
            
            print(f"Requesting: {RESULTS_URL}")
            print(f"Params: api_key={API_KEY[:10]}..., format=json")
            
            response = await client.get(
                RESULTS_URL,
                params=params,
                timeout=timeout_config
            )
            
            elapsed = time.time() - start_time
            
            print(f"✅ SUCCESS!")
            print(f"   Status Code: {response.status_code}")
            print(f"   Response Time: {elapsed:.2f} seconds")
            print(f"   Content Length: {len(response.content)} bytes ({len(response.content) / 1024 / 1024:.2f} MB)")
            print(f"   Content Type: {response.headers.get('content-type', 'unknown')}")
            
            # Try to parse JSON to verify it's valid
            try:
                data = response.json()
                print(f"   JSON Keys: {list(data.keys())[:10]}...")  # Show first 10 keys
                return True, elapsed, len(response.content)
            except json.JSONDecodeError as e:
                print(f"   ⚠️  Warning: Response is not valid JSON: {e}")
                return True, elapsed, len(response.content)
                
    except httpx.TimeoutException as e:
        elapsed = time.time() - start_time
        print(f"❌ TIMEOUT after {elapsed:.2f} seconds")
        print(f"   Error: {str(e)}")
        return False, elapsed, 0
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ ERROR after {elapsed:.2f} seconds")
        print(f"   Error Type: {type(e).__name__}")
        print(f"   Error Message: {str(e)}")
        return False, elapsed, 0

async def main():
    """Run timeout tests with increasing values."""
    print("REopt API Timeout Test")
    print(f"Testing job UUID: {TEST_JOB_UUID}")
    print(f"Results URL: {RESULTS_URL}")
    
    # Test with different timeout values
    timeout_values = [30, 60, 90, 120, 180, 240, 300]
    
    results = []
    
    for timeout in timeout_values:
        success, elapsed, size = await test_timeout(timeout)
        results.append({
            "timeout": timeout,
            "success": success,
            "elapsed": elapsed,
            "size_bytes": size
        })
        
        if success:
            print(f"\n✅ Found working timeout: {timeout} seconds")
            print(f"   Actual response time: {elapsed:.2f} seconds")
            print(f"   Recommended timeout: {max(timeout, int(elapsed * 1.5))} seconds (1.5x buffer)")
            break
        
        # Wait a bit between tests
        await asyncio.sleep(2)
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for result in results:
        status = "✅" if result["success"] else "❌"
        print(f"{status} Timeout: {result['timeout']:3d}s | "
              f"Elapsed: {result['elapsed']:6.2f}s | "
              f"Size: {result['size_bytes'] / 1024 / 1024:6.2f} MB")
    
    # Find optimal timeout
    successful_results = [r for r in results if r["success"]]
    if successful_results:
        best = successful_results[0]
        optimal = max(best["timeout"], int(best["elapsed"] * 1.5))
        print(f"\n💡 Recommended timeout: {optimal} seconds")
        print(f"   (Based on {best['elapsed']:.2f}s response time with 1.5x safety margin)")
    else:
        print("\n⚠️  No successful requests - may need to increase timeout further")

if __name__ == "__main__":
    asyncio.run(main())

