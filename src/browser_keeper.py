import logging
import threading
import queue
import time
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class BrowserKeeper:
	"""Keeps browser connection alive during long sleep periods"""
	
	def __init__(self, browser):
		self.browser = browser
		self.webdriver = browser.webdriver
		self.utils = browser.utils
		self._stop_event = threading.Event()
		self._activity_thread = None
		self._error_queue = queue.Queue()
		self._original_handle = None
		self._is_running = False
		self._reconnect_attempts = 0
		self.max_reconnect_attempts = 5
		
	def start(self):
		"""Start the browser keeper thread"""
		if self._is_running:
			return
			
		self._stop_event.clear()
		try:
			# Store original handle and verify browser is responsive
			self._original_handle = self.webdriver.current_window_handle
			self._verify_browser_responsive()
			
			# Configure longer timeouts
			self.webdriver.set_script_timeout(30)
			self.webdriver.set_page_load_timeout(30)
			
			# Enable CDP features
			self._enable_cdp_features()
			
			self._is_running = True
			self._reconnect_attempts = 0
			
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
			self._disable_cdp_features()
		except Exception as e:
			logging.debug(f"Error disabling CDP features: {str(e)}")
		
		try:
			error = self._error_queue.get_nowait()
			raise error
		except queue.Empty:
			pass
			
	def _verify_browser_responsive(self):
		"""Verify the browser is responsive"""
		try:
			WebDriverWait(self.webdriver, 10).until(
				lambda driver: driver.execute_script('return document.readyState') == 'complete'
			)
		except Exception as e:
			logging.debug(f"Browser not responsive: {str(e)}")
			raise
			
	def _enable_cdp_features(self):
		"""Enable required CDP features"""
		try:
			self.webdriver.execute_cdp_cmd('Network.enable', {})
			self.webdriver.execute_cdp_cmd('Page.enable', {})
			self.webdriver.execute_cdp_cmd('Runtime.enable', {})
			
			# Configure network conditions for better stability
			self.webdriver.execute_cdp_cmd('Network.emulateNetworkConditions', {
				'offline': False,
				'latency': 0,
				'downloadThroughput': 0,
				'uploadThroughput': 0
			})
		except Exception as e:
			logging.debug(f"Failed to enable CDP features: {str(e)}")
			raise
			
	def _disable_cdp_features(self):
		"""Disable CDP features"""
		try:
			self.webdriver.execute_cdp_cmd('Network.disable', {})
			self.webdriver.execute_cdp_cmd('Page.disable', {})
			self.webdriver.execute_cdp_cmd('Runtime.disable', {})
		except Exception:
			pass
			
	def _keep_connection_alive(self):
		"""Keep CDP connection alive by sending heartbeat commands"""
		try:
			# Execute multiple lightweight checks
			self.webdriver.execute_script('return navigator.onLine')
			self.webdriver.execute_script('return window.performance.timing.navigationStart')
			
			# Verify DOM access
			self.webdriver.execute_script('return document.readyState')
			
			# Send CDP heartbeat
			self.webdriver.execute_cdp_cmd('Runtime.evaluate', {
				'expression': 'true',
				'returnByValue': True
			})
			
			return True
		except Exception as e:
			logging.debug(f"Connection heartbeat failed: {str(e)}")
			return False
			
	def _attempt_reconnect(self):
		"""Attempt to reconnect to the browser"""
		if self._reconnect_attempts >= self.max_reconnect_attempts:
			return False
			
		try:
			self._reconnect_attempts += 1
			logging.debug(f"Attempting reconnection {self._reconnect_attempts}/{self.max_reconnect_attempts}")
			
			# Re-enable CDP features
			self._enable_cdp_features()
			
			# Verify browser is responsive
			self._verify_browser_responsive()
			
			# Reset reconnect counter on success
			self._reconnect_attempts = 0
			return True
			
		except Exception as e:
			logging.debug(f"Reconnection attempt failed: {str(e)}")
			return False
			
	def _keep_alive_loop(self):
		"""Main loop that keeps the browser active"""
		error_count = 0
		max_errors = 3
		heartbeat_interval = 2  # More frequent heartbeats
		
		while not self._stop_event.is_set() and error_count < max_errors:
			try:
				# Send heartbeat
				if not self._keep_connection_alive():
					# Attempt reconnection if heartbeat fails
					if not self._attempt_reconnect():
						raise WebDriverException("Failed to maintain connection")
				
				# Shorter delay between heartbeats
				time.sleep(heartbeat_interval)
				
				# Reset error count on successful iteration
				error_count = 0
				
			except WebDriverException as e:
				error_count += 1
				if "disconnected" in str(e).lower() or error_count >= max_errors:
					if not self._attempt_reconnect():
						self._error_queue.put(e)
						break
				logging.debug(f"Handled WebDriver error: {str(e)}")
				time.sleep(1)
				continue
				
			except Exception as e:
				error_count += 1
				if error_count >= max_errors:
					if not self._attempt_reconnect():
						self._error_queue.put(e)
						break
				logging.debug(f"Handled general error: {str(e)}")
				time.sleep(1)