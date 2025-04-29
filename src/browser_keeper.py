import logging
import threading
import time
import random
from selenium.common.exceptions import WebDriverException

class BrowserKeeper:
    """
    Class to keep browser sessions alive during long-running tasks.
    Prevents container timeouts by maintaining activity.
    """
    
    def __init__(self, webdriver, interval=30):
        """
        Initialize BrowserKeeper.
        
        Args:
            webdriver: The webdriver instance to keep alive
            interval: How often to perform the keepalive action (seconds)
        """
        self.webdriver = webdriver
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None
        self.is_running = False
        
    def start(self):
        """Start the keeper thread."""
        if self.thread and self.thread.is_alive():
            return
            
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._keeper_thread, daemon=True)
        self.thread.start()
        self.is_running = True
        logging.debug("BrowserKeeper started")
        
    def stop(self):
        """Stop the keeper thread."""
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self.thread.join(timeout=10)
            self.is_running = False
            logging.debug("BrowserKeeper stopped")
            
    def _keeper_thread(self):
        """Background thread that performs periodic actions to keep the browser active."""
        while not self.stop_event.is_set():
            try:
                # Wait for random time between 20-40 seconds
                # This randomization helps avoid detection patterns
                wait_time = random.uniform(20, 40)
                if self.stop_event.wait(timeout=wait_time):
                    break
                    
                # Only perform action if webdriver is still active
                if self._is_driver_active():
                    self._perform_keepalive_action()
            except Exception as e:
                logging.warning(f"Error in browser keeper thread: {str(e)}")
                # If we encounter an error, wait a bit before trying again
                time.sleep(5)
                
    def _is_driver_active(self):
        """Check if the webdriver session is still active."""
        try:
            # Lightweight check to see if driver is responding
            current_url = self.webdriver.current_url
            return True
        except (WebDriverException, AttributeError):
            return False
            
    def _perform_keepalive_action(self):
        """
        Perform a small action to keep the browser active.
        Uses minimal resources to avoid impacting performance.
        """
        try:
            # Get the current URL to check connection
            current_url = self.webdriver.current_url
            
            # Execute a lightweight JavaScript action
            # This simulates user activity without changing page state
            self.webdriver.execute_script("""
                // Create minimal activity that doesn't affect page
                let now = Date.now();
                return now;
            """)
            
            logging.debug(f"BrowserKeeper: Keepalive action performed on {current_url}")
        except Exception as e:
            logging.debug(f"BrowserKeeper: Failed to perform keepalive: {str(e)}")