import logging
import threading
import time
import random
import os
import psutil
from datetime import datetime

class ActiveContainer:
    """
    Keeps the container active by performing small periodic actions
    to prevent HuggingFace Spaces from marking it as inactive.
    """
    
    def __init__(self, interval_min=45, interval_max=90):
        """
        Initialize the container activity maintainer.
        
        Args:
            interval_min: Minimum seconds between activity
            interval_max: Maximum seconds between activity
        """
        self.interval_min = interval_min
        self.interval_max = interval_max
        self.stop_event = threading.Event()
        self.thread = None
        self.is_running = False
        self.last_activity = datetime.now()
        
    def start(self):
        """Start the activity thread."""
        if self.thread and self.thread.is_alive():
            return
            
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._activity_thread, daemon=True)
        self.thread.start()
        self.is_running = True
        logging.info("Container activity maintenance started")
        
    def stop(self):
        """Stop the activity thread."""
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self.thread.join(timeout=5)
            self.is_running = False
            logging.info("Container activity maintenance stopped")
            
    def record_activity(self):
        """Record that activity happened (called by main application code)."""
        self.last_activity = datetime.now()
            
    def _activity_thread(self):
        """Background thread that performs periodic actions to keep the container active."""
        while not self.stop_event.is_set():
            try:
                # Random interval helps avoid detection patterns
                interval = random.uniform(self.interval_min, self.interval_max)
                if self.stop_event.wait(timeout=interval):
                    break
                
                # Check if we need to perform activity (if no recent activity)
                seconds_since_activity = (datetime.now() - self.last_activity).total_seconds()
                if seconds_since_activity > 60:  # If no activity in the last minute
                    self._perform_activity()
                    
            except Exception as e:
                logging.warning(f"Error in container activity thread: {str(e)}")
                time.sleep(5)
                
    def _perform_activity(self):
        """
        Perform a minimal activity to keep the container active.
        This should use very minimal resources.
        """
        try:
            # Log memory usage periodically
            memory_info = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent(interval=0.1)
            
            # Create a small file operation
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            activity_file = "/tmp/container_activity.txt"
            
            with open(activity_file, "w") as f:
                f.write(f"Container active: {timestamp}\n")
                f.write(f"Memory used: {memory_info.percent}%\n")
                f.write(f"CPU used: {cpu_percent}%\n")
                
            # Read the file back to create I/O activity
            with open(activity_file, "r") as f:
                content = f.read()
                
            logging.debug(f"Container activity performed: {timestamp}")
            self.last_activity = datetime.now()
            
        except Exception as e:
            logging.debug(f"Failed to perform container activity: {str(e)}")