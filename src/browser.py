import contextlib
import locale
import logging
import os
import random
import time
import threading
import shutil
from pathlib import Path
from types import TracebackType
from typing import Any, Type

import ipapi
import seleniumwire.undetected_chromedriver as webdriver
import undetected_chromedriver
from ipapi.exceptions import RateLimited
from selenium.webdriver import ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.webdriver import WebDriver

from src import RemainingSearches
from src.userAgentGenerator import GenerateUserAgent
from src.utils import CONFIG, Utils, getBrowserConfig, getProjectRoot, saveBrowserConfig
from src.browser_keeper import BrowserKeeper


class Browser:
	"""WebDriver wrapper class."""

	webdriver: undetected_chromedriver.Chrome

	def __init__(
		self, mobile: bool, account
	) -> None:
		# Initialize browser instance
		logging.debug("in __init__")
		self.mobile = mobile
		self.browserType = "mobile" if mobile else "desktop"
		self.headless = not CONFIG.browser.visible
		self.maxtimeout = CONFIG.cooldown.max
		self.email = account.email
		self.password = account.password
		self.totp = account.get('totp')
		self.localeLang, self.localeGeo = self.getLanguageCountry()
		self.proxy = CONFIG.browser.proxy
		if not self.proxy and account.get('proxy'):
			self.proxy = account.proxy
		self.userDataDir = self.setupProfiles()				
		self.browserConfig = getBrowserConfig(self.userDataDir)
		(
			self.userAgent,
			self.userAgentMetadata,
			newBrowserConfig,
		) = GenerateUserAgent().userAgent(self.browserConfig, mobile)
		if newBrowserConfig:
			self.browserConfig = newBrowserConfig
			saveBrowserConfig(self.userDataDir, self.browserConfig)
		self.webdriver = self.browserSetup()
		self.utils = Utils(self.webdriver)
		# self._stop_heartbeat = threading.Event()
		# self._heartbeat_thread = None
		# self._start_heartbeat()
		# self.browser_keeper = BrowserKeeper(self)
		logging.debug("out __init__")

	# def active_sleep(self, seconds: float) -> None:
	# 	"""
	# 	Keep browser active during sleep periods by maintaining connection
	# 	"""
	# 	try:
	# 		# Start browser keeper
	# 		self.browser_keeper.start()
			
	# 		# Sleep for specified duration
	# 		time.sleep(seconds)
			
	# 	finally:
	# 		# Stop browser keeper
	# 		self.browser_keeper.stop()

	# def _start_heartbeat(self):
	# 	"""Start the heartbeat thread to keep the browser connection alive"""
	# 	self._stop_heartbeat.clear()
	# 	self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
	# 	self._heartbeat_thread.start()
		
	# def _heartbeat_loop(self):
	# 	"""Continuously send heartbeats to keep the browser connection alive"""
	# 	scripts = [
	# 		"return document.title;",
	# 		"return window.innerHeight;",
	# 		"return document.readyState;",
	# 		"return navigator.userAgent;",
	# 		"return new Date().toString();",
	# 		"return 1;",
	# 		"return window.location.href;",
	# 		"return document.documentElement.clientWidth;",
	# 		"return document.documentElement.clientHeight;",
	# 		"return window.performance.now();"
	# 	]
		
	# 	while not self._stop_heartbeat.is_set():
	# 		try:
	# 			# Execute a lightweight script
	# 			script = random.choice(scripts)
	# 			self.webdriver.execute_script(script)
				
	# 			# Log heartbeat occasionally (every ~5 minutes)
	# 			if random.random() < 0.01:  # 1% chance each time
	# 				logging.debug("Browser heartbeat active")
					
	# 			# Sleep for a short interval (5-10 seconds)
	# 			# Short enough to maintain connection but not flood with requests
	# 			sleep_time = random.uniform(5, 10)
				
	# 			# Use wait with timeout to allow for responsive shutdown
	# 			self._stop_heartbeat.wait(timeout=sleep_time)
				
	# 		except Exception as e:
	# 			# If we encounter an error, log it but don't stop the heartbeat
	# 			logging.debug(f"Heartbeat error (will retry): {str(e)}")
	# 			time.sleep(2)  # Short delay before retry

	def cleanup(self):
		"""Clean up browser resources with proper process termination"""
		if self.webdriver:
			try:
				# Store current window handle
				current_handle = self.webdriver.current_window_handle
				
				# Close any extra tabs/windows except main
				all_handles = self.webdriver.window_handles
				for handle in all_handles:
					if handle != current_handle:
						self.webdriver.switch_to.window(handle)
						self.webdriver.close()
				
				# Switch back to main window and close it
				self.webdriver.switch_to.window(current_handle)
				self.webdriver.close()
				
			except Exception as e:
				logging.error(f"Error during browser cleanup: {str(e)}")
			finally:
				try:
					# Ensure webdriver is fully quit
					self.webdriver.quit()
					
					# Small delay to ensure processes are terminated
					time.sleep(1)
				except Exception as e:
					logging.error(f"Error during browser quit: {str(e)}")
				self.webdriver = None
				self.utils = None

	def __enter__(self):
		logging.debug("in __enter__")
		return self

	def __exit__(
		self,
		exc_type: Type[BaseException] | None,
		exc_value: BaseException | None,
		traceback: TracebackType | None,
	):
		# Cleanup actions when exiting the browser context
		logging.debug(
			f"in __exit__ exc_type={exc_type} exc_value={exc_value} traceback={traceback}"
		)
		# self._stop_heartbeat.set()
		# if self._heartbeat_thread:
		# 	self._heartbeat_thread.join(timeout=2)

		self.cleanup()

	def browserSetup(
		self,
	) -> undetected_chromedriver.Chrome:
		# Configure and setup the Chrome browser
		options = undetected_chromedriver.ChromeOptions()
		options.headless = self.headless
		options.add_argument(f"--lang={self.localeLang}")
		options.add_argument("--log-level=3")
		options.add_argument(
			"--blink-settings=imagesEnabled=false"
		)  # If you are having MFA sign in issues comment this line out
		options.add_argument("--ignore-certificate-errors")
		options.add_argument("--ignore-certificate-errors-spki-list")
		options.add_argument("--ignore-ssl-errors")
		options.add_argument("--disable-dev-shm-usage")
		options.add_argument("--no-sandbox")
		options.add_argument("--disable-extensions")
		options.add_argument("--dns-prefetch-disable")
		options.add_argument("--disable-gpu")
		options.add_argument("--disable-default-apps")
		options.add_argument("--disable-features=Translate")
		options.add_argument("--disable-features=PrivacySandboxSettings4")
		options.add_argument("--disable-http2")
		options.add_argument("--disable-search-engine-choice-screen")  # 153
		options.add_argument("--disable-component-update")
		options.add_argument("--ozone-platform=wayland")
		# options.add_argument("--enable-wayland-ime")
		options.add_argument("--enable-features=UseOzonePlatform")
		options.add_argument("--disable-background-networking")
		options.add_argument('--disable-background-timer-throttling')
		options.add_argument('--disable-backgrounding-occluded-windows')
		options.add_argument('--disable-renderer-backgrounding')
		# options.add_argument('--disable-features=IsolateOrigins,site-per-process')
		options.page_load_strategy = "eager"

		seleniumwireOptions: dict[str, Any] = {
			"verify_ssl": False,
			"suppress_connection_errors": True,
		}

		if self.proxy:
			# Setup proxy if provided
			seleniumwireOptions["proxy"] = {
				"http": self.proxy,
				"https": self.proxy,
				"no_proxy": "localhost,127.0.0.1",
			}
		driver = None

		if os.environ.get("DOCKER"):
			driver = webdriver.Chrome(
				options=options,
				seleniumwire_options=seleniumwireOptions,
				user_data_dir=self.userDataDir.as_posix(),
				driver_executable_path="/usr/bin/chromedriver",
			)
		else:
			# Obtain webdriver chrome driver version
			version = self.getChromeVersion()
			major = int(version.split(".")[0])

			driver = webdriver.Chrome(
				options=options,
				seleniumwire_options=seleniumwireOptions,
				user_data_dir=self.userDataDir.as_posix(),
				driver_executable_path="/usr/bin/chromedriver",
				# version_main=major,
			)

		seleniumLogger = logging.getLogger("seleniumwire")
		seleniumLogger.setLevel(logging.ERROR)

		if self.browserConfig.get("sizes"):
			deviceHeight = self.browserConfig["sizes"]["height"]
			deviceWidth = self.browserConfig["sizes"]["width"]
		else:
			if self.mobile:
				deviceHeight = random.randint(568, 1024)
				deviceWidth = random.randint(320, min(576, int(deviceHeight * 0.7)))
			else:
				deviceWidth = random.randint(1024, 2560)
				deviceHeight = random.randint(768, min(1440, int(deviceWidth * 0.8)))
			self.browserConfig["sizes"] = {
				"height": deviceHeight,
				"width": deviceWidth,
			}
			saveBrowserConfig(self.userDataDir, self.browserConfig)

		if self.mobile:
			screenHeight = deviceHeight + 146
			screenWidth = deviceWidth
		else:
			screenWidth = deviceWidth + 55
			screenHeight = deviceHeight + 151

		logging.info(f"Screen size: {screenWidth}x{screenHeight}")
		logging.info(f"Device size: {deviceWidth}x{deviceHeight}")

		if self.mobile:
			driver.execute_cdp_cmd(
				"Emulation.setTouchEmulationEnabled",
				{
					"enabled": True,
				},
			)

		driver.execute_cdp_cmd(
			"Emulation.setDeviceMetricsOverride",
			{
				"width": deviceWidth,
				"height": deviceHeight,
				"deviceScaleFactor": 0,
				"mobile": self.mobile,
				"screenWidth": screenWidth,
				"screenHeight": screenHeight,
				"positionX": 0,
				"positionY": 0,
				"viewport": {
					"x": 0,
					"y": 0,
					"width": deviceWidth,
					"height": deviceHeight,
					"scale": 1,
				},
			},
		)

		driver.execute_cdp_cmd(
			"Emulation.setUserAgentOverride",
			{
				"userAgent": self.userAgent,
				"platform": self.userAgentMetadata["platform"],
				"userAgentMetadata": self.userAgentMetadata,
			},
		)

		#  # Keep session alive with periodic script execution
		# def session_keeper():
		# 	while True:
		# 		try:
		# 			# Execute a lightweight script
		# 			driver.execute_script("return 1;")
		# 			time.sleep(30)  # Heartbeat interval
		# 		except Exception:
		# 			break
					
		# threading.Thread(target=session_keeper, daemon=True).start()

		return driver

	def setupProfiles(self) -> Path:
			"""
			Sets up the sessions profile for the chrome browser.
			Uses the username to create a unique profile for the session.

			Returns:
					Path
			"""
			sessionsDir = getProjectRoot() / "sessions"

			# Create unique session ID using username and timestamp
			sessionid = f"{self.email}_{int(time.time())}"

			# Create new session directory
			userSessionDir = sessionsDir / sessionid
			userSessionDir.mkdir(parents=True, exist_ok=True)
			
			# Clean up old session directories for this user
			try:
					for oldDir in sessionsDir.glob(f"{self.email}_*"):
							if oldDir != userSessionDir:
									shutil.rmtree(oldDir)
			except Exception as e:
					logging.error(f"Error cleaning old session directories: {str(e)}")

			return userSessionDir


	@staticmethod
	def getLanguageCountry() -> tuple[str, str]:
		country = CONFIG.browser.geolocation
		language = CONFIG.browser.language

		if not language or not country:
			locale_info = locale.getlocale()
			if locale_info[0]:
				language, country = locale_info[0].split("_")

		if not language or not country:
			try:
				ipapiLocation = ipapi.location()
				if not language:
					language = ipapiLocation["languages"].split(",")[0].split("-")[0]
				if not country:
					country = ipapiLocation["country"]
			except RateLimited:
				logging.warning(exc_info=True)

		if not language:
			language = "en"
			logging.warning(
				f"Not able to figure language returning default: {language}"
			)

		if not country:
			country = "US"
			logging.warning(f"Not able to figure country returning default: {country}")

		return language, country

	@staticmethod
	def getChromeVersion() -> str:
		chrome_options = ChromeOptions()
		chrome_options.add_argument("--headless=new")
		chrome_options.add_argument("--no-sandbox")
		chrome_options.add_argument("--disable-gpu")
		chrome_options.add_argument("--disable-dev-shm-usage")
		# driver = WebDriver(service=ChromeService("chromedriver"), options=chrome_options)
		driver = WebDriver(options=chrome_options)
		version = driver.capabilities["browserVersion"]

		driver.close()
		driver.quit()
		# driver.__exit__(None, None, None)

		return version

	def getRemainingSearches(
		self, desktopAndMobile: bool = False
	) -> RemainingSearches | int:
		# bingInfo = self.utils.getBingInfo()
		bingInfo = self.utils.getDashboardData()
		searchPoints = 1
		counters = bingInfo["userStatus"]["counters"]
		pcSearch: dict = counters["pcSearch"][0]
		pointProgressMax: int = pcSearch["pointProgressMax"]

		searchPoints: int
		if pointProgressMax in [30, 90, 102]:
			searchPoints = 3
		elif pointProgressMax in [50, 150] or pointProgressMax >= 170:
			searchPoints = 5
		pcPointsRemaining = pcSearch["pointProgressMax"] - pcSearch["pointProgress"]
		assert pcPointsRemaining % searchPoints == 0
		remainingDesktopSearches: int = int(pcPointsRemaining / searchPoints)

		activeLevel = bingInfo["userStatus"]["levelInfo"]["activeLevel"]
		remainingMobileSearches: int = 0
		if activeLevel == "Level2":
			mobileSearch: dict = counters["mobileSearch"][0]
			mobilePointsRemaining = (
				mobileSearch["pointProgressMax"] - mobileSearch["pointProgress"]
			)
			assert mobilePointsRemaining % searchPoints == 0
			remainingMobileSearches = int(mobilePointsRemaining / searchPoints)
		elif activeLevel == "Level1":
			pass
		else:
			raise AssertionError(f"Unknown activeLevel: {activeLevel}")

		if desktopAndMobile:
			return RemainingSearches(
				desktop=remainingDesktopSearches, mobile=remainingMobileSearches
			)
		if self.mobile:
			return remainingMobileSearches
		return remainingDesktopSearches
