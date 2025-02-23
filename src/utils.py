import contextlib
import json
import locale as pylocale
import logging
import re
import time
from argparse import Namespace, ArgumentParser
from datetime import date
from pathlib import Path
import random
from typing import Any, Self
from copy import deepcopy

import requests
import os
import yaml
from apprise import Apprise
from requests import Session
from requests.adapters import HTTPAdapter
from selenium.common import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
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


class Utils:

    def __init__(self, webdriver: WebDriver):
        self.webdriver = webdriver
        with contextlib.suppress(Exception):
            locale = pylocale.getdefaultlocale()[0]
            pylocale.setlocale(pylocale.LC_NUMERIC, locale)

        # self.config = self.loadConfig()

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
        assert (
            self.webdriver.current_url == REWARDS_URL
        ), f"{self.webdriver.current_url} {REWARDS_URL}"

    def goToSearch(self) -> None:
        self.webdriver.get(SEARCH_URL)
        # assert (
        #     self.webdriver.current_url == SEARCH_URL
        # ), f"{self.webdriver.current_url} {SEARCH_URL}"  # need regex: AssertionError: https://www.bing.com/?toWww=1&redig=A5B72363182B49DEBB7465AD7520FDAA https://bing.com/

    # Prefer getBingInfo if possible
    def getDashboardData(self) -> dict:
        urlBefore = self.webdriver.current_url
        try:
            self.goToRewards()
            return self.webdriver.execute_script("return dashboard")
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

    def tryDismissAllMessages(self) -> None:
        byValues = [
            (By.ID, "iLandingViewAction"),
            (By.ID, "iShowSkip"),
            (By.ID, "iNext"),
            (By.ID, "iLooksGood"),
            (By.ID, "idSIButton9"),
            (By.ID, "bnp_btn_accept"),
            (By.ID, "acceptButton"),
            (By.CSS_SELECTOR, ".dashboardPopUpPopUpSelectButton"),
        ]
        for byValue in byValues:
            dismissButtons = []
            with contextlib.suppress(NoSuchElementException):
                dismissButtons = self.webdriver.find_elements(
                    by=byValue[0], value=byValue[1]
                )
            for dismissButton in dismissButtons:
                dismissButton.click()
        with contextlib.suppress(NoSuchElementException):
            self.webdriver.find_element(By.ID, "cookie-banner").find_element(
                By.TAG_NAME, "button"
            ).click()

    def switchToNewTab(self, timeToWait: float = 15, closeTab: bool = False) -> None:
        time.sleep(timeToWait)
        self.webdriver.switch_to.window(window_name=self.webdriver.window_handles[1])
        if closeTab:
            self.closeCurrentTab()

    def closeCurrentTab(self) -> None:
        self.webdriver.close()
        time.sleep(0.5)
        self.webdriver.switch_to.window(window_name=self.webdriver.window_handles[0])
        time.sleep(0.5)

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
            logging.info(f"Updated {len(account_pairs)} accounts from environment")
        
        # Update Discord webhook from TOKEN env var
        token_env = os.getenv('TOKEN')
        if token_env:
            if not config.get('apprise'):
                config['apprise'] = {}
            if not config['apprise'].get('urls'):
                config['apprise']['urls'] = []
            
            # Clear existing urls and add new token
            config['apprise']['urls'] = [token_env]
            logging.info("Updated Discord webhook URL from environment")
        
        # Write updated config back to file
        with open(config_path, 'w') as file:
            yaml.safe_dump(config, file, default_flow_style=False)
            
    except Exception as e:
        logging.error(f"Failed to update config from environment: {str(e)}")
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


def sendNotification(title: str, body: str, e: Exception = None) -> None:
    if not CONFIG.apprise.enabled or (
        e and not CONFIG.get("apprise.notify.uncaught-exception")
    ):
        return
    apprise = Apprise()
    urls: list[str] = CONFIG.apprise.urls
    if not urls:
        logging.debug("No urls found, not sending notification")
        return
    for url in urls:
        apprise.add(url)
    assert apprise.notify(title=str(title), body=str(body))


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
