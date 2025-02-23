import logging
import threading
import queue
import time
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.by import By

class BrowserKeeper:
    """Keeps browser connection alive during long sleep periods by creating and closing tabs"""
    
    def __init__(self, browser):
        self.browser = browser
        self.webdriver = browser.webdriver
        self.utils = browser.utils
        self._stop_event = threading.Event()
        self._activity_thread = None
        self._error_queue = queue.Queue()
        self._original_handle = None
        self._is_running = False
        
    def start(self):
        """Start the browser keeper thread"""
        if self._is_running:
            return
            
        self._stop_event.clear()
        try:
            # Store original handle and verify browser is responsive
            self._original_handle = self.webdriver.current_window_handle
            self._is_running = True
            
            self._activity_thread = threading.Thread(target=self._keep_alive_loop)
            self._activity_thread.daemon = True
            self._activity_thread.start()
            
        except Exception as e:
            logging.debug(f"Failed to start browser keeper: {str(e)}")
            self._is_running = False
            raise
        
    def stop(self):
        """Stop the browser keeper thread and cleanup"""
        if not self._is_running:
            return
            
        self._stop_event.set()
        self._is_running = False
        
        if self._activity_thread:
            self._activity_thread.join(timeout=5)
            self._activity_thread = None
        
        try:
            self._cleanup_tabs()
        except Exception as e:
            logging.debug(f"Error during final tab cleanup: {str(e)}")
        
        # Check for any errors that occurred
        try:
            error = self._error_queue.get_nowait()
            raise error
        except queue.Empty:
            pass
            
    def _cleanup_tabs(self):
        """Clean up any remaining tabs except original"""
        try:
            if not self._original_handle:
                return
                
            current_handles = self.webdriver.window_handles
            if self._original_handle in current_handles:
                for handle in current_handles:
                    if handle != self._original_handle:
                        try:
                            self.webdriver.switch_to.window(handle)
                            self.webdriver.close()
                        except Exception:
                            continue
                try:
                    self.webdriver.switch_to.window(self._original_handle)
                except Exception:
                    pass
        except Exception as e:
            logging.debug(f"Error cleaning up tabs: {str(e)}")
            
    def _keep_alive_loop(self):
        """Main loop that keeps the browser active by creating and closing tabs"""
        error_count = 0
        max_errors = 3
        
        while not self._stop_event.is_set() and error_count < max_errors:
            try:
                # Verify browser is still responsive
                _ = self.webdriver.current_window_handle
                
                # Create new tab
                self.webdriver.switch_to.new_window('tab')
                
                # Small delay
                time.sleep(1)
                
                # Close the tab
                self.webdriver.close()
                
                # Switch back to original tab
                self.webdriver.switch_to.window(self._original_handle)
                
                # Reset error count on successful operation
                error_count = 0
                
                # Delay between operations
                time.sleep(2)
                
            except WebDriverException as e:
                error_count += 1
                if "disconnected" in str(e).lower() or error_count >= max_errors:
                    self._error_queue.put(e)
                    break
                logging.debug(f"Handled WebDriver error: {str(e)}")
                time.sleep(1)
                continue
                
            except Exception as e:
                error_count += 1
                if error_count >= max_errors:
                    self._error_queue.put(e)
                    break
                logging.debug(f"Handled general error: {str(e)}")
                time.sleep(1)
