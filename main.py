import csv
import schedule
import random
import json
import logging
import logging.config
import logging.handlers as handlers
import sys
import traceback
import os
import wget
import zipfile
import shutil
from datetime import datetime
from enum import Enum, auto
from threading import Thread, Event
from pathlib import Path

from src import (
	Browser,
	Login,
	PunchCards,
	Searches,
	ReadToEarn,
)
from src.activities import Activities
from src.browser import RemainingSearches
from src.loggingColoredFormatter import ColoredFormatter
from src.utils import CONFIG, sendNotification, getProjectRoot, formatNumber



def main():
	# setupLogging()

	# Load previous day's points data
	previous_points_data = load_previous_points_data()

	for currentAccount in CONFIG.accounts:
		max_retries = 17
		retry_count = 0
		while retry_count < max_retries:
			try:
				earned_points = executeBot(currentAccount)
				previous_points = previous_points_data.get(currentAccount.email, 0)

				# Calculate the difference in points from the prior day
				points_difference = earned_points - previous_points

				# Append the daily points and points difference to CSV and Excel
				log_daily_points_to_csv(earned_points, points_difference)

				# Update the previous day's points data
				previous_points_data[currentAccount.email] = earned_points

				logging.info(
					f"[POINTS] Data for '{currentAccount.email}' appended to the file."
				)
				break  # Success - exit retry loop
			except AccountLockedException:
				break
			except AccountSuspendedException:
				break
			except Exception as e1:
				retry_count += 1
				if retry_count < max_retries:
					logging.error(
						f"Error executing account {currentAccount.username} (attempt {retry_count}/{max_retries}): {str(e)}"
					)
					# Add exponential backoff
					wait_time = 2 ** retry_count
					logging.info(f"Waiting {wait_time} seconds before retry...")
					time.sleep(wait_time)
				else:
					logging.error(
						f"Failed to execute account {currentAccount.username} after {max_retries} attempts. Moving to next account."
					)
				sendNotification(
					f"⚠️ Error executing {currentAccount.username} after {max_retries} retries",
					traceback.format_exc(),
					e1,
				)

	# Save the current day's points data for the next day in the "logs" folder
	save_previous_points_data(previous_points_data)
	logging.info("[POINTS] Data saved for the next day.")


def log_daily_points_to_csv(earned_points, points_difference):
	logs_directory = getProjectRoot() / "logs"
	csv_filename = logs_directory / "points_data.csv"

	# Create a new row with the date, daily points, and points difference
	date = datetime.now().strftime("%Y-%m-%d")
	new_row = {
		"Date": date,
		"Earned Points": earned_points,
		"Points Difference": points_difference,
	}

	fieldnames = ["Date", "Earned Points", "Points Difference"]
	is_new_file = not csv_filename.exists()

	with open(csv_filename, mode="a", newline="") as file:
		writer = csv.DictWriter(file, fieldnames=fieldnames)

		if is_new_file:
			writer.writeheader()

		writer.writerow(new_row)

def downloadWebDriver():
	"""Downloads and sets up chromedriver in the correct location"""
	try:
		# Download the zip file
		download_url = "https://storage.googleapis.com/chrome-for-testing-public/128.0.6613.119/linux64/chromedriver-linux64.zip"
		latest_driver_zip = wget.download(download_url, 'chromedriver.zip')
		
		# Create a temporary directory for extraction
		temp_dir = Path('temp_chromedriver')
		temp_dir.mkdir(exist_ok=True)
		
		# Extract the zip file to temp directory
		with zipfile.ZipFile(latest_driver_zip, 'r') as zip_ref:
			zip_ref.extractall(temp_dir)
		
		# Move the chromedriver to the correct location
		chromedriver_src = temp_dir / 'chromedriver-linux64' / 'chromedriver'
		chromedriver_dest = getProjectRoot() / 'chromedriver'
		
		# Ensure source file exists
		if not chromedriver_src.exists():
			raise FileNotFoundError(f"ChromeDriver not found in {chromedriver_src}")
		
		# Move the file and set permissions
		shutil.move(str(chromedriver_src), str(chromedriver_dest))
		os.chmod(chromedriver_dest, 0o755)
		
		# Cleanup
		os.remove(latest_driver_zip)
		shutil.rmtree(temp_dir)
		
		logging.info("ChromeDriver successfully installed")
		
	except Exception as e:
		logging.error(f"Error downloading ChromeDriver: {str(e)}")
		raise

def setupLogging():
	_format = CONFIG.logging.format
	terminalHandler = logging.StreamHandler(sys.stdout)
	terminalHandler.setFormatter(ColoredFormatter(_format))

	logs_directory = getProjectRoot() / "logs"
	logs_directory.mkdir(parents=True, exist_ok=True)

	# so only our code is logged if level=logging.DEBUG or finer
	logging.config.dictConfig(
		{
			"version": 1,
			"disable_existing_loggers": True,
		}
	)
	logging.basicConfig(
		level=logging.getLevelName(CONFIG.logging.level.upper()),
		format=_format,
		handlers=[
			handlers.TimedRotatingFileHandler(
				logs_directory / "activity.log",
				when="midnight",
				interval=1,
				backupCount=2,
				encoding="utf-8",
			),
			terminalHandler,
		],
	)


class AppriseSummary(Enum):
	"""
	configures how results are summarized via Apprise
	"""

	ALWAYS = auto()
	"""
	the default, as it was before, how many points were gained and goal percentage if set
	"""
	ON_ERROR = auto()
	"""
	only sends email if for some reason there's remaining searches 
	"""
	NEVER = auto()
	"""
	never send summary 
	"""


def executeBot(currentAccount):
	logging.info(f"********************{currentAccount.email}********************")

	startingPoints: int | None = None
	accountPoints: int
	remainingSearches: RemainingSearches
	goalTitle: str
	goalPoints: int

	if CONFIG.search.type in ("desktop", "both", None):
		with Browser(mobile=False, account=currentAccount) as desktopBrowser:
			utils = desktopBrowser.utils
			Login(desktopBrowser).login()
			startingPoints = utils.getAccountPoints()
			logging.info(
				f"[POINTS] You have {formatNumber(startingPoints)} points on your account"
			)
			Activities(desktopBrowser).completeActivities()
			PunchCards(desktopBrowser).completePunchCards()
			# VersusGame(desktopBrowser).completeVersusGame()

			with Searches(desktopBrowser) as searches:
				searches.bingSearches()

			goalPoints = utils.getGoalPoints()
			goalTitle = utils.getGoalTitle()

			remainingSearches = desktopBrowser.getRemainingSearches(
				desktopAndMobile=True
			)
			accountPoints = utils.getAccountPoints()

	if CONFIG.search.type in ("mobile", "both", None):
		with Browser(mobile=True, account=currentAccount) as mobileBrowser:
			utils = mobileBrowser.utils
			Login(mobileBrowser).login()
			if startingPoints is None:
				startingPoints = utils.getAccountPoints()
			ReadToEarn(mobileBrowser).completeReadToEarn()
			with Searches(mobileBrowser) as searches:
				searches.bingSearches()

			goalPoints = utils.getGoalPoints()
			goalTitle = utils.getGoalTitle()

			remainingSearches = mobileBrowser.getRemainingSearches(
				desktopAndMobile=True
			)
			accountPoints = utils.getAccountPoints()

	logging.info(
		f"[POINTS] You have earned {formatNumber(accountPoints - startingPoints)} points this run !"
	)
	logging.info(f"[POINTS] You are now at {formatNumber(accountPoints)} points !")
	appriseSummary = AppriseSummary[CONFIG.apprise.summary]
	if appriseSummary == AppriseSummary.ALWAYS:
		goalStatus = ""
		if goalPoints > 0:
			logging.info(
				f"[POINTS] You are now at {(formatNumber((accountPoints / goalPoints) * 100))}% of your "
				f"goal ({goalTitle}) !"
			)
			goalStatus = (
				f"🎯 Goal reached: {(formatNumber((accountPoints / goalPoints) * 100))}%"
				f" ({goalTitle})"
			)

		sendNotification(
			"Daily Points Update",
			"\n".join(
				[
					f"👤 Account: {currentAccount.email}",
					f"⭐️ Points earned today: {formatNumber(accountPoints - startingPoints)}",
					f"💰 Total points: {formatNumber(accountPoints)}",
					goalStatus,
				]
			),
		)
	elif appriseSummary == AppriseSummary.ON_ERROR:
		if remainingSearches.getTotal() > 0:
			sendNotification(
				"Error: remaining searches",
				f"account email: {currentAccount.email}, {remainingSearches}",
			)
	elif appriseSummary == AppriseSummary.NEVER:
		pass

	return accountPoints


def export_points_to_csv(points_data):
	logs_directory = getProjectRoot() / "logs"
	csv_filename = logs_directory / "points_data.csv"
	with open(csv_filename, mode="a", newline="") as file:  # Use "a" mode for append
		fieldnames = ["Account", "Earned Points", "Points Difference"]
		writer = csv.DictWriter(file, fieldnames=fieldnames)

		# Check if the file is empty, and if so, write the header row
		if file.tell() == 0:
			writer.writeheader()

		for data in points_data:
			writer.writerow(data)


# Define a function to load the previous day's points data from a file in the "logs" folder
def load_previous_points_data():
	try:
		with open(getProjectRoot() / "logs" / "previous_points_data.json", "r") as file:
			return json.load(file)
	except FileNotFoundError:
		return {}


# Define a function to save the current day's points data for the next day in the "logs" folder
def save_previous_points_data(data):
	logs_directory = getProjectRoot() / "logs"
	with open(logs_directory / "previous_points_data.json", "w") as file:
		json.dump(data, file, indent=4)

class ScheduleManager:
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
				# Use event with timeout instead of sleep for more responsive shutdown
				self.stop_event.wait(timeout=random.uniform(1, 2))
			except Exception as e:
				logging.error(f"Schedule error: {str(e)}")
				time.sleep(5)  # Wait before retrying on error

def setup_schedule():
	"""Set up the schedule with randomized times"""
	# Clear any existing jobs
	schedule.clear()

	# Add some randomization to job times to avoid detection
	base_morning_hour = 5
	base_evening_hour = 19
	
	# Add random minutes to base hours
	morning_time = f"{base_morning_hour:02d}:{random.randint(0, 59):02d}"
	evening_time = f"{base_evening_hour:02d}:{random.randint(0, 59):02d}"

	# Schedule jobs
	schedule.every().day.at(morning_time).do(run_job_with_activity)
	schedule.every().day.at(evening_time).do(run_job_with_activity)
	
	logging.info(f"Scheduled jobs for {morning_time} and {evening_time}")


def main_with_schedule():
	"""Main function with proper schedule handling"""
	try:
		# Initial setup
		setupLogging()
		logging.info("Starting application...")

		downloadWebDriver()
		
		# Run initial job
		try:
			
			main()
			
		except Exception as e:
			logging.exception("Job execution error")
			sendNotification(
				"⚠️ Error occurred, please check the log",
				traceback.format_exc(),
				e
			)
		
		# Set up and start scheduler
		setup_schedule()
		schedule_manager = ScheduleManager()
		schedule_manager.start()
		
		# Wait for keyboard interrupt or other signals
		try:
			while True:
				time.sleep(1)
		except KeyboardInterrupt:
			logging.info("Received shutdown signal, cleaning up...")
		finally:
			schedule_manager.stop()
			
	except Exception as e:
		logging.exception("Fatal error occurred")
		sendNotification(
			"⚠️ Fatal error occurred",
			traceback.format_exc(),
			e
		)
		raise

if __name__ == "__main__":
	main_with_schedule()
