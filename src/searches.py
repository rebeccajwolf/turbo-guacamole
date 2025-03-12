import atexit
import contextlib
import dbm.dumb
import json
import logging
import random
import re
import shelve
import time
import sys
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from enum import Enum, auto
from itertools import cycle
from typing import Final, List
from pathlib import Path
from typing import Dict, Optional

import requests
from selenium.common import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait

from src.browser import Browser
from src.utils import CONFIG, makeRequestsSession, getProjectRoot


class RetriesStrategy(Enum):
    """
    Method to use when retrying.
    """
    EXPONENTIAL = auto()  # Exponentially increasing delay between attempts.
    CONSTANT = auto()     # Constant delay between attempts.


class Searches:
    maxRetries: Final[int] = CONFIG.retries.max
    baseDelay: Final[float] = CONFIG.get("retries.base_delay_in_seconds")
    retriesStrategy = RetriesStrategy[CONFIG.retries.strategy]

    def __init__(self, browser: Browser):
        self.browser = browser
        self.webdriver = browser.webdriver

        # Open the googleTrendsShelf
        dumbDbm = dbm.dumb.open((getProjectRoot() / "google_trends").__str__())
        self.googleTrendsShelf: shelve.Shelf = shelve.Shelf(dumbDbm)

        # Blacklist as an in-memory dictionary
        self.blacklist: Dict[str, Dict[str, float]] = self._load_blacklist()
        self.blacklist_changed = False  # Flag to track changes
        self.blacklist_change_count = 0  # Counter for changes
        self.blacklist_save_threshold = 3 # Threshold for saving changes

        # Cooldown list for rootTerms
        self.cooldown_list: Dict[str, float] = self._load_cooldown_list()
        self.cooldown_list_changed = False  # Flag to track changes
        self.cooldown_list_change_count = 0  # Counter for changes
        self.cooldown_list_save_threshold = 3  # Threshold for saving changes

        # Track successful searches and cooldown
        self.successful_search_counter = 0  # Counter for successful searches
        self.last_successful_search_time = None  # Time of the last successful search
        self.allow_cooldown = True # Switch variable that controls whether a cooldown may be triggered  
        
        self.cooldown_base_minutes = 30 # Cooldown base value for searches in minutes  
        
        # Load the persistent search counter
        self.search_counter_file = getProjectRoot() / "search_counter.json"
        self.successful_search_counter = self._load_search_counter()

        # Autosave when exiting or crashing the bot
        atexit.register(lambda: self._save_blacklist())
        atexit.register(lambda: self._save_cooldown_list())
        atexit.register(lambda: self._save_search_counter())
        
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.googleTrendsShelf.__exit__(None, None, None)
        """
        Saves the blacklist when exiting the class.
        """
        self._save_blacklist_if_changed()

    def _load_blacklist(self) -> Dict[str, Dict[str, float]]:
        """
        Loads the blacklist from a JSON file.
        """
        blacklist_file = getProjectRoot() / "blacklist.json"
        if blacklist_file.exists():
            with open(blacklist_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_cooldown_list(self) -> Dict[str, float]:
        """
        Loads the cooldown list from a JSON file.
        """
        cooldown_file = getProjectRoot() / "cooldown_list.json"
        if cooldown_file.exists():
            with open(cooldown_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_search_counter(self) -> int:
        """
        Loads the search counter from a JSON file.
        """
        if self.search_counter_file.exists():
            with open(self.search_counter_file, "r", encoding="utf-8") as f:
                return json.load(f).get("successful_search_counter", 0)
        return 0

    def _save_blacklist(self) -> None:
        """
        Saves the blacklist to a JSON file.
        """
        blacklist_file = getProjectRoot() / "blacklist.json"
        with open(blacklist_file, "w", encoding="utf-8") as f:
            json.dump(self.blacklist, f, ensure_ascii=False, indent=4)

    def _save_cooldown_list(self) -> None:
        """
        Saves the cooldown list to a JSON file.
        """
        cooldown_file = getProjectRoot() / "cooldown_list.json"
        with open(cooldown_file, "w", encoding="utf-8") as f:
            json.dump(self.cooldown_list, f, ensure_ascii=False, indent=4)

    def _save_blacklist_if_changed(self) -> None:
        """
        Saves the blacklist only if it has changed.
        """
        if self.blacklist_changed:
            self._save_blacklist()
            self.blacklist_changed = False

    def _save_cooldown_list_if_changed(self) -> None:
        """
        Saves the cooldown list only if it has changed.
        """
        if self.cooldown_list_changed:
            self._save_cooldown_list()
            self.cooldown_list_changed = False

    def _save_search_counter(self) -> None:
        """
        Saves the search counter to a JSON file.
        """
        with open(self.search_counter_file, "w", encoding="utf-8") as f:
            json.dump({"successful_search_counter": self.successful_search_counter}, f, ensure_ascii=False, indent=4)

    def addToBlacklist(self, rootTerm: str, term: str, cooldownHours: int = 30) -> None:
        """
        Adds a term to the blacklist for a specific rootTerm. Edit int above to adjust the cooldown of terms.
        """
        if rootTerm not in self.blacklist:
            self.blacklist[rootTerm] = {}

        cooldownUntil = time.time() + cooldownHours * 3600
        self.blacklist[rootTerm][term] = cooldownUntil
        self.blacklist_changed = True
        self.blacklist_change_count += 1

        if self.blacklist_change_count >= self.blacklist_save_threshold:
            self._save_blacklist_if_changed()
            self.blacklist_change_count = 0

    def add_to_cooldown_list(self, rootTerm: str, cooldownHours: int = 24) -> None:
        """
        Adds a rootTerm to the cooldown list.
        """
        cooldownUntil = time.time() + cooldownHours * 3600
        self.cooldown_list[rootTerm] = cooldownUntil
        self.cooldown_list_changed = True
        self.cooldown_list_change_count += 1

        if self.cooldown_list_change_count >= self.cooldown_list_save_threshold:
            self._save_cooldown_list_if_changed()
            self.cooldown_list_change_count = 0

    def cleanupBlacklist(self) -> None:
        """
        Cleans up the blacklist by removing terms whose cooldown has expired.
        """
        current_time = time.time()
        rootTerms_to_remove = []

        for rootTerm, terms in self.blacklist.items():
            terms_to_remove = [term for term, cooldownUntil in terms.items() if current_time >= cooldownUntil]

            for term in terms_to_remove:
                del terms[term]

            if not terms:
                rootTerms_to_remove.append(rootTerm)

        for rootTerm in rootTerms_to_remove:
            del self.blacklist[rootTerm]

        if rootTerms_to_remove:
            self.blacklist_changed = True
            self._save_blacklist_if_changed()
            logging.info(f"[BING] Cleaned up blacklist. Removed {len(rootTerms_to_remove)} expired terms.")
        else:
            logging.info("[BING] Blacklist up-to-date. No action needed.")

    def cleanup_cooldown_list(self) -> None:
        """
        Cleans up the cooldown list by removing all rootTerms whose cooldown phase has expired.
        """
        current_time = time.time()
        terms_to_remove = [
            term for term, cooldown_until in self.cooldown_list.items()
            if current_time >= cooldown_until
        ]

        for term in terms_to_remove:
            del self.cooldown_list[term]

        if terms_to_remove:
            self.cooldown_list_changed = True
            self._save_cooldown_list_if_changed()
            logging.info(f"[BING] Cleaned up cooldown list. Removed {len(terms_to_remove)} expired terms.")
        else:
            logging.info("[BING] Cooldown list up-to-date. No action needed.")

    def cleanupRootTerms(self) -> None:
        """
        Cleans up the rootTerms list after both desktop and mobile searches are completed.
        """
        # Clear the prioritizedRootTerms list
        self.prioritizedRootTerms = []
        logging.info("[BING] Cleaned up rootTerms list after completing all searches.")

        # Optionally, clear the googleTrendsShelf if needed
        self.googleTrendsShelf.clear()
        logging.info("[BING] Cleared googleTrendsShelf as well.")

    def exportRootTermsToFile(self, rootTerms: list[str], filename: str = "root_terms.txt") -> None:
        """
        Exports the list of rootTerms to a text file for analysis.
        """
        with open(filename, "w", encoding="utf-8") as file:
            for term in rootTerms:
                file.write(f"{term}\n")
        #logging.info(f"[BING] Exported {len(rootTerms)} rootTerms to {filename}")

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

    def getPrioritizedRootTerms(self, similarity_threshold: float = 0.7) -> list[str]:
        """
        Generates a prioritized list of diverse rootTerms with daily variation.
        Ensures minimum 50 terms and avoids recently used terms.
        """
        # Load all potential terms and filter cooldown
        all_terms = list(self.googleTrendsShelf.keys())
        all_terms = [term for term in all_terms if self.is_latin_characters_only(term)] # Filter out terms with non-Latin characters
        active_terms = [t for t in all_terms if t not in self.cooldown_list]

        # Cluster terms by similarity
        clusters = []
        used_terms = set()

        # 1. Create similarity clusters
        for term in active_terms:
            if term in used_terms:
                continue

            # Find similar terms
            cluster = [term]
            used_terms.add(term)
            for other in active_terms:
                if other not in used_terms and self.similarity(term, other) > similarity_threshold:
                    cluster.append(other)
                    used_terms.add(other)

            clusters.append(cluster)

        # 2. Daily variation: Shuffle clusters and select terms
        prioritized = []
        random.seed(date.today().toordinal())  # Daily unique seed

        # Strategy: Select 1 term per cluster, prioritizing large clusters first
        clusters.sort(key=len, reverse=True)
        for cluster in clusters:
            if not prioritized:
                prioritized.append(random.choice(cluster))
            else:
                # Find term with lowest similarity to last added
                best_term = min(
                    cluster,
                    key=lambda x: max(self.similarity(x, p) for p in prioritized[-3:])
                )
                prioritized.append(best_term)

        # 3. Fill remaining slots
        needed = max(50 - len(prioritized), 0)
        
        # 4. Final shuffle to avoid pattern repetition
        #random.shuffle(final_terms[:50])  # Only shuffle first 50
        
        # Add from cooldown (oldest first)
        cooldown_terms = sorted(
            [t for t in all_terms if t in self.cooldown_list],
            key=lambda x: self.cooldown_list[x]
        )

        # Combine lists
        final_terms = prioritized + cooldown_terms[:needed]

        return final_terms #[:50]  # Ensure exactly 50 terms

    def getRelatedTerms(self, term: str) -> list[str]:
        """
        Fetches related terms from the Bing API.
        """
        relatedTerms: list[str] = (
            makeRequestsSession()
            .get(
                f"https://api.bing.com/osjson.aspx?query={term}",
                headers={"User-agent": self.browser.userAgent},
            )
            .json()[1]
        )
        if not relatedTerms:
            return [term]
        return relatedTerms

    def isBlacklisted(self, rootTerm: str, term: str) -> bool:
        """
        Checks if a term is blacklisted for a specific rootTerm.
        """
        if rootTerm in self.blacklist and term in self.blacklist[rootTerm]:
            cooldownUntil = self.blacklist[rootTerm][term]
            if time.time() < cooldownUntil:
                return True
            else:
                # Cooldown expired - remove term from the blacklist
                del self.blacklist[rootTerm][term]
                if not self.blacklist[rootTerm]:    # If no more terms for rootTerm, remove rootTerm
                    del self.blacklist[rootTerm]
                logging.debug(f"[BING] {term} (rootTerm: {rootTerm}) removed from blacklist.")

                self.blacklist_changed = True
                self._save_blacklist_if_changed()
        return False

    def is_latin_characters_only(self, term: str) -> bool:
        """
        Checks if the term contains only characters from the Latin alphabet.
        Allows numbers, hyphens, spaces, a wide range of special characters, and common keyboard symbols.
        """
        # Regex that allows only Latin letters, numbers, hyphens, spaces, a wide range of special characters, and common keyboard symbols
        latin_pattern = re.compile(r'^[a-zA-Z0-9\- .äöüßÄÖÜàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞŸ€șțğı§$%&@#<>_*+~|{}:;?/\\^`\[\]]+$')
        return bool(latin_pattern.match(term))

    def normalize_term(self, term: str) -> str:
        """
        Normalizes a term by removing special characters, normalizing spaces, and converting to lowercase.
        """
        # Remove special characters and normalize spaces
        term = re.sub(r'[^\w\s]', '', term)  # Remove all non-alphanumeric characters except spaces
        term = re.sub(r'\s+', ' ', term)     # Normalize multiple spaces to a single space
        return term.strip().lower()           # Convert to lowercase and strip leading/trailing spaces

    def similarity(self, term1: str, term2: str) -> float:
        """
        Calculates the similarity between two terms based on token overlap (Jaccard similarity).
        Works for terms with any number of words.
        """
        # Normalize terms: Remove special characters, convert to lowercase, and split into tokens
        tokens1 = set(self.normalize_term(term1).split())
        tokens2 = set(self.normalize_term(term2).split())

        # If either term has no tokens, similarity is 0
        if not tokens1 or not tokens2:
            return 0.0

        # Calculate Jaccard similarity: intersection / union
        intersection = tokens1.intersection(tokens2)
        union = tokens1.union(tokens2)
        return len(intersection) / len(union)
   
    def bingSearches(self) -> None:
        """
        Performs Bing searches to earn rewards points.
        """
        logging.info(
            f"[BING] Starting {self.browser.browserType.capitalize()} Edge Bing searches..."
        )
    
        self.browser.utils.goToSearch()
    
        # Clean up the blacklist before starting searches
        self.cleanupBlacklist()
    
        # Clean up the cooldown list before starting searches
        self.cleanup_cooldown_list()
    
        # Initialize the prioritized rootTerms list
        self.prioritizedRootTerms = self.getPrioritizedRootTerms()
    
        # Export the root terms to a file for debugging
        #self.exportRootTermsToFile(self.prioritizedRootTerms, "root_terms_before_search_1.txt")
    
        # Reset the successful search counter at the start of searches
        self.successful_search_counter = 0
        self._save_search_counter()
    
        while (remainingSearches := self.browser.getRemainingSearches()) > 0:
            logging.info(f"[BING] Remaining searches={remainingSearches}")
            desktopAndMobileRemaining = self.browser.getRemainingSearches(desktopAndMobile=True)
    
            # Get X search terms more than needed; ensures 50+ rootTerms...
            required_terms = desktopAndMobileRemaining.getTotal() + 15
    
            if desktopAndMobileRemaining.getTotal() > len(self.googleTrendsShelf):
                logging.debug(
                    f"google_trends before load = {list(self.googleTrendsShelf.items())}"
                )
                trends = self.getGoogleTrends(required_terms)  # Get x more here, if set above
                if not trends:
                    logging.error("[BING] Failed to fetch Google Trends.")
                    continue
                random.shuffle(trends)
                for trend in trends:
                    self.googleTrendsShelf[trend] = None
                logging.debug(
                    f"google_trends after load = {list(self.googleTrendsShelf.items())}"
                )
                # Update the prioritized rootTerms list with new trends
                self.prioritizedRootTerms = self.getPrioritizedRootTerms()
    
            # Export the root terms to a file for debugging
            #self.exportRootTermsToFile(self.prioritizedRootTerms, "root_terms_before_search_2.txt")
    
            # Perform the search
            search_successful = self.bingSearch()
    
            # Random delay between searches (unchanged)
            time.sleep(random.randint(15, 25))  # Increase delay between searches
    
        # Clean up the rootTerms only if both desktop and mobile searches are completed
        desktopAndMobileRemaining = self.browser.getRemainingSearches(desktopAndMobile=True)
        if desktopAndMobileRemaining.desktop == 0 and desktopAndMobileRemaining.mobile == 0:
            self.cleanupRootTerms()
            self.cleanup_cooldown_list()
            logging.info("[BING] Both desktop and mobile searches completed. Cleaned up rootTerms list.")
        else:
            logging.info("[BING] Only one search type completed. Skipping cleanup.")
    
        logging.info(
            f"[BING] Finished {self.browser.browserType.capitalize()} Edge Bing searches!"
        )
    
    def bingSearch(self) -> bool:
        """
        Performs a single Bing search.
        Returns True if the search was successful, False otherwise.
        """
        pointsBefore = self.browser.utils.getAccountPoints()
    
        # Use the instance attribute prioritizedRootTerms
        prioritizedRootTerms = self.prioritizedRootTerms
    
        # Export the root terms to a file for debugging
        #self.exportRootTermsToFile(self.prioritizedRootTerms, "root_terms_before_every_search.txt")
    
        # Find the first rootTerm that is not fully blacklisted
        rootTerm = None
        available_terms = {}
        for term in prioritizedRootTerms:
            related_terms = self.getRelatedTerms(term)
            if not related_terms:
                logging.warning(f"[BING] No related terms found for {term}.")
                continue
            available_terms[term] = [
                t for t in related_terms if not self.isBlacklisted(term, t)
            ]
            if available_terms[term]:
                rootTerm = term
                break
    
        # If all rootTerms are blacklisted, fetch new search terms and try again
        if not rootTerm:
            logging.warning("[BING] All rootTerms are fully blacklisted. Fetching new search terms...")
            
            # Fetch new search terms from Google Trends
            trends = self.getGoogleTrends(10)  # Fetch 10 new search terms
            if not trends:
                logging.error("[BING] Failed to fetch new Google Trends.")
                return False
            
            # Add the new trends to the googleTrendsShelf
            for trend in trends:
                self.googleTrendsShelf[trend] = None
            
            # Log the updated googleTrendsShelf for debugging
            logging.debug(f"google_trends after reload = {list(self.googleTrendsShelf.items())}")
            
            # Update the prioritized rootTerms list with new trends
            self.prioritizedRootTerms = self.getPrioritizedRootTerms()
            
            # Log the updated prioritizedRootTerms for debugging
            logging.debug(f"Updated prioritizedRootTerms: {self.prioritizedRootTerms}")
            
            # Process new trends immediately by calling bingSearch again
            return self.bingSearch()  # Call bingSearch again
    
        # Check if all terms for the rootTerm are blacklisted
        valid_terms = available_terms[rootTerm]
        logging.debug(f"Valid terms for {rootTerm}: {valid_terms}")
    
        if not valid_terms:
            logging.error(f"[BING] All terms for rootTerm {rootTerm} are blacklisted. Removing it from the list.")
            self.prioritizedRootTerms = [term for term in self.prioritizedRootTerms if term != rootTerm]
            logging.info(f"[BING] Removed rootTerm {rootTerm} from prioritizedRootTerms as all terms are blacklisted.")
            return False
    
        termsCycle: cycle[str] = cycle(valid_terms)  # Use only non-blacklisted terms
        baseDelay = Searches.baseDelay
        logging.debug(f"rootTerm={rootTerm}")
    
        # Dynamically adjust the maximum retries based on the number of terms
        dynamicMaxRetries = min(Searches.maxRetries, len(valid_terms))
        logging.debug(f"[BING] Dynamic max retries for rootTerm={rootTerm}: {dynamicMaxRetries}")
    
        search_start_time = time.time()  # Track the start time of the search
        cumulative_search_time = 0  # Track cumulative search time
    
        for i in range(dynamicMaxRetries + 1):
            if i != 0:
                sleepTime: float
                if Searches.retriesStrategy == Searches.retriesStrategy.EXPONENTIAL:
                    sleepTime = baseDelay * 2 ** (i - 1)
                elif Searches.retriesStrategy == Searches.retriesStrategy.CONSTANT:
                    sleepTime = baseDelay
                else:
                    raise AssertionError
    
                # Add random variation to the sleep time (±10 seconds)
                sleepTime += random.uniform(-10, 10)
                sleepTime = max(sleepTime, 8)  # Ensure sleep time is at least 8 seconds
    
                # Update cumulative search time
                cumulative_search_time += sleepTime
    
                # Calculate the time for the next search attempt
                current_time = datetime.now()
                next_attempt_time = current_time + timedelta(seconds=sleepTime)
                next_attempt_time_str = next_attempt_time.strftime("%H:%M:%S")
    
                # Convert seconds to minutes and seconds
                sleepTime_minutes = int(sleepTime // 60)  # Whole minutes
                sleepTime_seconds = int(sleepTime % 60)   # Remaining seconds
    
                # Format the minutes and seconds
                if sleepTime_minutes > 0 and sleepTime_seconds > 0:
                    sleepTime_str = f"{sleepTime_minutes} min{'s' if sleepTime_minutes > 1 else ''} and {sleepTime_seconds} sec{'s' if sleepTime_seconds > 1 else ''}"
                elif sleepTime_minutes > 0:
                    sleepTime_str = f"{sleepTime_minutes} min{'s' if sleepTime_minutes > 1 else ''}"
                else:
                    sleepTime_str = f"{sleepTime_seconds} sec{'s' if sleepTime_seconds > 1 else ''}"
    
                # Output with seconds, minutes, and the time of the next attempt
                logging.debug(
                    f"[BING] Search attempt not counted {i}/{dynamicMaxRetries}, sleeping {sleepTime:.1f} secs "
                    f"({sleepTime_str}) until {next_attempt_time_str}..."
                )
    
                # Countdown until the next search attempt
                remaining_time = sleepTime
                while remaining_time > 0:
                    mins, secs = divmod(int(remaining_time), 60)
                    time_format = f"{mins:02d}:{secs:02d}"
                    print(f"Next search in: {time_format}", end="\r")  # \r to overwrite the previous line
                    time.sleep(1)
                    remaining_time -= 1
    
                print(" " * 20, end="\r")  # Clear the countdown line
    
            # Find the next term that is not blacklisted
            term = next(termsCycle)
            logging.debug(f"term={term}")
    
            # Check if the term is blacklisted before using it
            if self.isBlacklisted(rootTerm, term):
                logging.debug(f"[BING] Term {term} is blacklisted. Skipping...")
                continue
    
            # Try to find the search bar
            searchbar: WebElement
            for attempt in range(3):  # Max 3 attempts to find the search bar
                try:
                    searchbar = self.browser.utils.waitUntilClickable(
                        By.ID, "sb_form_q", timeToWait=20  # Increase wait time to 20+ seconds
                    )
                    searchbar.clear()
                    time.sleep(1)
                    searchbar.send_keys(term)
                    time.sleep(1)
                    with contextlib.suppress(TimeoutException):
                        WebDriverWait(self.webdriver, 20).until(
                            expected_conditions.text_to_be_present_in_element_value(
                                (By.ID, "sb_form_q"), term
                            )
                        )
                        break
                except TimeoutException:
                    logging.warning(f"Attempt {attempt + 1}: Search bar not found. Stopping page load and retrying...")
                    self.webdriver.execute_script("window.stop()")  # Stop page loading
                    self.browser.utils.goToSearch()  # Go back to the search page
                    continue
            else:
                logging.error("Failed to find the search bar after multiple attempts.")
                raise TimeoutException("Failed to find the search bar after multiple attempts.")
    
            try:
                searchbar.submit()
            except TimeoutException:
                logging.warning("Timeout occurred while submitting the search. Stopping page load and retrying...")
                self.webdriver.execute_script("window.stop()")  # Stop page loading
                self.browser.utils.goToSearch()  # Go back to the search page
                continue
    
            pointsAfter = self.browser.utils.getAccountPoints()
            if pointsAfter is None:
                logging.error("[BING] Failed to get account points after search.")
                continue
            if pointsBefore < pointsAfter:
                logging.info(f"Search attempt successful for term '{term}'!")
                # Remove the used term from the available terms
                if term in available_terms[rootTerm]:
                    available_terms[rootTerm].remove(term)
    
                # Check if there are still unused terms for this rootTerm
                if available_terms[rootTerm]:
                    # Move the rootTerm to the end of the prioritizedRootTerms list
                    self.prioritizedRootTerms = [term for term in self.prioritizedRootTerms if term != rootTerm] + [rootTerm]
                    termsCycle = cycle(available_terms[rootTerm])
                else:
                    # Remove the rootTerm from the prioritizedRootTerms list if no terms are left
                    logging.info(f"[BING] RootTerm {rootTerm} has no usable terms left. Removing it from the list.")
                    self.prioritizedRootTerms = [term for term in self.prioritizedRootTerms if term != rootTerm]
    
                # Add the rootTerm to the cooldown list after successful search
                self.add_to_cooldown_list(rootTerm)
    
                # Increment the successful search counter
                self.successful_search_counter += 1
                self._save_search_counter()
                
                # Set the allow_cooldown flag to True
                self.allow_cooldown = True
    
                # Check if 4 successful searches were completed within 2.5 minutes and are consecutive
                current_time = time.time()
                if self.last_successful_search_time is not None and (current_time - self.last_successful_search_time) <= 150:
                    if self.successful_search_counter >= 4:
                        # Check remaining searches for BOTH desktop AND mobile
                        remaining_searches = self.browser.getRemainingSearches(desktopAndMobile=True)
                        remaining_desktop = remaining_searches.desktop
                        remaining_mobile = remaining_searches.mobile
                        
                        # Trigger cooldown only if:
                        # 1. There are still searches remaining for at least one type (Desktop or Mobile).
                        # 2. The 4th successful search is NOT the last search for either Desktop or Mobile.
                        if (remaining_desktop > 0 or remaining_mobile > 0) and not (
                            (remaining_desktop == 1 and remaining_mobile == 0) or  # Last Desktop search
                            (remaining_mobile == 1 and remaining_desktop == 0)     # Last Mobile search
                        ):
                            # Check if cooldown is allowed
                            if self.allow_cooldown:
                                cooldown_time = self.cooldown_base_minutes * 60 + random.randint(1, 59)
                                logging.info(f"[BING] 4 successful searches within 2.5 minutes. Entering cooldown for {cooldown_time} seconds...")
                                
                                # Display countdown in the terminal
                                remaining_time = cooldown_time
                                while remaining_time > 0:
                                    mins, secs = divmod(int(remaining_time), 60)
                                    time_format = f"{mins:02d}:{secs:02d}"
                                    print(f"Cooldown: {time_format} remaining", end="\r")  # \r to overwrite the previous line
                                    time.sleep(1)
                                    remaining_time -= 1
            
                                print(" " * 30, end="\r")  # Clear the countdown line
                                logging.info("[BING] Cooldown finished. Resuming searches...")
                                
                                # Set the allow_cooldown flag to False
                                self.allow_cooldown = False
    
                        # Reset the successful search counter
                        self.successful_search_counter = 0
                        self._save_search_counter()
                        self.last_successful_search_time = None
                else:
                    # Reset the counter if the time between successful searches is too long
                    self.successful_search_counter = 1
                    self._save_search_counter()
    
                # Update the time of the last successful search
                self.last_successful_search_time = current_time
    
                return True  # Search was successful
            else:
                # Add the failed term to the blacklist
                self.addToBlacklist(rootTerm, term)
                if term in available_terms[rootTerm]:
                    available_terms[rootTerm].remove(term)
                if available_terms[rootTerm]:
                    termsCycle = cycle(available_terms[rootTerm])
                else:
                    logging.info(f"[BING] No usable terms left for rootTerm {rootTerm}. Removing it from the list.")
                    self.prioritizedRootTerms = [term for term in self.prioritizedRootTerms if term != rootTerm]
                    self.add_to_cooldown_list(rootTerm)
    
                # Check if cumulative search time exceeds 3 minutes and allow_cooldown is True
                if cumulative_search_time > 180 and self.allow_cooldown:
                    # Start cooldown if cumulative search time exceeds 3 minutes
                    cooldown_time = self.cooldown_base_minutes * 60 + random.randint(1, 59) - cumulative_search_time
                    logging.info(f"[BING] Cumulative search time exceeded 3 minutes ({int(cumulative_search_time)}s). Calculated remaining cooldown: {int(cooldown_time)} seconds...")
    
                    # Display countdown in the terminal
                    remaining_time = cooldown_time
                    while remaining_time > 0:
                        mins, secs = divmod(int(remaining_time), 60)
                        time_format = f"{mins:02d}:{secs:02d}"
                        print(f"Cooldown: {time_format} remaining", end="\r")  # \r to overwrite the previous line
                        time.sleep(1)
                        remaining_time -= 1
    
                    print(" " * 30, end="\r")  # Clear the countdown line
                    logging.info("[BING] Cooldown finished. Resuming searches...")
    
                    # Reset the successful search counter
                    self.successful_search_counter = 0
                    self._save_search_counter()
                    self.last_successful_search_time = None
                    
                    # Set the allow_cooldown flag to False
                    self.allow_cooldown = False
                    
                    # Move the rootTerm to the end of the prioritizedRootTerms list
                    if rootTerm in self.prioritizedRootTerms:
                        self.prioritizedRootTerms = [term for term in self.prioritizedRootTerms if term != rootTerm] + [rootTerm]                   
                    
                    self.add_to_cooldown_list(rootTerm)
                    return False  # Exit after cooldown
    
        # If all attempts fail, check if the rootTerm has any usable terms left
        if not available_terms[rootTerm]:
            logging.info(f"[BING] RootTerm {rootTerm} has no usable terms left. Removing it from the list.")
            self.prioritizedRootTerms = [term for term in self.prioritizedRootTerms if term != rootTerm]
            # Add the rootTerm to the cooldown list after a failed search
            self.add_to_cooldown_list(rootTerm)
        else:
            logging.warning(f"[BING] All attempts for rootTerm {rootTerm} failed. Moving it to the end of the list.")
            self.prioritizedRootTerms = [term for term in self.prioritizedRootTerms if term != rootTerm] + [rootTerm]
            # Add the rootTerm to the cooldown list after a failed search
            self.add_to_cooldown_list(rootTerm)
    
        logging.error("[BING] Reached max search attempt retries.")
        logging.warning(f"[BING] Current blacklist for {rootTerm}: {self.blacklist.get(rootTerm, {})}")
        return False  # Search was not successful