import logging
import threading
import queue
import time
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.by import By

class BrowserKeeper:
	"""Keeps browser connection alive during long sleep periods using minimal interventions"""
	
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
			# Store original handle
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
			error = self._error_queue.get_nowait()
			raise error
		except queue.Empty:
			pass
			
	def _keep_connection_alive(self):
		"""Keep connection alive using minimal JavaScript execution"""
		try:
			# Single lightweight check
			self.webdriver.execute_script('return true')
			return True
		except Exception as e:
			logging.debug(f"Connection check failed: {str(e)}")
			return False
			
	def _keep_alive_loop(self):
		"""Main loop that keeps the browser active"""
		error_count = 0
		max_errors = 3
		heartbeat_interval = 5
		
		while not self._stop_event.is_set() and error_count < max_errors:
			try:
				# Simple connection check
				if not self._keep_connection_alive():
					error_count += 1
					if error_count >= max_errors:
						self._error_queue.put(WebDriverException("Failed to maintain connection"))
						break
				else:
					error_count = 0
				
				time.sleep(heartbeat_interval)
				
			except Exception as e:
				error_count += 1
				if error_count >= max_errors:
					self._error_queue.put(e)
					break
				logging.debug(f"Handled error: {str(e)}")
				time.sleep(1)