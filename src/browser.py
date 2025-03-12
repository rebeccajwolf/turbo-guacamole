import contextlib
import locale
import logging
import os
import random
import time
import threading
import shutil
import psutil
import subprocess
from pathlib import Path
from types import TracebackType
from typing import Any, Type
from datetime import datetime, timedelta

import ipapi
import seleniumwire.undetected_chromedriver as webdriver
import undetected_chromedriver
from ipapi.exceptions import RateLimited
from selenium.webdriver import ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, NoSuchElementException, InvalidSessionIdException

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
				self.webdriver = None
				self.utils = None
				self.setup_browser()
				logging.debug("out __init__")


		def setup_browser(self):
				"""Setup browser instance with proper error handling"""
				try:
						# Clean up any existing chrome processes
						self.kill_existing_chrome_processes()
						time.sleep(7)
						self.webdriver = self.browserSetup()
						self._setup_cdp_listeners()
						self.utils = Utils(self.webdriver)
				except Exception as e:
						logging.error(f"Error setting up browser: {str(e)}")
						self.cleanup()
						raise

		def reset_weston(self):
				"""Reset Weston compositor for clean display server state"""
				try:
						# Kill existing Weston process
						for proc in psutil.process_iter(['pid', 'name']):
								if 'weston' in proc.info['name'].lower():
										try:
												process = psutil.Process(proc.info["pid"])
												process.terminate()
												process.wait(timeout=3)
										except (psutil.NoSuchProcess, psutil.TimeoutExpired):
												try:
														process.kill()
												except psutil.NoSuchProcess:
														pass

						# Wait for process cleanup
						time.sleep(2)

						# Clean up runtime directory
						runtime_dir = os.environ.get('XDG_RUNTIME_DIR', '/tmp/runtime-user')
						wayland_socket = os.path.join(runtime_dir, os.environ.get('WAYLAND_DISPLAY', 'wayland-1'))

						# Start new Weston instance with output redirected to /dev/null
						with open(os.devnull, 'w') as devnull:
								weston_process = subprocess.Popen(
										[
												'/usr/bin/weston',
												'--backend=headless-backend.so',
												'--width=1920',
												'--height=1080'
										],
										stdout=devnull,
										stderr=devnull
								)

						# Wait for Weston to start
						timeout = 10
						start_time = time.time()
						while not os.path.exists(wayland_socket):
								if time.time() - start_time > timeout:
										raise TimeoutError("Weston failed to start")
								time.sleep(0.5)

						# Additional wait to ensure Weston is ready
						time.sleep(2)

						logging.info("Weston reset successful")

				except Exception as e:
						logging.error(f"Error resetting Weston: {str(e)}")
						raise

		def kill_existing_chrome_processes(self):
				"""Kill any existing chrome processes to ensure clean startup"""
				try:
						for proc in psutil.process_iter(['pid', 'name']):
								proc_name = proc.info['name'].lower()
								if any(name in proc_name for name in ['chrome', 'chromium', 'chromedriver']):
										try:
												process = psutil.Process(proc.info["pid"])
												process.terminate()
												process.wait(timeout=3)
										except (psutil.NoSuchProcess, psutil.TimeoutExpired):
												try:
														process.kill()
												except psutil.NoSuchProcess:
														pass
						
						time.sleep(1)
				except Exception as e:
						logging.warning(f"Error cleaning up chrome processes: {e}")

		def setupProfiles(self) -> Path:
				"""Sets up the sessions profile for the chrome browser with 24-hour retention."""
				sessionsDir = getProjectRoot() / "sessions"
				
				# Create sessions directory if it doesn't exist
				sessionsDir.mkdir(parents=True, exist_ok=True)

				# Clean up profiles older than 24 hours
				current_time = datetime.now()
				if sessionsDir.exists():
						for profile_dir in sessionsDir.iterdir():
								if profile_dir.is_dir():
										try:
												# Extract timestamp from directory name
												dir_parts = profile_dir.name.split('_')
												if len(dir_parts) >= 2:
														timestamp = float(dir_parts[-1])
														profile_time = datetime.fromtimestamp(timestamp)
														
														# Check if profile is older than 24 hours
														if current_time - profile_time > timedelta(hours=24):
																shutil.rmtree(profile_dir)
																logging.info(f"Removed old profile: {profile_dir.name}")
										except (ValueError, IndexError) as e:
												logging.warning(f"Error processing profile directory {profile_dir}: {e}")

				# Look for existing profile for this email
				existing_profile = None
				for profile_dir in sessionsDir.iterdir():
						if profile_dir.is_dir() and profile_dir.name.startswith(f"{self.email}_"):
								existing_profile = profile_dir
								break

				if existing_profile:
						logging.info(f"Using existing profile: {existing_profile.name}")
						return existing_profile

				# Create new profile if none exists
				sessionid = f"{self.email}_{int(time.time())}"
				userSessionDir = sessionsDir / sessionid
				userSessionDir.mkdir(parents=True, exist_ok=True)
				logging.info(f"Created new profile: {sessionid}")

				return userSessionDir

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
						except (InvalidSessionIdException):
							pass
						except Exception as e:
								logging.error(f"Error during browser cleanup: {str(e)}")
						finally:
								try:
										# Ensure webdriver is fully quit
										self.webdriver.quit()
										
										# Kill any remaining chrome processes
										self.kill_existing_chrome_processes()
										
										# Clean up the user data directory
										# if hasattr(self, 'userDataDir') and self.userDataDir.exists():
										# 		shutil.rmtree(self.userDataDir, ignore_errors=True)
										
										# Reset Weston before starting new browser session
										self.reset_weston()
										time.sleep(2)
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
				logging.debug(
						f"in __exit__ exc_type={exc_type} exc_value={exc_value} traceback={traceback}"
				)
				self.cleanup()

		def _apply_cdp_settings(self, target_id=None):
				"""Apply CDP settings to a specific target or current tab"""
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


				cdp_commands = [
						(
								"Emulation.setTouchEmulationEnabled",
								{"enabled": self.mobile}
						),
						(
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
								}
						),
						(
								"Emulation.setUserAgentOverride",
								{
										"userAgent": self.userAgent,
										"platform": self.userAgentMetadata["platform"],
										"userAgentMetadata": self.userAgentMetadata,
								},
						)
					]


				for command, params in cdp_commands:
						if target_id:
								self.webdriver.execute_cdp_cmd(
										f'Target.sendMessageToTarget',
										{
												'targetId': target_id,
												'message': json.dumps({
														'method': command,
														'params': params
												})
										}
								)
						else:
								self.webdriver.execute_cdp_cmd(command, params)

		def _setup_cdp_listeners(self):
				"""Setup listeners for new tab creation and navigation"""
				def handle_target_created(target):
						target_id = target.get('targetId')
						if target.get('type') == 'page':
								self._apply_cdp_settings(target_id)

				# Enable target events
				self.webdriver.execute_cdp_cmd('Target.setDiscoverTargets', {'discover': True})
				
				# Add event listener for target creation
				self.webdriver.add_cdp_listener('Target.targetCreated', handle_target_created)
				
				# Apply settings to initial tab
				self._apply_cdp_settings()

		def browserSetup(
				self,
		) -> undetected_chromedriver.Chrome:
				# Configure and setup the Chrome browser
				options = undetected_chromedriver.ChromeOptions()
				options.headless = self.headless
				options.add_argument(f"--lang={self.localeLang}")
				options.add_argument("--log-level=3")
				# options.add_argument(
				# 		"--blink-settings=imagesEnabled=false"
				# )
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
				options.add_argument("--disable-search-engine-choice-screen")
				options.add_argument("--disable-setuid-sandbox")
				options.add_argument("--disable-software-rasterizer")
				options.add_argument("--disable-site-isolation-trials")
				# options.add_argument("--disable-component-update")
				
				# Wayland specific options
				options.add_argument("--ozone-platform=wayland")
				options.add_argument("--enable-features=UseOzonePlatform")
				
				# Enhanced privacy and security options
				options.add_argument("--disable-web-security")
				# options.add_argument("--disable-blink-features=AutomationControlled")
				# options.add_argument("--disable-features=IsolateOrigins,site-per-process,AutomationControlled")
				# options.add_argument("--disable-blink-features")

				# Performance and stability options
				# options.add_argument("--disable-dev-tools")
				options.add_argument("--disable-background-networking")
				options.add_argument("--disable-background-timer-throttling")
				options.add_argument("--disable-backgrounding-occluded-windows")
				# options.add_argument("--disable-features=TranslateUI")
				# options.add_argument("--disable-ipc-flooding-protection")
				# options.add_argument("--disable-renderer-backgrounding")
				# options.add_argument("--force-color-profile=srgb")
				# options.add_argument("--metrics-recording-only")
				# options.add_argument("--no-first-run")

				# Microsoft-specific options
				# options.add_argument("--disable-prompt-on-repost")
				# options.add_argument("--disable-domain-reliability")
				# options.add_argument("--disable-client-side-phishing-detection")
				options.page_load_strategy = "eager"

				seleniumwireOptions: dict[str, Any] = {
						"verify_ssl": False,
						"suppress_connection_errors": True,
				}

				if self.proxy:
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
						version = self.getChromeVersion()
						major = int(version.split(".")[0])

						driver = webdriver.Chrome(
								options=options,
								seleniumwire_options=seleniumwireOptions,
								user_data_dir=self.userDataDir.as_posix(),
								driver_executable_path="chromedriver",
						)

				seleniumLogger = logging.getLogger("seleniumwire")
				seleniumLogger.setLevel(logging.ERROR)

				return driver

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
				driver = WebDriver(service=ChromeService("chromedriver"), options=chrome_options)
				# driver = WebDriver(options=chrome_options)
				version = driver.capabilities["browserVersion"]

				driver.close()
				driver.quit()

				return version


		def getRemainingSearches(
						self, desktopAndMobile: bool = False, retries: int = 3
		) -> RemainingSearches | int:
				"""
				Returns the number of remaining searches.
				:param desktopAndMobile: If True, returns a namedtuple with desktop and mobile searches.
				:param retries: Number of retries if the data cannot be fetched.
				:return: The number of remaining searches or a namedtuple with desktop and mobile searches.
				"""
				for attempt in range(retries):
					try:
							dashboard = self.utils.getDashboardData()
							searchPoints = 1
							counters = dashboard["userStatus"]["counters"]
	
							# Initialize default values for desktop and mobile searches
							remainingDesktop = 0
							remainingMobile = 0
	
							# Check if 'pcSearch' key exists and has the expected structure
							if "pcSearch" in counters and len(counters["pcSearch"]) > 0:
									progressDesktop = counters["pcSearch"][0]["pointProgress"]
									targetDesktop = counters["pcSearch"][0]["pointProgressMax"]
									if len(counters["pcSearch"]) >= 2:
											progressDesktop += counters["pcSearch"][1]["pointProgress"]
											targetDesktop += counters["pcSearch"][1]["pointProgressMax"]
									if targetDesktop in [30, 90, 102]:
											searchPoints = 3
									elif targetDesktop == 50 or targetDesktop >= 170 or targetDesktop == 150:
											searchPoints = 5
									remainingDesktop = int((targetDesktop - progressDesktop) / searchPoints)
	
							# Check if 'mobileSearch' key exists and has the expected structure
							if (dashboard["userStatus"]["levelInfo"]["activeLevel"] != "Level1" and
											"mobileSearch" in counters and len(counters["mobileSearch"]) > 0):
									progressMobile = counters["mobileSearch"][0]["pointProgress"]
									targetMobile = counters["mobileSearch"][0]["pointProgressMax"]
									remainingMobile = int((targetMobile - progressMobile) / searchPoints)
	
							if desktopAndMobile:
									return RemainingSearches(desktop=remainingDesktop, mobile=remainingMobile)
							if self.mobile:
									return remainingMobile
							return remainingDesktop
	
					except Exception as e:
							logging.warning(f"[BING] Attempt {attempt + 1} failed to get remaining searches: {e}")
							if attempt < retries - 1:
									time.sleep(5)  # Wait for 5 seconds before retrying
							else:
									logging.error("[BING] All attempts to get remaining searches failed. Using default values.")
									if desktopAndMobile:
											return RemainingSearches(desktop=3, mobile=2)  # Positive default values
									else:
											return 3 if not self.mobile else 2  # Positive default values