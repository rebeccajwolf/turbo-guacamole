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
import time
import requests
from datetime import datetime, timedelta
from enum import Enum, auto
from threading import Thread, Event, Lock
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
from src.exceptions import *
from src.background_monitor import BackgroundMonitor



def main():
	# setupLogging()

	# Load previous day's points data
	previous_points_data = load_previous_points_data()

	for currentAccount in CONFIG.accounts:
		max_retries = 17
		retry_count = 0
		while retry_count < max_retries:
			try:
				# Check if we should stop before processing each account
				if check_for_stop_signal():
					logging.info("Stop signal detected, stopping account processing")
					return 0  # Return early with 0 points
					
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
						f"Error executing account {currentAccount.email} (attempt {retry_count}/{max_retries}): {str(e1)}"
					)
					# Add exponential backoff
					wait_time = 2 ** retry_count
					logging.info(f"Waiting {wait_time} seconds before retry...")
					time.sleep(wait_time)
				else:
					logging.error(
						f"Failed to execute account {currentAccount.email} after {max_retries} attempts. Moving to next account."
					)
				sendNotification(
					f"⚠️ Error executing {currentAccount.email} after {max_retries} retries",
					traceback.format_exc(),
					e1,
				)

	# Save the current day's points data for the next day in the "logs" folder
	save_previous_points_data(previous_points_data)
	logging.info("[POINTS] Data saved for the next day.")
	return previous_points_data.get(currentAccount.email, 0) if 'currentAccount' in locals() else 0


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
		url = 'https://chromedriver.storage.googleapis.com/LATEST_RELEASE'
		response = requests.get(url)
		version_number = response.text
		# Download the zip file
		download_url = "https://chromedriver.storage.googleapis.com/" + version_number +"/chromedriver_linux64.zip"
		latest_driver_zip = wget.download(download_url, 'chromedriver.zip')
		
		# Create a temporary directory for extraction
		temp_dir = Path('temp_chromedriver')
		temp_dir.mkdir(exist_ok=True)
		
		# Extract the zip file to temp directory
		with zipfile.ZipFile(latest_driver_zip, 'r') as zip_ref:
			zip_ref.extractall(temp_dir)
		
		# Move the chromedriver to the correct location
		chromedriver_src = temp_dir / 'chromedriver'
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

	try:
		# Check for stop signal before starting browser sessions
		if check_for_stop_signal():
			logging.info("Stop signal detected before starting browser sessions")
			return 0  # Return early with 0 points

		if CONFIG.search.type in ("desktop", "both", None):
			with Browser(mobile=False, account=currentAccount) as desktopBrowser:
				utils = desktopBrowser.utils
				Login(desktopBrowser).login()
				startingPoints = utils.getAccountPoints()
				logging.info(
					f"[POINTS] You have {formatNumber(startingPoints)} points on your account"
				)
				
				# Check for stop signal before activities
				if check_for_stop_signal():
					logging.info("Stop signal detected before activities")
					return startingPoints
					
				Activities(desktopBrowser).completeActivities()
				
				# Check for stop signal before punch cards
				if check_for_stop_signal():
					logging.info("Stop signal detected before punch cards")
					return utils.getAccountPoints()
					
				PunchCards(desktopBrowser).completePunchCards()
				# VersusGame(desktopBrowser).completeVersusGame()

				# Check for stop signal before searches
				if check_for_stop_signal():
					logging.info("Stop signal detected before desktop searches")
					return utils.getAccountPoints()

				with Searches(desktopBrowser) as searches:
					searches.bingSearches()

				goalPoints = utils.getGoalPoints()
				goalTitle = utils.getGoalTitle()

				remainingSearches = desktopBrowser.getRemainingSearches(
					desktopAndMobile=True
				)
				accountPoints = utils.getAccountPoints()

		if CONFIG.search.type in ("mobile", "both", None):
			# Check for stop signal before mobile browser
			if check_for_stop_signal():
				logging.info("Stop signal detected before mobile browser")
				return accountPoints if 'accountPoints' in locals() else startingPoints or 0
				
			with Browser(mobile=True, account=currentAccount) as mobileBrowser:
				utils = mobileBrowser.utils
				Login(mobileBrowser).login()
				if startingPoints is None:
					startingPoints = utils.getAccountPoints()
					
				# Check for stop signal before read to earn
				if check_for_stop_signal():
					logging.info("Stop signal detected before read to earn")
					return utils.getAccountPoints()
					
				ReadToEarn(mobileBrowser).completeReadToEarn()
				
				# Check for stop signal before mobile searches
				if check_for_stop_signal():
					logging.info("Stop signal detected before mobile searches")
					return utils.getAccountPoints()
					
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
	except AccountLockedException:
		sendNotification(
			"Account Update",
			"\n".join(
				[
					f"👤 Account: {currentAccount.email}",
					f"Your account has been locked !",
					f"⚠️ Locked",
				]
			),
		)
		raise
	except AccountSuspendedException:
		sendNotification(
			"Account Update",
			"\n".join(
				[
					f"👤 Account: {currentAccount.email}",
					f"Your account has been suspended !",
					f"❌ Suspended",
				]
			),
		)
		raise
	except Exception as e:
		# Log the exception
		logging.error(f"Error during execution: {str(e)}")
		raise


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

class JobManager:
		"""Manages job execution and ensures only one job runs at a time"""
		
		def __init__(self):
				self.current_job_lock = Lock()
				self.current_job_thread = None
				self.stop_event = Event()
				self.job_running = False
				self.last_schedule_check = datetime.now()
				self.background_monitor = BackgroundMonitor(check_interval=15.0)  # Check every 15 seconds
				self.browser_instances = []  # Track active browser instances
				self.force_release_lock = Event()  # New event to force lock release
		
		def is_job_running(self):
				"""Check if a job is currently running"""
				return self.job_running
		
		def stop_current_job(self):
				"""Signal the current job to stop"""
				if self.job_running:
						logging.info("Stopping current job...")
						self.stop_event.set()
						self.force_release_lock.set()  # Signal to force release the lock
						
						# Wait for a short time to allow job to clean up
						time.sleep(2)
						
						# If job is still running after timeout, force terminate
						if self.job_running and self.current_job_thread and self.current_job_thread.is_alive():
								logging.warning("Job still running after timeout, forcing cleanup")
								
								# Force cleanup of browser instances
								self._force_cleanup_browsers()
								
								# Force release the lock if it's still held
								if not self.current_job_lock.acquire(blocking=False):
										# Lock is still held, we need to force release it
										# This is a hack, but we need to ensure the lock is released
										self._force_release_lock()
								else:
										# We acquired the lock, so release it
										self.current_job_lock.release()
								
								# Mark job as not running
								self.job_running = False
						
						return True
				return False
		
		def _force_cleanup_browsers(self):
				"""Force cleanup of all browser instances"""
				for browser in self.browser_instances:
						try:
								if hasattr(browser, 'cleanup'):
										browser.cleanup()
						except Exception as e:
								logging.error(f"Error cleaning up browser: {str(e)}")
				
				# Clear the list
				self.browser_instances = []
		
		def _force_release_lock(self):
				"""Force release the lock - use with extreme caution"""
				try:
						# This is a hack to force release the lock
						# It's not thread-safe, but we're in a desperate situation
						self.current_job_lock._owner = None
						self.current_job_lock._count = 0
						
						logging.warning("Forced lock release - this is a last resort measure")
				except Exception as e:
						logging.error(f"Failed to force release lock: {str(e)}")
		
		def run_job(self, job_function, job_name="unnamed"):
				"""Run a job with proper management"""
				# Reset force release event
				self.force_release_lock.clear()
				
				# Try to acquire the lock, but don't block if we can't
				lock_acquired = False
				try:
						if not self.current_job_lock.acquire(blocking=False):
								logging.warning(f"Another job is already running, stopping it first")
								self.stop_current_job()
								
								# Wait for the lock to be released with timeout
								lock_acquired = self.current_job_lock.acquire(blocking=True, timeout=5)
								if not lock_acquired:
										logging.error("Failed to acquire job lock after stopping previous job")
										# Force release as a last resort
										self._force_release_lock()
										lock_acquired = self.current_job_lock.acquire(blocking=True, timeout=5)
										if not lock_acquired:
												logging.error("Failed to acquire job lock even after force release")
												return
						else:
								lock_acquired = True
						
						# Reset the stop event
						self.stop_event.clear()
						self.job_running = True
						self.browser_instances = []  # Reset browser instances list
						
						# Start the job in a new thread
						self.current_job_thread = Thread(
								target=self._job_wrapper,
								args=(job_function, job_name),
								daemon=True
						)
						self.current_job_thread.start()
						
						# Start the background monitor to check for stop signals
						self.background_monitor.start(
								check_function=self._should_stop_for_schedule,
								action_function=self._handle_stop_signal
						)
						
						logging.info(f"Started new job '{job_name}' at {datetime.now().strftime('%H:%M:%S')}")
				except Exception as e:
						logging.exception(f"Error starting job '{job_name}': {str(e)}")
						self.job_running = False
						if lock_acquired:
								self.current_job_lock.release()
		
		def _job_wrapper(self, job_function, job_name):
				"""Wrapper to handle job execution and cleanup"""
				lock_released = False
				try:
						# Set a global flag that can be checked by long-running processes
						global JOB_STOP_EVENT
						JOB_STOP_EVENT = self.stop_event
						
						# Run the job
						job_function()
				except Exception as e:
						logging.exception(f"Error in job '{job_name}' execution: {str(e)}")
				finally:
						# Clean up
						self.job_running = False
						self.background_monitor.stop()  # Stop the background monitor
						
						# Clean up any remaining browser instances
						for browser in self.browser_instances:
								try:
										if hasattr(browser, 'cleanup'):
												browser.cleanup()
								except Exception as e:
										logging.error(f"Error cleaning up browser: {str(e)}")
						
						self.browser_instances = []  # Clear the list
						
						# Check if we need to force release the lock
						if self.force_release_lock.is_set():
								logging.warning("Force release lock event detected during cleanup")
								lock_released = True  # Mark as released since we're forcing it
						
						# Release the lock if we haven't already forced it
						if not lock_released:
								try:
										self.current_job_lock.release()
								except RuntimeError as e:
										logging.error(f"Error releasing lock: {str(e)}")
						
						logging.info(f"Job '{job_name}' completed at {datetime.now().strftime('%H:%M:%S')}")
		
		def _should_stop_for_schedule(self):
				"""Check if we should stop the current job for a scheduled job"""
				# Check if any scheduled jobs need to run
				now = datetime.now()
				if (now - self.last_schedule_check).total_seconds() < 5:
						return False
						
				self.last_schedule_check = now
				
				# Check if any scheduled jobs are due
				return schedule.idle_seconds() == 0
		
		def _handle_stop_signal(self):
				"""Handle a stop signal detected by the background monitor"""
				logging.info("Background monitor detected scheduled job is due")
				self.stop_current_job()
				
				# Run pending scheduled jobs
				schedule.run_pending()
		
		def check_scheduled_jobs(self):
				"""Check if any scheduled jobs need to run and run them if needed"""
				# Only check every 5 seconds to avoid excessive checking
				now = datetime.now()
				if (now - self.last_schedule_check).total_seconds() < 5:
						return
						
				self.last_schedule_check = now
				
				# Run pending jobs if any are due
				if schedule.idle_seconds() == 0:
						logging.info("Scheduled job time reached, running pending jobs")
						schedule.run_pending()
		
		def register_browser(self, browser):
				"""Register a browser instance for cleanup if job is stopped"""
				if browser not in self.browser_instances:
						self.browser_instances.append(browser)

# Global job manager instance
job_manager = JobManager()

# Global stop event that can be checked by long-running processes
JOB_STOP_EVENT = Event()

class ScheduleManager:
		def __init__(self):
				self.running = True
				self.stop_event = Event()
				self._schedule_thread = None
				self._schedule_check_thread = None

		def start(self):
				"""Start the schedule manager and schedule checker thread"""
				# Start the main schedule thread
				self._schedule_thread = Thread(target=self._run_schedule, daemon=True)
				self._schedule_thread.start()
				
				# Start a separate thread to check for scheduled jobs during long-running operations
				self._schedule_check_thread = Thread(target=self._check_schedule_during_jobs, daemon=True)
				self._schedule_check_thread.start()

		def stop(self):
				"""Stop the schedule manager gracefully"""
				self.running = False
				self.stop_event.set()
				if self._schedule_thread:
						self._schedule_thread.join(timeout=5)
				if self._schedule_check_thread:
						self._schedule_check_thread.join(timeout=5)

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
		
		def _check_schedule_during_jobs(self):
				"""Periodically check if scheduled jobs need to run, even during long-running jobs"""
				while self.running and not self.stop_event.is_set():
						try:
								# Check if any scheduled jobs need to run
								if job_manager.is_job_running():
										job_manager.check_scheduled_jobs()
								
								# Sleep for a short time before checking again
								self.stop_event.wait(timeout=5)  # Check every 5 seconds
						except Exception as e:
								logging.error(f"Schedule check error: {str(e)}")
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
		schedule.every().day.at(morning_time).do(run_scheduled_job, "morning")
		schedule.every().day.at(evening_time).do(run_scheduled_job, "evening")
		
		# For testing/debugging: Add a job that runs every few minutes
		# This helps verify the scheduling system works without waiting for the actual times
		if CONFIG.get('debug.quick_schedule'):
				schedule.every(5).minutes.do(run_scheduled_job, "debug")
		
		logging.info(f"Scheduled jobs for {morning_time} and {evening_time}")
		
		# Check if we need to run a job immediately (if we're close to a scheduled time)
		check_if_job_due_now()

def check_if_job_due_now():
		"""Check if a job is due to run now or very soon"""
		now = datetime.now()
		
		# Get all jobs
		all_jobs = schedule.get_jobs()
		
		for job in all_jobs:
				# Get the next run time for this job
				next_run = job.next_run
				
				# If the job is due within the next 5 minutes, run it now
				if next_run and (next_run - now).total_seconds() < 300:  # 5 minutes = 300 seconds
						logging.info(f"Job scheduled for {next_run.strftime('%H:%M')} is due soon, running now")
						job.run()
						return True
		
		return False

def run_scheduled_job(job_type="scheduled"):
		"""Run a scheduled job, stopping any currently running job first"""
		logging.info(f"Starting {job_type} scheduled job")
		
		# Stop any currently running job
		if job_manager.is_job_running():
				logging.info(f"Stopping currently running job before starting {job_type} scheduled job")
				job_manager.stop_current_job()
		
		# Start the new job
		job_manager.run_job(run_job_with_activity, f"{job_type}_job")
		return schedule.CancelJob  # Don't repeat this specific job

def run_job_with_activity():
		"""Priority-based job execution with container persistence"""
		try:
				# Run the main job
				main()
		except Exception as e:
				logging.exception("Job execution error")
				sendNotification(
						"⚠️ Error occurred, please check the log",
						traceback.format_exc(),
						e
				)

def check_for_stop_signal():
		"""Function that can be called from long-running processes to check if they should stop"""
		# Check if the job manager wants to stop the current job
		if JOB_STOP_EVENT.is_set():
				return True
				
		# Also check if any scheduled jobs need to run
		job_manager.check_scheduled_jobs()
		
		# Re-check if stop event was set by the schedule check
		return JOB_STOP_EVENT.is_set()

def main_with_schedule():
		"""Main function with proper schedule handling"""
		try:
				# Initial setup
				setupLogging()
				logging.info("Starting application...")

				downloadWebDriver()
				
				# Set up schedule first so we can check if a job is due now
				setup_schedule()
				
				# Start the schedule manager
				schedule_manager = ScheduleManager()
				schedule_manager.start()
				
				# Run initial job only if no scheduled job is due now
				if not check_if_job_due_now():
						logging.info("No scheduled job due now, running initial job")
						job_manager.run_job(run_job_with_activity, "initial_job")
				
				# Wait for keyboard interrupt or other signals
				try:
						while True:
								time.sleep(1)
				except KeyboardInterrupt:
						logging.info("Received shutdown signal, cleaning up...")
				finally:
						# Stop any running job
						job_manager.stop_current_job()
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