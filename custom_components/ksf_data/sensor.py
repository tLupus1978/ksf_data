"""KSF Data fetcher (Substitute plan of Kopernikusschule Freigericht).

Original Author:  Thomas Wolf

Description:
    Configuration Instructions are on GitHub.
"""

from datetime import datetime, timedelta
from html.parser import HTMLParser
import logging
from typing import List, Optional, Tuple, Dict, Any  # noqa: UP035
import threading
from urllib.parse import urlparse

from attrs import define, field, validators
from pyquery import PyQuery as pq
import requests
from requests.adapters import HTTPAdapter, Retry

from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle
from homeassistant.helpers.event import track_time_interval
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)

from .const import DOMAIN

import jsonpickle

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=45)
CACHE_DURATION = timedelta(minutes=15)
MAX_RETRIES = 3
BACKOFF_FACTOR = 1
TIMEOUT = (5, 15)  # (connect timeout, read timeout)

DEFAULT_LOGIN_URL = "https://login.schulportal.hessen.de/?url=aHR0cHM6Ly9jb25uZWN0LnNjaHVscG9ydGFsLmhlc3Nlbi5kZS8=&skin=sp&i=6013"
DEFAULT_LANDINGPAGE_URL = "https://connect.schulportal.hessen.de/"
DEFAULT_SUBSTITUTE_URL = "https://start.schulportal.hessen.de/vertretungsplan.php"

# Define the update interval (every 1 hour)
SCAN_INTERVAL = timedelta(hours=1)


class SessionManager:
    """Manages the session and authentication state."""

    def __init__(self):
        self._session = None
        self._cookies = None
        self._last_auth = None
        self._lock = threading.Lock()

    def get_session(self) -> requests.Session:
        """Get a configured session with retry logic."""
        if not self._session:
            self._session = requests.Session()
            retry_strategy = Retry(
                total=MAX_RETRIES,
                backoff_factor=BACKOFF_FACTOR,
                status_forcelist=[500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
        return self._session

    def clear_session(self):
        """Clear the current session."""
        if self._session:
            self._session.close()
        self._session = None
        self._cookies = None
        self._last_auth = None


class RequestError(Exception):
    """Custom exception for request errors."""

    pass


class ParsingError(Exception):
    """Custom exception for parsing errors."""

    pass


def validate_url(instance, attribute, value):
    """Validate URL format."""
    try:
        result = urlparse(value)
        if not all([result.scheme, result.netloc]):
            raise ValueError("Invalid URL format")
    except Exception as e:
        raise ValueError(f"Invalid URL: {str(e)}")


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the KSF sensor platform."""
    username = config.get("username")
    password = config.get("password")
    name = config.get("name")

    if not all([username, password, name]):
        _LOGGER.error("Missing required configuration: username, password, or name")
        return False

    try:
        add_entities(
            [ksfSensor(name, username, password)],
            update_before_add=True,
        )
        return True
    except Exception as e:
        _LOGGER.error(f"Failed to set up KSF sensor: {str(e)}")
        return False


@define
class SubstitutionDay:
    """The substitution plan page in a data type."""

    @define
    class Substitution:
        """The individual substitution data (table row)."""

        substitute: str = field(factory=str, validator=validators.instance_of(str))
        teacher: str = field(factory=str, validator=validators.instance_of(str))
        hours: str = field(factory=str, validator=validators.instance_of(str))
        class_name: str = field(factory=str, validator=validators.instance_of(str))
        subject: str = field(factory=str, validator=validators.instance_of(str))
        subject_old: str = field(factory=str, validator=validators.instance_of(str))
        room: str = field(factory=str, validator=validators.instance_of(str))
        room_old: str = field(factory=str, validator=validators.instance_of(str))
        notice: str = field(factory=str, validator=validators.instance_of(str))

    #        def __attrs_post_init__(self):
    #            """Clean and validate data after initialization."""
    #            for field_name, field_value in self.__dict__.items():
    #                if isinstance(field_value, str):
    #                    # Clean the string
    #                    cleaned = field_value.strip().replace("\x00", "")
    #                    setattr(self, field_name, cleaned)

    date: str = field(validator=validators.instance_of(str))
    substitutions: List[Substitution] = field(factory=list)

    def __attrs_post_init__(self):
        """Validate the date format."""
        if not self.date.startswith("Vertretungen am"):
            raise ValueError("Invalid date format")


class HTMLTableParser(HTMLParser):
    """Enhanced HTML table parser with better error handling."""

    def __init__(
        self,
        decode_html_entities: bool = False,
        data_separator: str = " ",
    ) -> None:
        super().__init__(convert_charrefs=decode_html_entities)
        self._data_separator = data_separator
        self._in_td = False
        self._in_th = False
        self._current_table = []
        self._current_row = []
        self._current_cell = []
        self.tables = []
        self.named_tables = {}
        self.name = ""
        self._error = None

    def error(self, message):
        """Override error method to capture parsing errors."""
        self._error = message
        _LOGGER.error(f"HTML parsing error: {message}")

    def get_error(self):
        """Return any parsing error that occurred."""
        return self._error

    def handle_starttag(self, tag: str, attrs: List) -> None:
        try:
            if tag == "table":
                name = [a[1] for a in attrs if a[0] == "id"]
                if name:
                    self.name = name[0]
            if tag == "td":
                self._in_td = True
            if tag == "th":
                self._in_th = True
        except Exception as e:
            self.error(f"Error in handle_starttag: {str(e)}")

    def handle_data(self, data: str) -> None:
        """This is where we save content to a cell"""
        if self._in_td or self._in_th:
            self._current_cell.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        """Here we exit the tags. If the closing tag is </tr>, we know that we
        can save our currently parsed cells to the current table as a row and
        prepare for a new row. If the closing tag is </table>, we save the
        current table and prepare for a new one.
        """
        if tag == "td":
            self._in_td = False
        elif tag == "th":
            self._in_th = False

        if tag in ["td", "th"]:
            final_cell = self._data_separator.join(self._current_cell).strip()
            self._current_row.append(final_cell)
            self._current_cell = []
        elif tag == "tr":
            self._current_table.append(self._current_row)
            self._current_row = []
        elif tag == "table":
            self.tables.append(self._current_table)
            if len(self.name) > 0:
                self.named_tables[self.name] = self._current_table
            self._current_table = []
            self.name = ""


class ksfData:
    """Enhanced KSF data handler with better error handling and caching."""

    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password
        self._substituteplan = None
        self._last_update = None
        self._session_manager = SessionManager()
        self._update_lock = threading.Lock()
        self._state = STATE_UNKNOWN
        self._error_count = 0
        self._max_errors = 3

    def _validate_session(self, session: requests.Session, cookies: Dict) -> bool:
        """Validate if the session is still active."""
        try:
            resp = session.get(
                DEFAULT_LANDINGPAGE_URL,
                cookies=cookies,
                timeout=TIMEOUT,
                allow_redirects=False,
            )
            return resp.status_code == 200 and "login" not in resp.url.lower()
        except Exception as e:
            _LOGGER.error(f"Session validation failed: {str(e)}")
            return False

    def _parse_substitution_data(
        self, page_data: str
    ) -> Tuple[List[SubstitutionDay], Optional[Exception]]:
        """Parse the substitution data with enhanced error handling."""
        try:
            d = pq(page_data)
            if not d:
                raise ParsingError("Failed to parse page with PyQuery")

            dates = []
            vertretungen_dates = d(".panel-body")

            if not vertretungen_dates:
                _LOGGER.warning("No panel-body elements found in page")

            for div in vertretungen_dates.items():
                found_data = div("h3").not_(".hidden-xs").text()
                if found_data.startswith("Vertretungen am"):
                    dates.append(found_data)

            if not dates:
                raise ParsingError("No valid dates found in the page")

            parser = HTMLTableParser()
            parser.feed(page_data)

            if parser.get_error():
                raise ParsingError(f"HTML parsing error: {parser.get_error()}")

            data = parser.named_tables.values()
            substitution_plan = []

            for i, inner_list in enumerate(data):
                if i >= len(dates):
                    _LOGGER.warning("More tables than dates found")
                    break

                if self._is_valid_table(inner_list):
                    plan_of_day = self._process_table(inner_list, dates[i])
                    if plan_of_day:
                        substitution_plan.append(plan_of_day)

            return substitution_plan, None

        except Exception as e:
            _LOGGER.error(f"Error parsing substitution data: {str(e)}")
            return None, e

    def _is_valid_table(self, table: List) -> bool:
        """Check if the table contains valid substitution data."""
        if not table or not table[0]:
            return False

        skip_headers = [
            "['Abwesende Klassen']",
            "['Betroffene Lehrer']",
            "['Abwesende Lehrkräfte']",
            "['Allgemein']",
        ]

        return (
            len(table[0]) > 1
            and table[0][1] != "Datenschutz | Impressum"
            and str(table[0]) not in skip_headers
        )

    def _process_table(self, table: List, date: str) -> Optional[SubstitutionDay]:
        """Process a single table of substitution data."""
        try:
            plan_of_day = SubstitutionDay(date, [])

            if len(table) <= 2 and len(table[1]) == 1:
                # Handle special case with only notice
                notice_field = self._clean_notice(table[1][0])
                substitution = plan_of_day.Substitution(
                    substitute="",
                    teacher="",
                    hours="",
                    class_name="",
                    subject="",
                    subject_old="",
                    room="",
                    room_old="",
                    notice=notice_field,
                )
                plan_of_day.substitutions.append(substitution)
            else:
                # Process normal substitution entries
                for row in table[1:]:
                    if len(row) >= 11:  # Ensure row has all required fields
                        substitution = plan_of_day.Substitution(
                            substitute=row[3],
                            teacher=row[4],
                            hours=row[1],
                            class_name=row[2],
                            subject=row[6],
                            subject_old=row[7],
                            room=row[8],
                            room_old=row[9],
                            notice=row[10] if row[10] else "",
                        )
                        plan_of_day.substitutions.append(substitution)

            return plan_of_day
        except Exception as e:
            _LOGGER.error(f"Error processing table: {str(e)}")
            return None

    def _clean_notice(self, notice: str) -> str:
        """Clean and normalize notice text."""
        notice = str(notice).replace("\n", "")
        while "  " in notice:
            notice = notice.replace("  ", " ")
        return notice.strip()

    def update(self) -> None:
        """Update the substitution plan with enhanced error handling and caching."""
        if self._update_lock.locked():
            _LOGGER.warning("Update already in progress")
            return

        with self._update_lock:
            try:
                now = datetime.now()

                # Check cache validity
                if (
                    self._last_update
                    and self._substituteplan
                    and now - self._last_update < CACHE_DURATION
                ):
                    return

                self._substituteplan, ex = self._get_substituteplan()

                if ex:
                    self._error_count += 1
                    if self._error_count >= self._max_errors:
                        self._state = STATE_UNAVAILABLE
                        _LOGGER.error(
                            f"Too many errors ({self._error_count}), marking as unavailable"
                        )
                else:
                    self._error_count = 0
                    self._state = "ok"
                    self._last_update = now

            except Exception as e:
                _LOGGER.exception(f"Unexpected error in update: {str(e)}")
                self._state = STATE_UNAVAILABLE

    def _get_substituteplan(self) -> Tuple[Optional[str], Optional[Exception]]:
        """Enhanced substitution plan getter with better error handling."""
        try:
            session = self._session_manager.get_session()

            # Prepare request data
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }

            payload = {
                "user2": "user",
                "user": f"6013.{self._username}",
                "password": self._password,
                "skin": "sp",
                "timezone": "1",
                "url": "aHR0cHM6Ly9jb25uZWN0LnNjaHVscG9ydGFsLmhlc3Nlbi5kZS8=",
            }

            # Initial login page request
            resp = session.get(DEFAULT_LOGIN_URL, headers=headers, timeout=TIMEOUT)
            if resp.status_code != 200:
                raise RequestError(f"Failed to access login page: {resp.status_code}")

            # Store initial cookies
            cookies = requests.utils.cookiejar_from_dict(
                requests.utils.dict_from_cookiejar(session.cookies)
            )

            # Perform login
            resp = session.post(
                DEFAULT_LOGIN_URL,
                headers=headers,
                data=payload,
                cookies=cookies,
                timeout=TIMEOUT,
            )
            if resp.status_code != 200:
                raise RequestError("Login failed")

            # Update cookies after login
            cookies = requests.utils.cookiejar_from_dict(
                requests.utils.dict_from_cookiejar(session.cookies)
            )

            # Validate session
            # if not self._validate_session(session, cookies):
            #    raise RequestError("Session validation failed")

            # Get substitute plan
            resp = session.get(
                DEFAULT_SUBSTITUTE_URL,
                cookies=cookies,
                timeout=TIMEOUT,
            )
            if resp.status_code != 200:
                raise RequestError(
                    f"Failed to fetch substitute plan: {resp.status_code}"
                )

            # Parse the data
            substitution_plan, parse_error = self._parse_substitution_data(resp.text)
            if parse_error:
                raise parse_error

            # Convert to JSON
            json_string = jsonpickle.encode(substitution_plan, unpicklable=False)
            return json_string, None

        except RequestError as e:
            _LOGGER.error(f"Request error: {str(e)}")
            return None, e
        except ParsingError as e:
            _LOGGER.error(f"Parsing error: {str(e)}")
            return None, e
        except Exception as e:
            _LOGGER.exception(f"Unexpected error: {str(e)}")
            return None, e
        finally:
            # If we had critical errors, clear the session
            if self._error_count >= self._max_errors:
                self._session_manager.clear_session()


class ksfSensor(Entity):
    """Enhanced KSF sensor with better state management."""

    def __init__(self, name: str, username: str, password: str):
        self._ksf = ksfData(username, password)
        self._state = None
        self._attributes = {}
        self._name = f"ksf_daten_{name}"
        self._username = username
        self._available = True

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._available

    @property
    def unique_id(self) -> str:
        return self._name

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> str:
        return self._state if self._available else STATE_UNAVAILABLE

    @property
    def icon(self) -> str:
        return "mdi:account"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the state attributes."""
        return {
            "Name": self._name,
            "FriendlyName": self._username,
            "SubstitutePlan": str(self._ksf._substituteplan)
            if self._ksf._substituteplan
            else None,
            "LastUpdate": self._ksf._last_update.isoformat()
            if self._ksf._last_update
            else None,
            "State": self._ksf._state,
        }

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self) -> None:
        """Update the sensor."""
        try:
            _LOGGER.debug(f"Updating KSF data for {self._username}")
            self._ksf.update()
            self._available = self._ksf._state != STATE_UNAVAILABLE
            self._state = datetime.now().strftime("%H:%M")
            _LOGGER.info(f"Update KSF done for {self._username}")
        except Exception as e:
            _LOGGER.error(f"Error updating sensor: {str(e)}")
            self._available = False
            self._state = STATE_UNAVAILABLE
