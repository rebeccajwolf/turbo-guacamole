import logging
import time
import threading
from datetime import datetime

class ExtendedWait:
    """
    Provides a way to wait for long periods while keeping the browser active.
    Replaces simple time.sleep() calls that might cause timeout issues.
    """
    
    @staticmethod
    def sleep(seconds, browser_instance=None, callback=None):
        """
        Sleep for the specified number of seconds while keeping browser active.
        
        Args:
            seconds: Number of seconds to sleep
            browser_instance: Optional browser instance to keep active
            callback: Optional function to call periodically during sleep
        """
        if seconds <= 5:
            # For short waits, use standard sleep
            time.sleep(seconds)
            return
            
        # For longer waits, break it into chunks and keep activity
        start_time = datetime.now()
        end_time = start_time + seconds * time.timedelta(seconds=1)
        
        chunk_size = min(30, seconds)  # Maximum 30 second chunks
        remaining = seconds
        
        logging.debug(f"Extended wait started for {seconds} seconds")
        
        while remaining > 0:
            # Calculate next chunk duration
            chunk = min(chunk_size, remaining)
            
            # Sleep for this chunk
            time.sleep(chunk)
            
            # If browser instance provided, ensure it's active
            if browser_instance and hasattr(browser_instance, "utils"):
                try:
                    # Perform a lightweight browser action
                    browser_instance.webdriver.execute_script("return document.title")
                    logging.debug("Browser activity during extended wait")
                except Exception as e:
                    logging.debug(f"Failed browser activity during wait: {str(e)}")
            
            # If callback provided, call it
            if callback:
                try:
                    callback()
                except Exception as e:
                    logging.warning(f"Error in wait callback: {str(e)}")
            
            # Update remaining time
            elapsed = (datetime.now() - start_time).total_seconds()
            remaining = seconds - elapsed
            
            if remaining <= 0:
                break
                
        logging.debug(f"Extended wait completed after {(datetime.now() - start_time).total_seconds()} seconds")