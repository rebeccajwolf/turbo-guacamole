import logging
import threading
import queue
import time
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.by import By

class BrowserKeeper:
	"""Keeps browser connection alive during long sleep periods by loading Reddit in background"""
	
	def __init__(self, browser):
		self.browser = browser
		self.webdriver = browser.webdriver
		self._stop_event = threading.Event()
		self._activity_thread = None
		self._error_queue = queue.Queue()
		self._original_handle = None
		self._activity_handle = None
		self._is_running = False
		
	def start(self):
		"""Start the browser keeper thread"""
		if self._is_running:
			return
			
		self._stop_event.clear()
		try:
			# Store original handle
			self._original_handle = self.webdriver.current_window_handle
			self._is_running = True
			
			# Create activity tab
			self.webdriver.switch_to.new_window('tab')
			self._activity_handle = self.webdriver.current_window_handle
			self.webdriver.get("https://www.reddit.com/r/worldnews/new/")
			
			# Switch back to original tab
			self.webdriver.switch_to.window(self._original_handle)
			
			self._activity_thread = threading.Thread(target=self._keep_alive_loop)
			self._activity_thread.daemon = True
			self._activity_thread.start()
			
		except Exception as e:
			logging.debug(f"Failed to start browser keeper: {str(e)}")
			self._is_running = False
			self._cleanup_activity_tab()
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
			
		self._cleanup_activity_tab()
		
		try:
			error = self._error_queue.get_nowait()
			raise error
		except queue.Empty:
			pass
			
	def _cleanup_activity_tab(self):
		"""Clean up the activity tab"""
		try:
			if self._activity_handle:
				current = self.webdriver.current_window_handle
				self.webdriver.switch_to.window(self._activity_handle)
				self.webdriver.close()
				if current != self._activity_handle:
					self.webdriver.switch_to.window(current)
				self._activity_handle = None
		except Exception as e:
			logging.debug(f"Error cleaning up activity tab: {str(e)}")
			
	def _keep_connection_alive(self):
		"""Keep connection alive by refreshing Reddit tab"""
		try:
			# Switch to activity tab
			current = self.webdriver.current_window_handle
			self.webdriver.switch_to.window(self._activity_handle)
			
			# Refresh the page
			self.webdriver.refresh()
			
			# Add some visual updates
			self.webdriver.execute_script('''
				if (!window._keepAliveStyle) {
					window._keepAliveStyle = document.createElement('style');
					document.head.appendChild(window._keepAliveStyle);
				}
				window._keepAliveStyle.textContent = `body { opacity: ${Math.random() > 0.5 ? 0.99999 : 1}; }`;
			''')
			
			# Switch back to original tab
			self.webdriver.switch_to.window(current)
			
			return True
		except Exception as e:
			logging.debug(f"Connection check failed: {str(e)}")
			return False
			
	def _keep_alive_loop(self):
		"""Main loop that keeps the browser active"""
		error_count = 0
		max_errors = 3
		refresh_interval = 10  # Refresh Reddit every 10 seconds
		
		while not self._stop_event.is_set() and error_count < max_errors:
			try:
				# Keep connection alive
				if not self._keep_connection_alive():
					error_count += 1
					if error_count >= max_errors:
						self._error_queue.put(WebDriverException("Failed to maintain connection"))
						break
				else:
					error_count = 0
				
				# Sleep in shorter intervals to check stop event
				for _ in range(refresh_interval * 2):
					if self._stop_event.is_set():
						break
					time.sleep(0.5)
				
			except Exception as e:
				error_count += 1
				if error_count >= max_errors:
					self._error_queue.put(e)
					break
				logging.debug(f"Handled error: {str(e)}")
				time.sleep(1)