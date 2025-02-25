import logging
import threading
import queue
import time
from itertools import cycle
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class BrowserKeeper:
	"""Keeps browser connection alive during long sleep periods by simulating real activity"""
	
	def __init__(self, browser):
		self.browser = browser
		self.webdriver = browser.webdriver
		self.utils = browser.utils
		self._stop_event = threading.Event()
		self._activity_thread = None
		self._error_queue = queue.Queue()
		self._original_handle = None
		self._original_url = None
		self._is_running = False
		self._connection_timeout = 60  # Timeout in seconds
		
	def start(self):
		"""Start the browser keeper thread"""
		if self._is_running:
			return
			
		self._stop_event.clear()
		try:
			# Store original state and ensure CDP connection
			self._original_handle = self.webdriver.current_window_handle
			self._original_url = self.webdriver.current_url
			
			# Ensure CDP connection is active
			self.webdriver.execute_cdp_cmd('Network.enable', {})
			self.webdriver.execute_cdp_cmd('Page.enable', {})
			
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
			self._restore_state()
		except Exception as e:
			logging.debug(f"Error restoring state: {str(e)}")
		
		try:
			error = self._error_queue.get_nowait()
			raise error
		except queue.Empty:
			pass
			
	def _restore_state(self):
		"""Restore original browser state"""
		try:
			if not self._original_handle or not self._original_url:
				return
				
			# Close any extra tabs
			current_handles = self.webdriver.window_handles
			if self._original_handle in current_handles:
				for handle in current_handles:
					if handle != self._original_handle:
						try:
							self.webdriver.switch_to.window(handle)
							self.webdriver.close()
						except Exception:
							continue
							
				# Restore original tab and URL
				try:
					self.webdriver.switch_to.window(self._original_handle)
					if self.webdriver.current_url != self._original_url:
						self.webdriver.get(self._original_url)
				except Exception:
					pass
					
		except Exception as e:
			logging.debug(f"Error in restore state: {str(e)}")
			
	def _keep_connection_alive(self):
		"""Keep CDP connection alive by sending heartbeat commands"""
		try:
			# Send CDP command to keep connection alive
			self.webdriver.execute_cdp_cmd('Network.enable', {})
			self.webdriver.execute_cdp_cmd('Page.enable', {})
			
			# Execute a lightweight JavaScript command
			self.webdriver.execute_script('return document.readyState')
			
			return True
		except Exception as e:
			logging.debug(f"Connection heartbeat failed: {str(e)}")
			return False
			
	def _keep_alive_loop(self):
		"""Main loop that keeps the browser active by simulating real activity"""
		error_count = 0
		max_errors = 3
		urls = [
			"https://www.reddit.com",
			"https://www.reddit.com/t/news_and_politics/",
			"https://www.reddit.com/t/science/",
			"https://www.reddit.com/t/reality_tv/"
		]
		url_cycle = cycle(urls)
		last_heartbeat = time.time()
		
		while not self._stop_event.is_set() and error_count < max_errors:
			try:
				# Check if we need to send a heartbeat
				current_time = time.time()
				if current_time - last_heartbeat >= 30:  # Send heartbeat every 30 seconds
					if not self._keep_connection_alive():
						raise WebDriverException("Failed to maintain connection")
					last_heartbeat = current_time
				
				# Verify browser is responsive
				_ = self.webdriver.current_window_handle
				
				# Create new tab with real page load
				self.webdriver.switch_to.new_window('tab')
				url = next(url_cycle)
				
				try:
					# Set page load timeout
					self.webdriver.set_page_load_timeout(30)
					self.webdriver.get(url)
					
					# Wait for page to be interactive
					WebDriverWait(self.webdriver, 10).until(
						lambda driver: driver.execute_script('return document.readyState') == 'interactive'
					)
					
					# Simulate real user activity
					self.webdriver.execute_script(
						"window.scrollTo(0, document.body.scrollHeight/2);"
					)
					
					# Small delay
					time.sleep(2)
					
				except Exception as page_error:
					logging.debug(f"Page load error (continuing): {str(page_error)}")
				finally:
					# Always try to close the tab and switch back
					try:
						self.webdriver.close()
						self.webdriver.switch_to.window(self._original_handle)
					except Exception as close_error:
						logging.debug(f"Tab cleanup error: {str(close_error)}")
				
				# Reset error count on successful iteration
				error_count = 0
				
				# Delay between operations
				time.sleep(3)
				
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
				
			# Verify connection is still alive after each iteration
			if not self._keep_connection_alive():
				error_count += 1
				if error_count >= max_errors:
					self._error_queue.put(WebDriverException("Lost connection to browser"))
					break