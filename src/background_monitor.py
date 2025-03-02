import logging
import threading
import time
from typing import Callable

class BackgroundMonitor:
    """
    A background monitor that continuously checks for stop signals
    and can terminate running jobs when needed.
    """
    
    def __init__(self, check_interval: float = 60.0):
        """
        Initialize the background monitor.
        
        Args:
            check_interval: How often to check for stop signals (in seconds)
        """
        self.check_interval = check_interval
        self.running = False
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.check_function = None
        self.action_function = None
    
    def start(self, check_function: Callable[[], bool], action_function: Callable[[], None]):
        """
        Start the background monitor.
        
        Args:
            check_function: Function that returns True if a stop signal is detected
            action_function: Function to call when a stop signal is detected
        """
        if self.running:
            return
            
        self.check_function = check_function
        self.action_function = action_function
        self.running = True
        self.stop_event.clear()
        
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="BackgroundMonitor"
        )
        self.monitor_thread.start()
        logging.info("Background monitor started")
    
    def stop(self):
        """Stop the background monitor."""
        if not self.running:
            return
            
        self.running = False
        self.stop_event.set()
        
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
            self.monitor_thread = None
        
        logging.info("Background monitor stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop that checks for stop signals."""
        while self.running and not self.stop_event.is_set():
            try:
                # Check if a stop signal is detected
                if self.check_function and self.check_function():
                    logging.info("Stop signal detected by background monitor")
                    
                    # Call the action function
                    if self.action_function:
                        try:
                            self.action_function()
                        except Exception as e:
                            logging.error(f"Error in action function: {str(e)}")
                    
                    # Break out of the loop after handling the stop signal
                    break
                
                # Wait for the next check interval or until stopped
                self.stop_event.wait(timeout=self.check_interval)
                
            except Exception as e:
                logging.error(f"Error in background monitor: {str(e)}")
                # Wait a bit before retrying to avoid tight error loops
                time.sleep(5)