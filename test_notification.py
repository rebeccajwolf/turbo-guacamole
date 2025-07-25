#!/usr/bin/env python3
"""
Test script for Discord notification functionality with IP workaround
"""

import sys
import logging
import traceback
from pathlib import Path

# Add src to path so we can import utils
sys.path.append(str(Path(__file__).parent / "src"))

from src.utils import sendNotification, CONFIG

def setup_test_logging():
    """Setup basic logging for testing"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )

def test_basic_notification():
    """Test basic notification sending"""
    print("🧪 Testing basic notification...")
    
    try:
        sendNotification(
            title="Test Notification",
            body="This is a basic test notification from the Microsoft Rewards bot."
        )
        print("✅ Basic notification test completed")
    except Exception as e:
        print(f"❌ Basic notification test failed: {str(e)}")
        traceback.print_exc()

def test_long_message_notification():
    """Test notification with long message that needs splitting"""
    print("\n🧪 Testing long message notification...")
    
    long_message = """
This is a very long test message that should trigger the message splitting functionality.

Here's some sample data that might be included in a real notification:

Account Details:
- Email: test@example.com
- Points Earned: 1,250
- Total Points: 15,750
- Goal Progress: 78.5%

Recent Activities:
- Daily Set: Completed ✅
- Punch Cards: 3/5 completed
- Desktop Searches: 30/30 completed
- Mobile Searches: 20/20 completed
- Read to Earn: 3 articles completed

Error Log (if any):
No errors detected in this run.

System Information:
- Browser: Chrome (headless)
- Platform: Linux
- Container: Hugging Face Spaces
- IP Workaround: Active for Discord notifications

This message is intentionally long to test the message splitting functionality
that breaks messages into multiple parts when they exceed Discord's character limit.

Additional padding text to make this even longer...
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor 
incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis 
nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.

More padding...
Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore 
eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, 
sunt in culpa qui officia deserunt mollit anim id est laborum.

Even more content to ensure we hit the character limit...
Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium 
doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore 
veritatis et quasi architecto beatae vitae dicta sunt explicabo.
    """
    
    try:
        sendNotification(
            title="Long Message Test",
            body=long_message.strip()
        )
        print("✅ Long message notification test completed")
    except Exception as e:
        print(f"❌ Long message notification test failed: {str(e)}")
        traceback.print_exc()

def test_exception_notification():
    """Test notification with exception"""
    print("\n🧪 Testing exception notification...")
    
    try:
        # Create a test exception
        try:
            result = 10 / 0  # This will raise ZeroDivisionError
        except ZeroDivisionError as e:
            sendNotification(
                title="Exception Test",
                body="This is a test notification with an exception attached.",
                e=e
            )
        print("✅ Exception notification test completed")
    except Exception as e:
        print(f"❌ Exception notification test failed: {str(e)}")
        traceback.print_exc()

def test_code_block_notification():
    """Test notification with code blocks"""
    print("\n🧪 Testing code block notification...")
    
    code_message = """
Test notification with code blocks:

Here's some Python code:
```python
def test_function():
    print("Hello, World!")
    return True

# This is a comment
result = test_function()
```

And here's some JSON data:
```json
{
    "account": "test@example.com",
    "points": 1250,
    "activities": {
        "daily_set": true,
        "searches": {
            "desktop": 30,
            "mobile": 20
        }
    }
}
```

This tests the code block preservation functionality.
    """
    
    try:
        sendNotification(
            title="Code Block Test",
            body=code_message.strip()
        )
        print("✅ Code block notification test completed")
    except Exception as e:
        print(f"❌ Code block notification test failed: {str(e)}")
        traceback.print_exc()


def test_config_check():
    """Check if configuration is properly loaded"""
    print("\n🧪 Checking configuration...")
    
    try:
        print(f"Apprise enabled: {CONFIG.apprise.enabled}")
        print(f"Number of notification URLs: {len(CONFIG.apprise.urls) if CONFIG.apprise.urls else 0}")
        
        if CONFIG.apprise.urls:
            for i, url in enumerate(CONFIG.apprise.urls, 1):
                # Only show first 20 characters for security
                url_preview = url[:20] + "..." if len(url) > 20 else url
                print(f"URL {i}: {url_preview}")
                
                if url.startswith("discord://"):
                    print(f"  → Discord webhook detected (will use IP workaround)")
        else:
            print("⚠️  No notification URLs configured")
            print("   Add Discord webhook URLs to config.yaml under apprise.urls")
            
    except Exception as e:
        print(f"❌ Configuration check failed: {str(e)}")
        traceback.print_exc()

def main():
    """Run all notification tests"""
    print("🚀 Starting Discord Notification Tests")
    print("=" * 60)
    
    # Setup logging
    setup_test_logging()
    
    # Check configuration first
    test_config_check()
    
    # Only run notification tests if URLs are configured
    if not CONFIG.apprise.enabled:
        print("\n⚠️  Apprise is disabled in configuration")
        print("   Enable it in config.yaml to test notifications")
        return
        
    if not CONFIG.apprise.urls:
        print("\n⚠️  No notification URLs configured")
        print("   Add Discord webhook URLs to config.yaml to test notifications")
        return
    
    # Run all tests
    test_basic_notification()
    test_long_message_notification()
    test_exception_notification()
    test_code_block_notification()
    
    print("\n" + "=" * 60)
    print("🏁 All tests completed!")
    print("\nCheck your Discord channel to see if notifications were received.")
    print("If notifications failed, check the logs above for error details.")

if __name__ == "__main__":
    main()