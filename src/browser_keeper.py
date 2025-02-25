import logging
import threading
import queue
import time
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

class BrowserKeeper:
    """Keeps browser connection alive during long sleep periods using Chrome DevTools Protocol"""
    
    def __init__(self, browser):
        self.browser = browser
        self.webdriver = browser.webdriver
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
            
            # Disable page lifecycle controls
            self.webdriver.execute_cdp_cmd('Page.enable', {})
            self.webdriver.execute_cdp_cmd('Page.setBypassCSP', {'enabled': True})
            
            # Keep CPU priority
            self.webdriver.execute_cdp_cmd('Emulation.setCPUThrottlingRate', {'rate': 1})
            
            # Start keeper thread
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
            # Re-enable default CPU throttling
            self.webdriver.execute_cdp_cmd('Emulation.setCPUThrottlingRate', {'rate': 1})
        except Exception as e:
            logging.debug(f"Error resetting CPU throttling: {str(e)}")
            
        try:
            error = self._error_queue.get_nowait()
            raise error
        except queue.Empty:
            pass
            
    def _keep_alive_loop(self):
        """Main loop that keeps the browser active"""
        error_count = 0
        max_errors = 3
        check_interval = 10  # Check every 10 seconds
        
        while not self._stop_event.is_set() and error_count < max_errors:
            try:
                # Send periodic CDP commands to keep connection alive
                self.webdriver.execute_cdp_cmd('Network.enable', {})
                self.webdriver.execute_cdp_cmd('Network.getResponseBody', {'requestId': '1'})
                
                # Execute simple JS to keep page active
                self.webdriver.execute_script("window.performance.memory")
                
                # Reset error count on success
                error_count = 0
                
                # Sleep in shorter intervals to check stop event
                for _ in range(check_interval * 2):
                    if self._stop_event.is_set():
                        break
                    time.sleep(0.5)
                    
            except Exception as e:
                error_count += 1
                if error_count >= max_errors:
                    self._error_queue.put(e)
                    break
                logging.debug(f"Handled error in keep alive loop: {str(e)}")
                time.sleep(1)