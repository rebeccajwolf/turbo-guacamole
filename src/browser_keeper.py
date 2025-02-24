import logging
import random
import time
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from typing import Optional
import threading
import queue

class BrowserKeeper:
    """Keeps browser connection alive during long sleep periods"""
    
    def __init__(self, webdriver, utils):
        self.webdriver = webdriver
        self.utils = utils
        self._stop_event = threading.Event()
        self._activity_thread: Optional[threading.Thread] = None
        self._error_queue = queue.Queue()
        
    def start(self):
        """Start the browser keeper thread"""
        if self._activity_thread is not None and self._activity_thread.is_alive():
            return
            
        self._stop_event.clear()
        self._activity_thread = threading.Thread(target=self._keep_alive_loop)
        self._activity_thread.daemon = True
        self._activity_thread.start()
        
    def stop(self):
        """Stop the browser keeper thread"""
        if self._activity_thread is None:
            return
            
        self._stop_event.set()
        self._activity_thread.join(timeout=5)
        self._activity_thread = None
        
        # Check for any errors that occurred
        try:
            error = self._error_queue.get_nowait()
            raise error
        except queue.Empty:
            pass
            
    def _keep_alive_loop(self):
        """Main loop that keeps the browser active"""
        try:
            current_url = self.webdriver.current_url
            while not self._stop_event.is_set():
                try:
                    # Perform minimal browser interaction
                    self._perform_activity()
                    
                    # Random sleep between activities (2-5 seconds)
                    time.sleep(random.uniform(2, 5))
                    
                except WebDriverException as e:
                    if "disconnected" in str(e).lower():
                        self._error_queue.put(e)
                        break
                    logging.debug(f"Handled WebDriver error: {str(e)}")
                    continue
                    
            # Restore original URL if possible
            try:
                self.webdriver.get(current_url)
            except Exception as e:
                logging.debug(f"Error restoring URL: {str(e)}")
                
        except Exception as e:
            self._error_queue.put(e)
            
    def _perform_activity(self):
        """Performs a random browser activity to maintain connection"""
        activities = [
            self._scroll_activity,
            self._tab_activity,
            self._focus_activity
        ]
        
        # Choose and execute a random activity
        random.choice(activities)()
        
    def _scroll_activity(self):
        """Scroll the page slightly"""
        try:
            self.webdriver.execute_script(
                "window.scrollTo(0, window.scrollY + arguments[0]);", 
                random.randint(-10, 10)
            )
        except Exception as e:
            logging.debug(f"Scroll activity error: {str(e)}")
            
    def _tab_activity(self):
        """Create and close a temporary tab"""
        try:
            # Store current handle
            current = self.webdriver.current_window_handle
            
            # Open new tab
            self.webdriver.switch_to.new_window('tab')
            
            # Switch back and close new tab
            self.webdriver.switch_to.window(current)
            
            # Close other tabs
            for handle in self.webdriver.window_handles:
                if handle != current:
                    self.webdriver.switch_to.window(handle)
                    self.webdriver.close()
                    
            # Switch back to original
            self.webdriver.switch_to.window(current)
            
        except Exception as e:
            logging.debug(f"Tab activity error: {str(e)}")
            
    def _focus_activity(self):
        """Focus on a random element"""
        try:
            elements = self.webdriver.find_elements(By.TAG_NAME, "div")
            if elements:
                element = random.choice(elements)
                self.webdriver.execute_script("arguments[0].focus();", element)
        except Exception as e:
            logging.debug(f"Focus activity error: {str(e)}")
