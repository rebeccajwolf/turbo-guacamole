import contextlib
import logging
from random import randint, choice, uniform
from time import sleep

from selenium.common import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.common.exceptions import (
	ElementClickInterceptedException,
	ElementNotInteractableException,
	NoSuchElementException,
	StaleElementReferenceException,
)

from src.browser import Browser
from src.constants import REWARDS_URL
from src.utils import CONFIG, sendNotification, getAnswerCode, active_sleep, take_screenshot


class Activities:
	def __init__(self, browser: Browser):
		self.browser = browser
		self.webdriver = browser.webdriver

	def openDailySetActivity(self, cardId: int):
		# Open the Daily Set activity for the given cardId
		cardId += 1
		element = self.webdriver.find_element(
			By.XPATH,
			f'//*[@id="daily-sets"]/mee-card-group[1]/div/mee-card[{cardId}]/div/card-content/mee-rewards-daily-set-item-content/div/a',
		)
		self.browser.utils.click(element)
		sleep(5)  # Add small delay to ensure click is registered
		# self.browser.utils.switchToNewTab()

	def openMorePromotionsActivity(self, offerId: str):
		while True:
			try:
				# cardId += 1
				# Open the More Promotions activity for the given cardId
				# element = self.webdriver.find_element(
				# 	By.CSS_SELECTOR,
				# 	f"#more-activities > .m-card-group > .ng-scope:nth-child({cardId}) #ma-card-link .pointLink",
				# )
				# element = self.webdriver.find_element(
				# 	By.CSS_SELECTOR,
				# 	f"#more-activities > .m-card-group > .ng-scope:nth-child({cardId}) .ds-card-sec",
				# )
				element = self.webdriver.find_element(
					By.CSS_SELECTOR,
					f"[data-bi-id^=\"{offerId}\"] .pointLink:not(.contentContainer .pointLink)",
				)
				# Scroll element into view
				self.webdriver.execute_script("arguments[0].scrollIntoView(true);", element)
				sleep(3)  # Wait for scroll
				take_screenshot(self.webdriver, f"Before_Clicking_cardID{offerId}")
				self.browser.utils.mouseClick(element)
				sleep(5)  # Add small delay to ensure click is registered
				# self.browser.utils.switchToNewTab()
				break
			except(NoSuchElementException):
				self.webdriver.refresh()
				continue

	def completeSearch(self):
		# Simulate completing a search activity
		pass

	def completeSurvey(self):
		# Simulate completing a survey activity
		# noinspection SpellCheckingInspection
		# self.webdriver.find_element(By.ID, f"btoption{randint(0, 1)}").click()
		
		res = True
		# click poll option
		while res:
			try:
				if self.browser.utils.isElementExists(By.XPATH, '//*[@class="bt_headerMessage"]'):
					res = False
				logging.debug(f"Poll Quiz Doing...")
				# self.browser.waitUntilVisible(By.ID, 'btPollOverlay', 30)
				sleep(3)
				self.browser.utils.waitUntilClickable(By.ID, 'btoption0', timeToWait=20)
				choices = ['btoption0', 'btoption1']
				option = self.webdriver.find_element(By.ID, choice(choices))
				sleep(3)
				self.browser.utils.mouseClick(option)
				sleep(4)
			except:
				pass


	def waitUntilQuizLoads(self):
		"""Wait until quiz loads"""
		tries = 0
		refreshCount = 0
		while True:
			try:
				self.webdriver.find_element(
					By.XPATH, '//*[@id="currentQuestionContainer"]')
				return True
			except:
				if tries < 10:
					tries += 1
					sleep(0.5)
				else:
					if refreshCount < 5:
						self.webdriver.refresh()
						refreshCount += 1
						tries = 0
						sleep(5)
					else:
						return False

	def completeQuiz(self):
		# Simulate completing a quiz activity
		sleep(12)
		if not self.waitUntilQuizLoads():
			self.browser.utils.resetTabs()
			return
		with contextlib.suppress(TimeoutException):
			startQuiz = self.browser.utils.waitUntilQuizLoads()
			self.browser.utils.click(startQuiz)
		self.browser.utils.waitUntilVisible(
			By.XPATH, '//*[@id="currentQuestionContainer"]/div/div[1]', 180
		)
		currentQuestionNumber: int = self.webdriver.execute_script(
			"return _w.rewardsQuizRenderInfo.currentQuestionNumber"
		)
		numberOfQuestions = self.webdriver.execute_script(
			"return _w.rewardsQuizRenderInfo.maxQuestions"
		)
		numberOfOptions = self.webdriver.execute_script(
			"return _w.rewardsQuizRenderInfo.numberOfOptions"
		)
		answerdQuestions = self.webdriver.execute_script(
			"return _w.rewardsQuizRenderInfo.CorrectlyAnsweredQuestionCount"
		)
		numberOfQuestions -= answerdQuestions
		for _ in range(numberOfQuestions):
			if numberOfOptions == 8:
				answers = []
				for i in range(numberOfOptions):
					isCorrectOption = self.webdriver.find_element(
						By.ID, f"rqAnswerOption{i}"
					).get_attribute("iscorrectoption")
					if isCorrectOption and isCorrectOption.lower() == "true":
						answers.append(f"rqAnswerOption{i}")
				for answer in answers:
					element = self.browser.utils.waitUntilClickable(By.ID, answer)
					self.browser.utils.mouseClick(element)
					self.browser.utils.waitUntilQuestionRefresh()
			elif numberOfOptions in [2, 3, 4]:
				correctOption = self.webdriver.execute_script(
					"return _w.rewardsQuizRenderInfo.correctAnswer"
				)
				for i in range(numberOfOptions):
					if (
						self.webdriver.find_element(
							By.ID, f"rqAnswerOption{i}"
						).get_attribute("data-option")
						== correctOption
					):
						element = self.browser.utils.waitUntilClickable(
							By.ID, f"rqAnswerOption{i}"
						)
						self.browser.utils.mouseClick(element)

						self.browser.utils.waitUntilQuestionRefresh()
						break

	def completeABC(self):
		# Simulate completing an ABC activity
		counter = self.webdriver.find_element(
			By.XPATH, '//*[@id="QuestionPane0"]/div[2]'
		).text[:-1][1:]
		numberOfQuestions = max(int(s) for s in counter.split() if s.isdigit())
		for question in range(numberOfQuestions):
			element = self.webdriver.find_element(
				By.ID, f"questionOptionChoice{question}{randint(0, 2)}"
			)
			self.browser.utils.click(element)
			sleep(randint(10, 15))
			element = self.webdriver.find_element(By.ID, f"nextQuestionbtn{question}")
			self.browser.utils.click(element)
			sleep(randint(10, 15))

	def completeThisOrThat(self):
		# Simulate completing a This or That activity
		sleep(12)
		if not self.waitUntilQuizLoads():
			self.browser.utils.resetTabs()
			return
		with contextlib.suppress(TimeoutException):
			startQuiz = self.browser.utils.waitUntilQuizLoads()
			self.browser.utils.click(startQuiz)
		self.browser.utils.waitUntilVisible(
			By.XPATH, '//*[@id="currentQuestionContainer"]/div/div[1]', 180
		)
		sleep(randint(10, 15))
		for _ in range(10):
			correctAnswerCode = self.webdriver.execute_script(
				"return _w.rewardsQuizRenderInfo.correctAnswer"
			)
			answer1, answer1Code = self.getAnswerAndCode("rqAnswerOption0")
			answer2, answer2Code = self.getAnswerAndCode("rqAnswerOption1")
			answerToClick: WebElement
			if answer1Code == correctAnswerCode:
				answerToClick = answer1
			elif answer2Code == correctAnswerCode:
				answerToClick = answer2

			self.browser.utils.click(answerToClick)
			sleep(randint(10, 15))

	def getAnswerAndCode(self, answerId: str) -> tuple[WebElement, str]:
		# Helper function to get answer element and its code
		answerEncodeKey = self.webdriver.execute_script("return _G.IG")
		answer = self.webdriver.find_element(By.ID, answerId)
		answerTitle = answer.get_attribute("data-option")
		return (
			answer,
			getAnswerCode(answerEncodeKey, answerTitle),
		)

	def searchOnBing(self, query: str):

		def completeTrackingSeach():
			if self.browser.utils.isElementExists(By.ID, "g_pack_track_form"):
				logging.debug(f'Doing Tracking Search Activity...')
				textbar = self.webdriver.find_element(By.XPATH, '//*[@class="tracking_Number_Input"]/input')
				sleep(1)
				textbar.click()
				sleep(1)
				textbar.send_keys("9205 5000 0000 0000 0000 00")
				sleep(1)
				self.webdriver.find_element(By.CLASS_NAME, "pack_tracking_track_button").click()

		def completeDictionarySearch():
			self.browser.utils.waitUntilVisible(By.ID, "dictautodd_c", 30)
			if self.browser.utils.isElementExists(By.ID, "dictautodd_c"):
				logging.debug(f'Doing Dictionary Search Activity...')
				textbar = self.webdriver.find_element(By.ID, 'dictautodd_c')
				sleep(1)
				textbar.click()
				sleep(1)
				textbar.send_keys("demure")
				sleep(1)
				self.webdriver.find_element(By.ID, "dc_searchbtn").click()

		try:
			# self.browser.utils.waitUntilVisible(By.ID, "modern-flyout", timeToWait=30)
			searchbar = self.browser.utils.waitUntilClickable(By.ID, "sb_form_q", timeToWait=30)
			self.browser.utils.mouseClick(searchbar)
			take_screenshot(self.webdriver, f"searchOnBing_AfterClick_{query}")
			sleep(2)
			searchbar.clear()
			sleep(2)
			for char in query:
				searchbar.send_keys(char)
				sleep(uniform(0.2, 0.45))
			sleep(3)
			take_screenshot(self.webdriver, f"searchOnBing_BeforeSubmit_{query}")
			searchbar.submit()
			sleep(2)

			if "define" in query:
				completeDictionarySearch()
			elif "tracking" in query:
				completeTrackingSeach()
			take_screenshot(self.webdriver, "searchOnBing_Complete")
		except Exception as e:
			take_screenshot(self.webdriver, "searchOnBing_error")
			logging.warning(f"Error Occured while Doing Activity: {e}")
			raise


	def doActivity(self, activity: dict, activities: list[dict]) -> None:
		max_retries = 4
		retry_count = 0
		while retry_count < max_retries:
			try:
				activityTitle = cleanupActivityTitle(activity["title"])
				logging.debug(f"activityTitle={activityTitle}")
				if activity["complete"] is True or activity["pointProgressMax"] == 0 or activity["exclusiveLockedFeatureStatus"] == "locked":
					logging.debug("Already done, returning")
					return
				if "is_unlocked" in activity["attributes"] and activity["attributes"]["is_unlocked"] == "False":
					logging.debug("Activity locked, returning")
					return
				if activityTitle in CONFIG.activities.ignore:
					logging.debug(f"Ignoring {activityTitle}")
					return

					
				# Open the activity for the activity
				cardId = activities.index(activity)
				if "membercenter" in activity["name"].lower() or "exploreonbing" in activity["name"].lower():
					offerId = activity["name"]
				else:
					offerId = activity["offerId"]
				isDailySet = (
					"daily_set_date" in activity["attributes"]
					and activity["attributes"]["daily_set_date"]
				)


				if isDailySet:
					self.openDailySetActivity(cardId)
				else:
					self.openMorePromotionsActivity(offerId)


				sleep(7)
				try:
					if self.webdriver.find_element(By.XPATH, '//*[@id="modal-host"]/div[2]/button').is_displayed():
						self.webdriver.find_element(By.XPATH, '//*[@id="modal-host"]/div[2]/button').click()
						return
				except:
					pass
				finally:
					# Check if new tab exists before switching
					if len(self.webdriver.window_handles) > 1:
						self.browser.utils.switchToNewTab()
				sleep(7)


				
				if activityTitle in CONFIG.activities.search:
					self.searchOnBing(CONFIG.activities.search[activityTitle])
				elif "poll" in activityTitle:
					# logging.info(f"[ACTIVITY] Completing poll of card {cardId}")
					# Complete survey for a specific scenario
					self.completeSurvey()
				elif activity["promotionType"] == "urlreward":
					# Complete search for URL reward
					self.completeSearch()
				elif activity["promotionType"] == "quiz":
					# Complete different types of quizzes based on point progress max
					if activity["pointProgressMax"] == 10:
						self.completeABC()
					elif activity["pointProgressMax"] in [30, 40]:
						self.completeQuiz()
					elif activity["pointProgressMax"] == 50:
						self.completeThisOrThat()
				else:
					# Default to completing search
					self.completeSearch()
			except Exception:
				retry_count += 1
				if retry_count >= max_retries:
					logging.error(f"[ACTIVITY] Error doing {activityTitle}", exc_info=True)
				self.browser.utils.resetTabs()
				continue
			logging.debug(f"Entering Sleep after Activity")
			sleep(randint(CONFIG.cooldown.min, CONFIG.cooldown.max))
			logging.debug(f"Finished Sleep after Activity")
			self.browser.utils.resetTabs()
			break

	def completeActivities(self):
		logging.info("[DAILY SET] " + "Trying to complete the Daily Set...")
		dailySetPromotions = self.browser.utils.getDailySetPromotions()
		self.browser.utils.goToRewards()
		for activity in dailySetPromotions:
			self.doActivity(activity, dailySetPromotions)
		logging.info("[DAILY SET] Done")

		logging.info("[MORE PROMOS] " + "Trying to complete More Promotions...")
		morePromotions: list[dict] = self.browser.utils.getMorePromotions()
		self.browser.utils.goToRewards()
		for activity in morePromotions:
			self.doActivity(activity, morePromotions)
		logging.info("[MORE PROMOS] Done")

		# todo Send one email for all accounts?
		# fixme This is falsely considering some activities incomplete when complete
		if CONFIG.get('apprise.notify.incomplete-activity'):
			incompleteActivities: list[str] = []
			for activity in (
				self.browser.utils.getDailySetPromotions()
				+ self.browser.utils.getMorePromotions()
			):  # Have to refresh
				if activity["pointProgress"] < activity["pointProgressMax"]:
					incompleteActivities.append(cleanupActivityTitle(activity["title"]))
			for incompleteActivityToIgnore in CONFIG.activities.ignore:
				if incompleteActivityToIgnore in incompleteActivities:
					incompleteActivities.remove(incompleteActivityToIgnore)
			if incompleteActivities:
				logging.info(f"incompleteActivities: {incompleteActivities}")
				sendNotification(
					f"We found some incomplete activities for {self.browser.email}",
					'"' + '", "'.join(incompleteActivities) + '"\n' + REWARDS_URL,
				)


def cleanupActivityTitle(activityTitle: str) -> str:
	return activityTitle.replace("\u200b", "").replace("\xa0", " ")
