import dbm.dumb
import json
import logging
import shelve
from datetime import date, timedelta
from enum import Enum, auto
from itertools import cycle
from random import random, randint, shuffle, uniform, choice
from time import sleep
from typing import Final

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, NoSuchElementException

from src.browser import Browser
from src.utils import CONFIG, makeRequestsSession, getProjectRoot, active_sleep, take_screenshot


class RetriesStrategy(Enum):
    """
    method to use when retrying
    """

    EXPONENTIAL = auto()
    """
    an exponentially increasing `base_delay_in_seconds` between attempts
    """
    CONSTANT = auto()
    """
    the default; a constant `base_delay_in_seconds` between attempts
    """


class Searches:
    maxRetries: Final[int] = CONFIG.retries.max
    """
    the max amount of retries to attempt
    """
    baseDelay: Final[float] = CONFIG.get("retries.base_delay_in_seconds")
    """
    how many seconds to delay
    """
    # retriesStrategy = Final[  # todo Figure why doesn't work with equality below
    retriesStrategy = RetriesStrategy[CONFIG.retries.strategy]

    def __init__(self, browser: Browser):
        self.browser = browser
        self.webdriver = browser.webdriver

        dumbDbm = dbm.dumb.open((getProjectRoot() / "google_trends").__str__())
        self.googleTrendsShelf: shelve.Shelf = shelve.Shelf(dumbDbm)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.googleTrendsShelf.__exit__(None, None, None)

    def getGoogleTrends(self, words_count: int) -> list[str]:
        """
        Retrieves Google Trends search terms via the new API (last 48 hours).
        """
        logging.debug("Starting Google Trends fetch (last 48 hours)...")
        search_terms: list[str] = []
        session = makeRequestsSession()
        
        url = "https://trends.google.com/_/TrendsUi/data/batchexecute"
        payload = f'f.req=[[[i0OFE,"[null, null, \\"{self.browser.localeGeo}\\", 0, null, 48]"]]]'
        headers = {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}
        
        logging.debug(f"Sending POST request to {url}")
        try:
            response = session.post(url, headers=headers, data=payload)
            response.raise_for_status()
            logging.debug("Response received from Google Trends API")
        except requests.RequestException as e:
            logging.error(f"Error fetching Google Trends: {e}")
            return []

        trends_data = self.extract_json_from_response(response.text)
        if not trends_data:
            logging.error("Failed to extract JSON from Google Trends response")
            return []
    
        logging.debug("JSON successfully extracted. Processing root terms...")
    
        # Process only the first element in each item
        root_terms = []
        for item in trends_data:
            try:
                topic = item[0]
                root_terms.append(topic)
            except Exception as e:
                logging.warning(f"Error processing an item: {e}")
                continue
    
        logging.debug(f"Extracted {len(root_terms)} root trend entries")
    
        # Convert to lowercase and remove duplicates
        search_terms = list(set(term.lower() for term in root_terms))
        logging.debug(f"Found {len(search_terms)} unique search terms")
    
        if words_count < len(search_terms):
            logging.debug(f"Limiting search terms to {words_count} items")
            search_terms = search_terms[:words_count]
    
        logging.debug("Google Trends fetch complete")
        return search_terms

    def extract_json_from_response(self, text: str):
        """
        Extracts the nested JSON object from the API response.
        """
        logging.debug("Extracting JSON from API response")
        for line in text.splitlines():
            trimmed = line.strip()
            if trimmed.startswith('[') and trimmed.endswith(']'):
                try:
                    intermediate = json.loads(trimmed)
                    data = json.loads(intermediate[0][2])
                    logging.debug("JSON extraction successful")
                    return data[1]
                except Exception as e:
                    logging.warning(f"Error parsing JSON: {e}")
                    continue
        logging.error("No valid JSON found in response")
        return None

    def getRelatedTerms(self, term: str) -> list[str]:
        # Function to retrieve related terms from Bing API
        relatedTerms: list[str] = (
            makeRequestsSession()
            .get(
                f"https://api.bing.com/osjson.aspx?query={term}",
                headers={"User-agent": self.browser.userAgent},
            )
            .json()[1]
        )  # todo Wrap if failed, or assert response?
        if not relatedTerms:
            return [term]
        return relatedTerms

    def bingSearches(self) -> None:
      logging.info(
            f"[BING] Starting {self.browser.browserType.capitalize()} Edge Bing searches..."
        )
      self.browser.utils.goToSearch()
      try:
        numberOfSearches = self.browser.getRemainingSearches(desktopAndMobile=True)
        if numberOfSearches.getTotal() > len(self.googleTrendsShelf):
          # self.googleTrendsShelf.clear()  # Maybe needed?
          logging.debug(
              f"google_trends before load = {list(self.googleTrendsShelf.items())}"
          )
          trends = self.getGoogleTrends(numberOfSearches.getTotal())
          shuffle(trends)
          for trend in trends:
              self.googleTrendsShelf[trend] = None
          logging.debug(
              f"google_trends after load = {list(self.googleTrendsShelf.items())}"
          )
        initial_points, pointsCounter = self.browser.utils.getAccountPoints()
        successful_searches = 0

        i = 0
        attempt = 0
        for word in list(self.googleTrendsShelf.keys()):
          i += 1
          logging.info(f"[BING] Search {i}/{numberOfSearches}")
          try:
            current_points = self.bingSearch(word)
            # Check if points increased from the search
            if current_points > pointsCounter:
                successful_searches += 1
                pointsCounter = current_points
                attempt = 0  # Reset attempt counter on successful search
                logging.info(f"[BING] Successful search {successful_searches}/{numberOfSearches}")
                del self.googleTrendsShelf[list(self.googleTrendsShelf.keys())[0]]
            else:
                attempt += 1
                if attempt >= 2:
                    logging.warning("[BING] Possible blockage. Refreshing the page.")
                    self.webdriver.refresh()
                    sleep(5)  # Wait for refresh
                    attempt = 0
          except Exception as e:
              logging.warning(f"[BING] Error during search: {str(e)}")
              attempt += 1
              if attempt >= 2:
                  logging.warning("[BING] Too many errors. Refreshing the page.")
                  self.webdriver.refresh()
                  sleep(5)
                  attempt = 0
              continue

          
          # Log completion status
          points_earned = pointsCounter - initial_points
          logging.info(
              f"[BING] Completed {successful_searches}/{numberOfSearches} searches. "
              f"[BING] Points earned through {self.browser.browserType.capitalize()} Searches: {points_earned}"
          )
          
          # Return false if we didn't complete all searches
          if successful_searches < numberOfSearches:
              logging.warning(f"[BING] Only completed {successful_searches} out of {numberOfSearches} searches")
              return False
              
          return True

      except Exception as e:
          logging.error(f"[BING] Critical error during searches: {str(e)}", exc_info=True)
          return False


    def bingSearch(self, word: str):
        # Function to perform a single Bing search
        i = 0

        while True:
            try:
                # Ensure we're on Bing's homepage
                if "bing.com" not in self.webdriver.current_url:
                    self.webdriver.get("https://www.bing.com/")
                    sleep(2)

                # Wait for search bar and clear it
                self.browser.utils.waitUntilClickable(By.ID, "sb_form_q", 40)
                searchbar = self.webdriver.find_element(By.ID, "sb_form_q")
                searchbar.clear()
                
                # Add random typing delay to simulate human behavior
                for char in word:
                    searchbar.send_keys(char)
                    sleep(uniform(0.1, 0.3))  # Random delay between keystrokes
                
                # Random delay before submitting
                sleep(uniform(0.5, 1.5))
                searchbar.submit()
                
                # Wait for search results to load
                sleep(3)
                
                # Random delay between searches
                sleep(randint(CONFIG.cooldown.min, CONFIG.cooldown.max))

                self.random_scroll()

                # Random chance to click a result
                if random() < 0.5:  # 50% chance
                    self.click_random_result()

                return self.browser.utils.getAccountPoints()
            except TimeoutException:
                if i == 10:
                    logging.error(
                        "[BING] "
                        + "Cancelling mobile searches due to too many retries."
                    )
                    return self.browser.utils.getAccountPoints()
                self.browser.utils.tryDismissAllMessages()
                logging.error("[BING] " + "Timeout, retrying in 5~ seconds...")
                sleep(randint(7, 15))
                i += 1
                continue
            except Exception as e:
                logging.error(f"[BING] Error during search: {str(e)}")
                sleep(randint(5, 10))
                i += 1
                if i >= 10:
                    logging.error("[BING] Too many errors, returning current points")
                    return self.browser.utils.getAccountPoints()
                continue

    def random_scroll(self):
        """Scroll to a random position on the page"""
        try:
            # Get viewport and total height
            viewport_height = self.webdriver.execute_script("return window.innerHeight")
            total_height = self.webdriver.execute_script("return document.body.scrollHeight")
            
            # Calculate random scroll position
            random_scroll = randint(0, max(0, total_height - viewport_height))
            
            # Smooth scroll to position
            self.webdriver.execute_script(f"window.scrollTo({{top: {random_scroll}, behavior: 'smooth'}})")
            
            # Small delay to allow scroll animation
            sleep(uniform(1, 2))
            
        except Exception as e:
            logging.warning(f"Error during random scroll: {str(e)}")

    def click_random_result(self):
      """Click a random search result link with mobile/desktop handling"""
      try:
          logging.debug(f'[BING] Doing Random link clicking...')
          
          # Store original window handle
          original_window = self.webdriver.current_window_handle
          
          # Handle "Continue on Edge" popup
          self.close_continue_popup()
          
          # Different selectors for mobile and desktop
          selector = "#b_results .b_algoheader a h2" if self.browser.mobile else "#b_results .b_algo h2 a"
          
          # Find all search result links
          results = self.webdriver.find_elements(By.CSS_SELECTOR, selector)
          if not results:
              return
          
          # Select random result
          random_result = choice(results)
          
          try:
              # Scroll element into view
              self.webdriver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", random_result)
              sleep(1)  # Wait for scroll
              
              # Try regular click first
              random_result.click()
          except ElementClickInterceptedException:
              try:
                  # Try JavaScript click if regular click fails
                  self.webdriver.execute_script("arguments[0].click();", random_result)
              except Exception as e:
                  logging.warning(f"JavaScript click failed: {str(e)}")
                  return
          
          # Wait for page load
          sleep(2)
          
          if self.browser.mobile:
              # Mobile: Stay on same page, just scroll
              logging.debug(f"[BING] Mobile Link: {self.webdriver.title}")
              sleep(uniform(2, 3))
              self.random_scroll()
              
              # Return to search page using back button
              sleep(uniform(1, 2))
              logging.debug("[BING] Returning to search page")
              self.webdriver.back()
              
              # Wait for search results to be visible again
              try:
                  WebDriverWait(self.webdriver, 20).until(
                      EC.presence_of_element_located((By.CSS_SELECTOR, "#b_results"))
                  )
              except TimeoutException:
                  logging.warning("[BING] Timeout waiting for search results after back navigation")
                  # Refresh if results don't load
                  self.webdriver.refresh()
              
          else:
              # Desktop: Handle new window if opened
              new_window = None
              try:
                  WebDriverWait(self.webdriver, 3).until(lambda d: len(d.window_handles) > 1)
                  new_window = [h for h in self.webdriver.window_handles if h != original_window][0]
              except TimeoutException:
                  pass

              if new_window:
                  # Switch to new window
                  self.webdriver.switch_to.window(new_window)
                  
                  logging.debug(f"[BING] Desktop Link Tab: {self.webdriver.title}")

                  # Wait for page load and scroll
                  sleep(uniform(3, 5))
                  self.random_scroll()
                  
                  # Close tab and switch back
                  self.webdriver.close()
                  self.webdriver.switch_to.window(original_window)
              else:
                  # Just scroll on current page
                  sleep(uniform(2, 3))
                  self.random_scroll()
          
      except Exception as e:
          logging.warning(f"Error clicking random result: {str(e)}")
          # For mobile, ensure we return to search page on error
          if self.browser.mobile:
              try:
                  self.webdriver.back()
                  # Wait for search results after error recovery
                  WebDriverWait(self.webdriver, 10).until(
                      EC.presence_of_element_located((By.CSS_SELECTOR, "#b_results"))
                  )
              except:
                  logging.error("[BING] Failed to return to search page after error")
          # For desktop, ensure we're back on the original window
          else:
              if original_window in self.webdriver.window_handles:
                  self.webdriver.switch_to.window(original_window)


    def close_continue_popup(self):
        """Close the 'Continue on Edge' popup if present"""
        try:
            popup = WebDriverWait(self.webdriver, 2).until(
                EC.presence_of_element_located((By.ID, "sacs_close"))
            )
            popup.click()
        except TimeoutException:
            pass
