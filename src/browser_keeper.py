import logging
import threading
import queue
import time
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

from src.browser import Browser

class BrowserKeeper:
    """Keeps browser connection alive during long sleep periods by creating and closing tabs"""
    
    def __init__(self, browser: Browser):
        self.browser = browser
        self.webdriver = browser.webdriver
        self.utils = browser.utils
        self._stop_event = threading.Event()
        self._activity_thread = None
        self._error_queue = queue.Queue()
        self._original_handle = None
        
    def start(self):
        """Start the browser keeper thread"""
        if self._activity_thread is not None and self._activity_thread.is_alive():
            return
            
        self._stop_event.clear()
        self._original_handle = self.webdriver.current_window_handle
        self._activity_thread = threading.Thread(target=self._keep_alive_loop)
        self._activity_thread.daemon = True
        self._activity_thread.start()
        
    def stop(self):
        """Stop the browser keeper thread and cleanup"""
        if self._activity_thread is None:
            return
            
        self._stop_event.set()
        self._activity_thread.join(timeout=5)
        self._activity_thread = None
        
        # Clean up any remaining tabs except original
        try:
            if self._original_handle:
                for handle in self.webdriver.window_handles:
                    if handle != self._original_handle:
                        self.webdriver.switch_to.window(handle)
                        self.webdriver.close()
                self.webdriver.switch_to.window(self._original_handle)
        except Exception as e:
            logging.debug(f"Error during tab cleanup: {str(e)}")
        
        # Check for any errors that occurred
        try:
            error = self._error_queue.get_nowait()
            raise error
        except queue.Empty:
            pass
            
    def _keep_alive_loop(self):
        """Main loop that keeps the browser active by creating and closing tabs"""
        try:
            while not self._stop_event.is_set():
                try:
                    # Create new tab
                    self.webdriver.switch_to.new_window('tab')
                    new_handle = self.webdriver.current_window_handle
                    
                    # Small delay
                    time.sleep(2)
                    
                    # Close the tab
                    self.webdriver.close()
                    
                    # Switch back to original tab
                    self.webdriver.switch_to.window(self._original_handle)
                    
                    # Random delay between tab operations (3-5 seconds)
                    time.sleep(3)
                    
                except WebDriverException as e:
                    if "disconnected" in str(e).lower():
                        self._error_queue.put(e)
                        break
                    logging.debug(f"Handled WebDriver error: {str(e)}")
                    continue
                    
        except Exception as e:
            self._error_queue.put(e)
