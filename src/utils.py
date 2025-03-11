import contextlib
import json
import locale as pylocale
import logging
import re
import time
import inspect
from argparse import Namespace, ArgumentParser
from datetime import date, datetime
from pathlib import Path
import random
import schedule
from itertools import cycle
from threading import Event, Thread
from typing import Any, List, Self
from copy import deepcopy
import base64
from flask import send_file
from io import BytesIO

import requests
import os
import yaml
from apprise import Apprise
from requests import Session
from functools import wraps
from requests.adapters import HTTPAdapter
from selenium.common import (
	ElementClickInterceptedException,
	ElementNotInteractableException,
	ElementNotVisibleException,
	NoSuchElementException,
	TimeoutException,
	StaleElementReferenceException
)
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait
from urllib3 import Retry

from .constants import REWARDS_URL, SEARCH_URL

class Config(dict):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for key, value in self.items():
			if isinstance(value, dict):
				self[key] = self.__class__(value)
			if isinstance(value, list):
				for i, v in enumerate(value):
					if isinstance(v, dict):
						value[i] = self.__class__(v)

	def __or__(self, other):
		new = deepcopy(self)
		for key in other:
			if key in new:
				if isinstance(new[key], dict) and isinstance(other[key], dict):
					new[key] = new[key] | other[key]
					continue
			if isinstance(other[key], dict):
				new[key] = self.__class__(other[key])
				continue
			if isinstance(other[key], list):
				new[key] = self.configifyList(other[key])
				continue
			new[key] = other[key]
		return new


	def __getattribute__(self, item):
		if item in self:
			return self[item]
		return super().__getattribute__(item)

	def __setattr__(self, key, value):
		if type(value) is dict:
			value = self.__class__(value)
		if type(value) is list:
			value = self.configifyList(value)
		self[key] = value


	def __getitem__(self, item):
		if type(item) is not str or not '.' in item:
			return super().__getitem__(item)
		item: str
		items = item.split(".")
		found = super().__getitem__(items[0])
		for item in items[1:]:
			found = found.__getitem__(item)
		return found

	def __setitem__(self, key, value):
		if type(value) is dict:
			value = self.__class__(value)
		if type(value) is list:
			value = self.configifyList(value)
		if type(key) is not str or not '.' in key:
			return super().__setitem__(key, value)
		item: str
		items = key.split(".")
		found = super().__getitem__(items[0])
		for item in items[1:-1]:
			found = found.__getitem__(item)
		found.__setitem__(items[-1], value)

	@classmethod
	def fromYaml(cls, path: Path) -> Self:
		if not path.exists() or not path.is_file():
			return cls()
		with open(path, encoding="utf-8") as f:
			yamlContents = yaml.safe_load(f)
			if not yamlContents:
				return cls()
			return cls(yamlContents)


	@classmethod
	def configifyList(cls, listToConvert: list) -> list:
		new = [None] * len(listToConvert)
		for index, item in enumerate(listToConvert):
			if isinstance(item, dict):
				new[index] = cls(item)
				continue
			if isinstance(item, list):
				new[index] = cls.configifyList(item)
				continue
			new[index] = item
		return new

	@classmethod
	def dictifyList(cls, listToConvert: list) -> list:
		new = [None] * len(listToConvert)
		for index, item in enumerate(listToConvert):
			if isinstance(item, cls):
				new[index] = item.toDict()
				continue
			if isinstance(item, list):
				new[index] = cls.dictifyList(item)
				continue
			new[index] = item
		return new


	def get(self, key, default=None):
		if type(key) is not str or not '.' in key:
			return super().get(key, default)
		item: str
		keys = key.split(".")
		found = super().get(keys[0], default)
		for key in keys[1:]:
			found = found.get(key, default)
		return found

	def toDict(self) -> dict:
		new = {}
		for key, value in self.items():
			if isinstance(value, self.__class__):
				new[key] = value.toDict()
				continue
			if isinstance(value, list):
				new[key] = self.dictifyList(value)
				continue
			new[key] = value
		return new


DEFAULT_CONFIG: Config = Config(
	{
		'apprise': {
			'enabled': True,
			'notify': {
				'incomplete-activity': True,
				'uncaught-exception': True,
				'login-code': True
			},
			'summary': 'ON_ERROR',
			'urls': []
		},
		'browser': {
			'geolocation': None,
			'language': None,
			'visible': False,
			'proxy': None
		},
		'activities': {
			'ignore': [
				'Get 50 entries plus 1000 points!',
				"Safeguard your family's info"
			],
			'search': {
				'Black Friday shopping': 'black friday deals',
				'Discover open job roles': 'jobs at microsoft',
				'Expand your vocabulary': 'define demure',
				'Find places to stay': 'hotels rome italy',
				'Find somewhere new to explore': 'directions to new york',
				'Gaming time': 'vampire survivors video game',
				'Get your shopping done faster': 'new iphone',
				'Houses near you': 'apartments manhattan',
				"How's the economy?": 'sp 500',
				'Learn to cook a new recipe': 'how cook pierogi',
				"Let's watch that movie again!": 'aliens movie',
				'Plan a quick getaway': 'flights nyc to paris',
				'Prepare for the weather': 'weather tomorrow',
				'Quickly convert your money': 'convert 374 usd to yen',
				'Search the lyrics of a song': 'black sabbath supernaut lyrics',
				'Stay on top of the elections': 'election news latest',
				'Too tired to cook tonight?': 'Pizza Hut near me',
				'Translate anything': 'translate pencil sharpener to spanish',
				'What time is it?': 'china time',
				"What's for Thanksgiving dinner?": 'pumpkin pie recipe',
				'Who won?': 'braves score',
				'You can track your package': 'usps tracking'
			}
		},
		'logging': {
			'format': '%(asctime)s [%(levelname)s] %(message)s',
			'level': 'INFO'
		},
		'retries': {
			'base_delay_in_seconds': 120,
			'max': 4,
			'strategy': 'EXPONENTIAL'
		},
		'cooldown': {
			'min': 300,
			'max': 600
		},
		'search': {
			'type': 'both'
		},
		'accounts': []
	}
)


# class ActiveSleepManager:
# 	def __init__(self):
# 		self.running = True
# 		self.stop_event = Event()
# 		self._schedule_thread = None

# 	def start(self):
# 		"""Start the schedule manager"""
# 		self._schedule_thread = Thread(target=self._run_schedule, daemon=True)
# 		self._schedule_thread.start()

# 	def stop(self):
# 		"""Stop the schedule manager gracefully"""
# 		self.running = False
# 		self.stop_event.set()
# 		if self._schedule_thread:
# 			self._schedule_thread.join(timeout=5)

# 	def _run_schedule(self):
# 		"""Run the schedule loop with proper error handling"""
# 		while self.running and not self.stop_event.is_set():
# 			try:
# 				schedule.run_pending()
# 				self.stop_event.wait(timeout=1)
# 			except Exception as e:
# 				logging.error(f"Schedule error: {str(e)}")
# 				time.sleep(1)

# def active_sleep(seconds: float) -> None:
# 	"""
# 	Active sleep function that uses the browser keeper to maintain connection.
	
# 	Args:
# 		seconds: Total number of seconds to sleep
# 	"""
# 	# Get the current browser instance
# 	browser = None
# 	frame = inspect.currentframe()
# 	while frame:
# 		if 'self' in frame.f_locals:
# 			instance = frame.f_locals['self']
# 			if hasattr(instance, 'browser'):
# 				browser = instance.browser
# 				break
# 		frame = frame.f_back
	
# 	if browser and hasattr(browser, 'browser_keeper'):
# 		try:
# 			# Start browser keeper
# 			browser.browser_keeper.start()
			
# 			# Use scheduler for container activity
# 			sleep_completed = False
# 			manager = ActiveSleepManager()
			
# 			def mark_complete():
# 				nonlocal sleep_completed
# 				sleep_completed = True
# 				return schedule.CancelJob
			
# 			try:
# 				# Start the scheduler manager
# 				manager.start()
				
# 				# Schedule the wake-up
# 				schedule.every(seconds).seconds.do(mark_complete)
				
# 				# Wait until sleep is complete
# 				while not sleep_completed:
# 					time.sleep(1)
					
# 			finally:
# 				# Cleanup
# 				manager.stop()
# 				schedule.clear()
				
# 		finally:
# 			# Always stop browser keeper
# 			if hasattr(browser, 'browser_keeper'):
# 				browser.browser_keeper.stop()
# 	else:
# 		# Fallback to simple active sleep with scheduler
# 		sleep_completed = False
# 		manager = ActiveSleepManager()
		
# 		def mark_complete():
# 			nonlocal sleep_completed
# 			sleep_completed = True
# 			return schedule.CancelJob
		
# 		try:
# 			# Start the scheduler manager
# 			manager.start()
			
# 			# Schedule the wake-up
# 			schedule.every(seconds).seconds.do(mark_complete)
			
# 			# Wait until sleep is complete
# 			while not sleep_completed:
# 				time.sleep(1)
				
# 		finally:
# 			# Cleanup
# 			manager.stop()
# 			schedule.clear()




# def active_sleep(seconds: float) -> None:
# 	"""
# 	Active sleep function that keeps the browser alive during sleep periods.
# 	Uses the browser's active_sleep method to maintain connection.
	
# 	Args:
# 		seconds: Total number of seconds to sleep
# 	"""
# 	# Get the current browser instance
# 	browser = None
# 	frame = inspect.currentframe()
# 	while frame:
# 		if 'self' in frame.f_locals:
# 			instance = frame.f_locals['self']
# 			if hasattr(instance, 'browser'):
# 				browser = instance.browser
# 				break
# 		frame = frame.f_back
		
# 	if browser:
# 		browser.active_sleep(seconds)
# 	else:
# 		# Fallback to simple sleep if no browser instance found
# 		time.sleep(seconds)


class ActiveSleepManager:
	def __init__(self):
		self.running = True
		self.stop_event = Event()
		self._schedule_thread = None

	def start(self):
		"""Start the schedule manager"""
		self._schedule_thread = Thread(target=self._run_schedule, daemon=True)
		self._schedule_thread.start()

	def stop(self):
		"""Stop the schedule manager gracefully"""
		self.running = False
		self.stop_event.set()
		if self._schedule_thread:
			self._schedule_thread.join(timeout=5)

	def _run_schedule(self):
		"""Run the schedule loop with proper error handling"""
		while self.running and not self.stop_event.is_set():
			try:
				schedule.run_pending()
				self.stop_event.wait(timeout=1)
			except Exception as e:
				logging.error(f"Schedule error: {str(e)}")
				time.sleep(1)

def active_sleep(seconds: float) -> None:
	"""
	Active sleep function that uses the scheduler system to keep the container alive.
	
	Args:
		seconds: Total number of seconds to sleep
	"""
	sleep_completed = False
	manager = ActiveSleepManager()
	
	def mark_complete():
		nonlocal sleep_completed
		sleep_completed = True
		return schedule.CancelJob
	
	try:
		# Start the scheduler manager
		manager.start()
		
		# Schedule the wake-up
		schedule.every(seconds).seconds.do(mark_complete)
		
		# Wait until sleep is complete
		while not sleep_completed:
			time.sleep(1)
			
	finally:
		# Cleanup
		manager.stop()
		schedule.clear()



# def active_sleep(seconds: float) -> None:
# 	"""
# 	Active sleep function that keeps the container alive by using small sleep intervals.
	
# 	Args:
# 		seconds: Total number of seconds to sleep
# 	"""
# 	end_time = time.time() + seconds
# 	while time.time() < end_time:
# 		# Sleep in 1-second intervals to maintain activity
# 		time.sleep(1)


# def scheduled_sleep(seconds: float) -> None:
#     """
#     Schedule a delay while maintaining sequential execution.
#     Uses the scheduler to keep the container alive during long delays.
	
#     Args:
#         seconds: Total number of seconds to sleep
#     """
#     event_completed = False
	
#     def mark_complete():
#         nonlocal event_completed
#         event_completed = True
#         return schedule.CancelJob
		
#     # Schedule a one-time job after the delay
#     schedule.every(seconds).seconds.do(mark_complete)
	
#     # Wait for the job to complete while keeping the container alive
#     while not event_completed:
#         schedule.run_pending()
#         time.sleep(1)


def retry_on_500_errors(function):
	@wraps(function)
	def wrapper(*args, **kwargs):
		utils_instance: Utils = args[0]  # First arg is Utils instance
		driver = utils_instance.webdriver  # Get the WebDriver instance
		error_codes = ["HTTP ERROR 500", "HTTP ERROR 502",
									 "HTTP ERROR 503", "HTTP ERROR 504", "HTTP ERROR 505"]
		status_code = "-"
		result = function(*args, **kwargs)
		while True:
				try:
						status_code = driver.execute_script(
								"return document.readyState;")
						if status_code in ("complete", "interactive") and not any(error_code in driver.page_source for error_code in error_codes):
								return result
						elif status_code == "loading":
								return result
						else:
								raise Exception("Page not loaded")
				except Exception as e:
						# Check if the page contains 500 errors
						if any(error_code in driver.page_source for error_code in error_codes):
								driver.refresh()  # Recursively refresh
						else:
								raise Exception(
										f"another exception occurred during handling 500 errors with status '{status_code}': {e}")
	return wrapper


class Utils:

	def __init__(self, webdriver: WebDriver):
		self.webdriver = webdriver
		with contextlib.suppress(Exception):
			locale = pylocale.getdefaultlocale()[0]
			pylocale.setlocale(pylocale.LC_NUMERIC, locale)

		# self.config = self.loadConfig()


	@retry_on_500_errors
	def goToURL(self, url: str):
			self.webdriver.get(url)

	def waitUntilVisible(
		self, by: str, selector: str, timeToWait: float = 10
	) -> WebElement:
		return WebDriverWait(self.webdriver, timeToWait).until(
			expected_conditions.visibility_of_element_located((by, selector))
		)

	def waitUntilClickable(
		self, by: str, selector: str, timeToWait: float = 10
	) -> WebElement:
		return WebDriverWait(self.webdriver, timeToWait).until(
			expected_conditions.element_to_be_clickable((by, selector))
		)

	def checkIfTextPresentAfterDelay(self, text: str, timeToWait: float = 10) -> bool:
		time.sleep(timeToWait)
		text_found = re.search(text, self.webdriver.page_source)
		return text_found is not None

	def waitUntilQuestionRefresh(self) -> WebElement:
		return self.waitUntilVisible(By.CLASS_NAME, "rqECredits", timeToWait=20)

	def waitUntilQuizLoads(self) -> WebElement:
		return self.waitUntilVisible(By.XPATH, '//*[@id="rqStartQuiz"]')

	def resetTabs(self) -> None:
		curr = self.webdriver.current_window_handle

		for handle in self.webdriver.window_handles:
			if handle != curr:
				self.webdriver.switch_to.window(handle)
				time.sleep(0.5)
				self.webdriver.close()
				time.sleep(0.5)

		self.webdriver.switch_to.window(curr)
		time.sleep(0.5)
		self.goToRewards()

	def goToRewards(self) -> None:
		self.webdriver.get(REWARDS_URL)
		while True:
				try:
						assert (
								self.webdriver.current_url == REWARDS_URL
						), f"{self.webdriver.current_url} {REWARDS_URL}"
						return
				except:
						self.webdriver.refresh()
						time.sleep(10)

	def goToSearch(self) -> None:
		self.webdriver.get(SEARCH_URL)
		# assert (
		#     self.webdriver.current_url == SEARCH_URL
		# ), f"{self.webdriver.current_url} {SEARCH_URL}"  # need regex: AssertionError: https://www.bing.com/?toWww=1&redig=A5B72363182B49DEBB7465AD7520FDAA https://bing.com/

	# Prefer getBingInfo if possible
	def getDashboardData(self) -> dict:
		urlBefore = self.webdriver.current_url
		maxTries = 5
		for _ in range(maxTries):
			try:
				self.goToRewards()
				return self.webdriver.execute_script("return dashboard")
			except:
				self.webdriver.refresh()
				time.sleep(10)
				self.waitUntilVisible(By.ID, 'app-host', 30)
			finally:
				try:
					self.webdriver.get(urlBefore)
				except TimeoutException:
					self.goToRewards()

	def getDailySetPromotions(self) -> list[dict]:
		return self.getDashboardData()["dailySetPromotions"][
			date.today().strftime("%m/%d/%Y")
		]

	def getMorePromotions(self) -> list[dict]:
		return self.getDashboardData()["morePromotions"]

	# Not reliable
	def getBingInfo(self) -> Any:
		session = makeRequestsSession()

		for cookie in self.webdriver.get_cookies():
			session.cookies.set(cookie["name"], cookie["value"])

		response = session.get("https://www.bing.com/rewards/panelflyout/getuserinfo")

		assert response.status_code == requests.codes.ok
		# fixme Add more asserts
		# todo Add fallback to src.utils.Utils.getDashboardData (slower but more reliable)
		return response.json()

	def isLoggedIn(self) -> bool:
		if self.getBingInfo()["isRewardsUser"]:  # faster, if it works
			return True
		self.webdriver.get(
			"https://rewards.bing.com/Signin/"
		)  # changed site to allow bypassing when M$ blocks access to login.live.com randomly
		with contextlib.suppress(TimeoutException):
			self.waitUntilVisible(
				By.CSS_SELECTOR, 'html[data-role-name="RewardsPortal"]', 10
			)
			return True
		return False

	def getAccountPoints(self) -> int:
		return self.getDashboardData()["userStatus"]["availablePoints"]

	def getGoalPoints(self) -> int:
		return self.getDashboardData()["userStatus"]["redeemGoal"]["price"]

	def getGoalTitle(self) -> str:
		return self.getDashboardData()["userStatus"]["redeemGoal"]["title"]

	def tryDismissAllMessages(self) -> bool:
			"""
			Attempts to dismiss all possible messages/popups by checking visibility and interactability.
			Returns True if any message was dismissed successfully.
			"""
			buttons = [
					{"by": By.ID, "selector": "acceptButton", "label": "AcceptButton"},
					{"by": By.CSS_SELECTOR, "selector": ".ext-secondary.ext-button", "label": "Skip for now Button"},
					{"by": By.ID, "selector": "iLandingViewAction", "label": "iLandingViewAction"},
					{"by": By.ID, "selector": "iShowSkip", "label": "iShowSkip"},
					{"by": By.ID, "selector": "iNext", "label": "iNext"},
					{"by": By.ID, "selector": "iLooksGood", "label": "iLooksGood"},
					{"by": By.ID, "selector": "idSIButton9", "label": "idSIButton9"},
					{"by": By.CSS_SELECTOR, "selector": ".ms-Button.ms-Button--primary", "label": "Primary Button"},
					{"by": By.CSS_SELECTOR, "selector": ".c-glyph.glyph-cancel", "label": "Mobile Welcome Button"},
					{"by": By.CSS_SELECTOR, "selector": ".maybe-later", "label": "Mobile Rewards App Banner"},
					{"by": By.XPATH, "selector": "//div[@id='cookieConsentContainer']//button[contains(text(), 'Accept')]", "label": "Accept Cookie Consent Container"},
					{"by": By.ID, "selector": "bnp_btn_accept", "label": "Bing Cookie Banner"},
					{"by": By.ID, "selector": "reward_pivot_earn", "label": "Reward Coupon Accept"},
					{"by": By.CSS_SELECTOR, "selector": ".dashboardPopUpPopUpSelectButton", "label": "Dashboard Popup Button"},
					{"by": By.ID, "selector": "cookie-banner", "label": "Cookie Banner"}
			]

			any_dismissed = False

			for button in buttons:
					try:
							# Find all matching elements
							elements = self.webdriver.find_elements(by=button["by"], value=button["selector"])
							
							for element in elements:
									try:
											# Check if element is displayed and interactable
											if element.is_displayed():
													# Create a new wait for this specific element
													wait = WebDriverWait(self.webdriver, 1)
													
													# Wait until element is clickable
													clickable_element = wait.until(
															expected_conditions.element_to_be_clickable(element)
													)
													
													# Try to click the element
													clickable_element.click()
													logging.info(f"[DISMISS] Successfully clicked: {button['label']}")
													any_dismissed = True
													
													# Small delay after successful click
													time.sleep(0.5)
													
									except (ElementClickInterceptedException, ElementNotInteractableException) as e:
											# Try JavaScript click if regular click fails
											try:
													self.webdriver.execute_script("arguments[0].click();", element)
													logging.info(f"[DISMISS] Successfully clicked (JS): {button['label']}")
													any_dismissed = True
													time.sleep(0.5)
											except Exception:
													continue
									except (TimeoutException, StaleElementReferenceException):
											# Element either not clickable or no longer in DOM
											continue
									
					except Exception as e:
							# Log any unexpected errors but continue with next button
							logging.info(f"[DISMISS] Error handling {button['label']}: {str(e)}")
							continue

			return any_dismissed

	def switchToNewTab(self, timeToWait: float = 15, closeTab: bool = False) -> None:
		time.sleep(timeToWait)
		self.webdriver.switch_to.window(window_name=self.webdriver.window_handles[1])
		if closeTab:
			self.closeCurrentTab()

	def goToLatestWindow(self, timeToWait: float = 15) -> None:
		"""
		Switches to newest open window
		:return:
		"""
		self.webdriver.switch_to.window(self.webdriver.window_handles[-1])
		if timeToWait > 0:
				time.sleep(timeToWait)

	def closeCurrentTab(self) -> None:
		self.webdriver.close()
		time.sleep(0.5)
		self.webdriver.switch_to.window(window_name=self.webdriver.window_handles[0])
		time.sleep(0.5)

	def isElementExists(self, by: str, selector: str) -> bool:
			'''Returns True if given element exits else False'''
			try:
					self.webdriver.find_element(by, selector)
			except NoSuchElementException:
					return False
			return True

	def jsClick(self, element: WebElement) -> None:
		"""Click any given element"""
		try:
			self.webdriver.execute_script("arguments[0].click();", element)
		except Exception:
			logging.exception(msg=f'Exception when JS clicking element {element}.')

	def click(self, element: WebElement) -> None:
		try:
			WebDriverWait(self.webdriver, 10).until(
				expected_conditions.element_to_be_clickable(element)
			)
			element.click()
		except (ElementClickInterceptedException, ElementNotInteractableException):
			self.tryDismissAllMessages()
			WebDriverWait(self.webdriver, 10).until(
				expected_conditions.element_to_be_clickable(element)
			)
			element.click()

	def mouseClick(self, element: WebElement) -> None:
		try:
			action = ActionChains(self.webdriver)
			action.move_to_element(element).pause(0.5).click().perform()
		except (ElementNotVisibleException, ElementClickInterceptedException, ElementNotInteractableException):
			self.tryDismissAllMessages()
			WebDriverWait(self.webdriver, 10).until(
				expected_conditions.element_to_be_clickable(element)
			)
			jsClick(element)

def take_screenshot(webdriver: WebDriver, name: str = None) -> str:
		"""
		Takes a screenshot of the current browser window and saves it
		
		Args:
				webdriver: The WebDriver instance
				name: Optional name for the screenshot. If not provided, uses timestamp
				
		Returns:
				str: Path to the saved screenshot
		"""
		try:
				screenshots_dir = getProjectRoot() / "screenshots"
				screenshots_dir.mkdir(parents=True, exist_ok=True)
				
				# Generate filename
				timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
				filename = f"{name}_{timestamp}.png" if name else f"screenshot_{timestamp}.png"
				filepath = screenshots_dir / filename
				
				# Take screenshot
				webdriver.save_screenshot(str(filepath))
				logging.info(f"Screenshot saved: {filepath}")
				return str(filepath)
				
		except Exception as e:
				logging.error(f"Error taking screenshot: {str(e)}")
				return None

def get_screenshot_b64(webdriver: WebDriver) -> str:
		"""
		Takes a screenshot and returns it as a base64 encoded string
		
		Args:
				webdriver: The WebDriver instance
				
		Returns:
				str: Base64 encoded screenshot
		"""
		try:
				# Take screenshot
				screenshot = webdriver.get_screenshot_as_png()
				
				# Convert to base64
				b64_screenshot = base64.b64encode(screenshot).decode()
				return b64_screenshot
				
		except Exception as e:
				logging.error(f"Error taking screenshot: {str(e)}")
				return None


def argumentParser() -> Namespace:
	parser = ArgumentParser(
		description="A simple bot that uses Selenium to farm M$ Rewards in Python",
		epilog="At least one account should be specified, either using command line arguments or a configuration file."
				 "\nAll specified arguments will override the configuration file values."
	)
	parser.add_argument(
		"-c",
		"--config",
		type=str,
		default=None,
		help="Specify the configuration file path",
	)
	parser.add_argument(
		"-C",
		"--create-config",
		action="store_true",
		help="Create a fillable configuration file with basic settings and given ones if none exists",
	)
	parser.add_argument(
		"-v",
		"--visible",
		action="store_true",
		help="Visible browser (Disable headless mode)",
	)
	parser.add_argument(
		"-l",
		"--lang",
		type=str,
		default=None,
		help="Language (ex: en)"
			 "\nsee https://serpapi.com/google-languages for options"
	)
	parser.add_argument(
		"-g",
		"--geo",
		type=str,
		default=None,
		help="Searching geolocation (ex: US)"
			 "\nsee https://serpapi.com/google-trends-locations for options (should be uppercase)"
	)
	parser.add_argument(
		"-em",
		"--email",
		type=str,
		default=None,
		help="Email address of the account to run. Only used if a password is given.",
	)
	parser.add_argument(
		"-pw",
		"--password",
		type=str,
		default=None,
		help="Password of the account to run. Only used if an email is given.",
	)
	parser.add_argument(
		"-p",
		"--proxy",
		type=str,
		default=None,
		help="Global Proxy, supports http/https/socks4/socks5 (overrides config per-account proxies)"
			 "\n`(ex: http://user:pass@host:port)`",
	)
	parser.add_argument(
		"-t",
		"--searchtype",
		choices=['desktop', 'mobile', 'both'],
		default=None,
		help="Set to search in either desktop, mobile or both (default: both)",
	)
	parser.add_argument(
		"-da",
		"--disable-apprise",
		action="store_true",
		help="Disable Apprise notifications, useful when developing",
	)
	parser.add_argument(
		"-d",
		"--debug",
		action="store_true",
		help="Set the logging level to DEBUG",
	)
	return parser.parse_args()


def getProjectRoot() -> Path:
	return Path(__file__).parent.parent


def commandLineArgumentsAsConfig(args: Namespace) -> Config:
	config = Config()
	if args.visible:
		config.browser = Config()
		config.browser.visible = True
	if args.lang:
		if not 'browser' in config:
			config.browser = Config()
		config.browser.language = args.lang
	if args.geo:
		if not 'browser' in config:
			config.browser = Config()
		config.browser.geolocation = args.geo
	if args.proxy:
		if not 'browser' in config:
			config.browser = Config()
		config.browser.proxy = args.proxy
	if args.disable_apprise:
		config.apprise = Config()
		config.apprise.enabled = False
	if args.debug:
		config.logging = Config()
		config.logging.level = 'DEBUG'
	if args.searchtype:
		config.search = Config()
		config.search.type = args.searchtype
	if args.email and args.password:
		config.accounts = [Config(
			email=args.email,
			password=args.password,
		)]

	return config


def setupAccounts(config: Config) -> Config:
	def validEmail(email: str) -> bool:
		"""Validate Email."""
		pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
		return bool(re.match(pattern, email))

	loadedAccounts = []
	for account in config.accounts:
		if (
				not 'email' in account
				or not isinstance(account.email, str)
				or not validEmail(account.email)
		):
			logging.warning(
				f"[CREDENTIALS] Invalid email '{account.get('email', 'No email provided')}',"
				f" skipping this account"
			)
			continue
		if not 'password' in account or not isinstance(account['password'], str):
			logging.warning(
				f"[CREDENTIALS] Invalid password '{account.get('password', 'No password provided')}',"
				f" skipping this account"
			)
		loadedAccounts.append(account)

	if not loadedAccounts:
		noAccountsNotice = """
		[ACCOUNT] No valid account provided.
		[ACCOUNT] Please provide a valid account, either using command line arguments or a configuration file.
		[ACCOUNT] For command line, please use the following arguments (change the email and password):
		[ACCOUNT]   `--email youremail@domain.com --password yourpassword` 
		[ACCOUNT] For configuration file, please generate a configuration file using the `-C` argument,
		[ACCOUNT]   then edit the generated file by replacing the email and password using yours. 
		"""
		logging.error(noAccountsNotice)
		exit(1)

	random.shuffle(loadedAccounts)
	config.accounts = loadedAccounts
	return config

def createEmptyConfig(configPath: Path, config: Config) -> None:
	if configPath.is_file():
		logging.error(
			f"[CONFIG] A file already exists at '{configPath}'"
		)
		exit(1)

	emptyConfig = Config(
		{
			'apprise': {
				'urls': ['discord://{WebhookID}/{WebhookToken}']
			},
			'accounts': [
				{
					'email': 'Your Email 1',
					'password': 'Your Password 1',
					'totp': '0123 4567 89ab cdef',
					'proxy': 'http://user:pass@host1:port'
				},
				{
					'email': 'Your Email 2',
					'password': 'Your Password 2',
					'totp': '0123 4567 89ab cdef',
					'proxy': 'http://user:pass@host2:port'
				}
			]
		}
	)
	with open(configPath, "w", encoding="utf-8") as configFile:
		yaml.dump((emptyConfig | config).toDict(), configFile)
	logging.info(
		f"[CONFIG] A configuration file was created at '{configPath}'"
	)
	exit(0)

def update_config_from_env():
	"""Updates config.yaml with environment variables ACCOUNTS and TOKEN"""
	config_path = getProjectRoot() / "config.yaml"
	
	try:
		# Read existing config
		with open(config_path, 'r') as file:
			config = yaml.safe_load(file)
		
		# Update accounts from ACCOUNTS env var
		accounts_env = os.getenv('ACCOUNTS')
		if accounts_env:
			# Clear existing accounts
			config['accounts'] = []
			
			# Parse accounts string and update config
			account_pairs = accounts_env.split(',')
			for pair in account_pairs:
				email, password = pair.split(':')
				config['accounts'].append({
					'email': email.strip(),
					'password': password.strip()
				})
			print(f"Updated {len(account_pairs)} accounts from environment")
		
		# Update Discord webhook from TOKEN env var
		token_env = os.getenv('TOKEN')
		if token_env:
			if not config.get('apprise'):
				config['apprise'] = {}
			if not config['apprise'].get('urls'):
				config['apprise']['urls'] = []
			
			# Clear existing urls and add new token
			config['apprise']['urls'] = [token_env]
			print("Updated Discord webhook URL from environment")
		
		# Write updated config back to file
		with open(config_path, 'w') as file:
			yaml.safe_dump(config, file, default_flow_style=False)
			
	except Exception as e:
		print(f"Failed to update config from environment: {str(e)}")
		raise


def loadConfig(
	configFilename="config.yaml", defaultConfig=DEFAULT_CONFIG
) -> Config:
	args = argumentParser()

	update_config_from_env()

	if args.config:
		configFile = Path(args.config)
	else:
		configFile = getProjectRoot() / configFilename

	args_config = commandLineArgumentsAsConfig(args)

	if args.create_config:
		createEmptyConfig(configFile, args_config)

	config = defaultConfig | Config.fromYaml(configFile) | args_config
	config = setupAccounts(config)

	return config


def split_message(message: str, max_length: int = 1900) -> List[str]:
	"""Split a message into parts that fit within Discord's character limit while preserving code blocks"""
	if len(message) <= max_length:
		return [message]
	
	parts = []
	current_part = ""
	in_code_block = False
	code_block_lang = ""
	lines = message.split('\n')
	
	for line in lines:
		# Check for code block markers
		if line.startswith('```'):
			if not in_code_block:
				in_code_block = True
				code_block_lang = line[3:] if len(line) > 3 else ""
			else:
				in_code_block = False
		
		# Check if adding this line would exceed the limit
		new_part = current_part + line + '\n'
		if len(new_part) <= max_length:
			current_part = new_part
		else:
			# If we're in a code block, close it and start a new one in next part
			if in_code_block:
				current_part += "```\n"  # Close current code block
				parts.append(current_part.rstrip())
				current_part = f"```{code_block_lang}\n{line}\n"  # Start new code block
			else:
				parts.append(current_part.rstrip())
				current_part = line + '\n'
	
	# Add the last part
	if current_part:
		parts.append(current_part.rstrip())
	
	# Add part numbers and ensure all code blocks are closed
	total_parts = len(parts)
	if total_parts > 1:
		for i in range(total_parts):
			part = parts[i]
			# Count code block starts and ends
			starts = part.count("```") - part.count("```\n")
			if starts > 0:  # Unclosed code block
				part += "\n```"
			parts[i] = f"[Part {i+1}/{total_parts}]\n{part}"
	
	return parts


def sendNotification(title: str, body: str, e: Exception = None) -> None:
	try:
		if not CONFIG.apprise.enabled or (
			e and not CONFIG.get("apprise.notify.uncaught-exception")
		):
			return
		apprise = Apprise()
		urls: list[str] = CONFIG.apprise.urls
		if not urls:
			logging.debug("No urls found, not sending notification")
			return

		# Check if any Discord URLs are present
		has_discord = any(url.startswith("discord://") for url in urls)
		
		# Format the message for Discord
		formatted_body = body
		if has_discord:
			# Clean and escape the message for Discord formatting
			formatted_body = formatted_body.replace("```", "'''")  # Temporarily replace code blocks
			formatted_body = formatted_body.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
			
			# Handle exception formatting
			if e is not None:
				# Extract traceback if available
				if hasattr(e, '__traceback__'):
					import traceback
					tb_str = ''.join(traceback.format_tb(e.__traceback__))
					error_msg = f"Error: {str(e)}\n\nTraceback:\n{tb_str}"
				else:
					error_msg = str(e)
				
				# Clean up the error message
				error_msg = error_msg.replace("```", "'''")  # Remove nested code blocks
				error_msg = error_msg.replace("\t", "    ")  # Replace tabs with spaces
				
				# Add code block formatting
				formatted_body = f"{formatted_body}\n```python\n{error_msg}\n```"
			
			# Restore any legitimate code blocks
			formatted_body = formatted_body.replace("'''", "```")

		# Add all configured notification URLs
		for url in urls:
			try:
				apprise.add(url)
			except Exception as add_error:
				logging.error(f"Failed to add notification URL: {str(add_error)}")
				continue

		# Split message into parts if it's too long for Discord
		message_parts = [formatted_body]
		if has_discord:
			message_parts = split_message(formatted_body)

		# Send each part with retries
		for part_num, message_part in enumerate(message_parts, 1):
			part_title = title
			if len(message_parts) > 1:
				part_title = f"{title} (Part {part_num}/{len(message_parts)})"

			# Attempt to send notification with retries
			max_retries = 3
			for attempt in range(max_retries):
				try:
					notification_result = apprise.notify(
						title=str(part_title),
						body=message_part
					)

					if notification_result:
						logging.info(f"Notification part {part_num}/{len(message_parts)} sent successfully")
						break
					else:
						logging.error(f"Failed to send notification part {part_num} - attempt {attempt + 1}/{max_retries}")
						if attempt < max_retries - 1:
							time.sleep(2 ** attempt)  # Exponential backoff
				except Exception as notify_error:
					logging.error(f"Error sending notification part {part_num} (attempt {attempt + 1}/{max_retries}): {str(notify_error)}")
					if attempt < max_retries - 1:
						time.sleep(2 ** attempt)
						continue
					raise

			# Add a small delay between parts to avoid rate limiting
			if part_num < len(message_parts):
				time.sleep(1)

	except Exception as e:
		logging.error(f"Fatal error in sendNotification: {str(e)}")


def getAnswerCode(key: str, string: str) -> str:
	t = sum(ord(string[i]) for i in range(len(string)))
	t += int(key[-2:], 16)
	return str(t)


def formatNumber(number, num_decimals=2) -> str:
	return pylocale.format_string(f"%10.{num_decimals}f", number, grouping=True).strip()


def getBrowserConfig(sessionPath: Path) -> dict | None:
	configFile = sessionPath / "config.json"
	if not configFile.exists():
		return
	with open(configFile, "r") as f:
		return json.load(f)


def saveBrowserConfig(sessionPath: Path, config: dict) -> None:
	configFile = sessionPath / "config.json"
	with open(configFile, "w") as f:
		json.dump(config, f)


def makeRequestsSession(session: Session = requests.session()) -> Session:
	retry = Retry(
		total=CONFIG.retries.max,
		backoff_factor=1,
		status_forcelist=[
			500,
			502,
			503,
			504,
		],
	)
	session.mount(
		"https://", HTTPAdapter(max_retries=retry)
	)  # See https://stackoverflow.com/a/35504626/4164390 to finetune
	session.mount(
		"http://", HTTPAdapter(max_retries=retry)
	)  # See https://stackoverflow.com/a/35504626/4164390 to finetune
	return session


CONFIG = loadConfig()
