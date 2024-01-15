"""KSF Data fetcher (Substitute plan of Kopernikusschule Freigericht).

Original Author:  Thomas Wolf

Description:
    Configuration Instructions are on GitHub.
"""

from datetime import datetime, timedelta
from html.parser import HTMLParser
import logging
from typing import List  # noqa: UP035

from attrs import define, field
from pyquery import PyQuery as pq
import requests

from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

from .const import DOMAIN

import jsonpickle

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=10)

DEFAULT_LOGIN_URL = "https://login.schulportal.hessen.de/?url=aHR0cHM6Ly9jb25uZWN0LnNjaHVscG9ydGFsLmhlc3Nlbi5kZS8=&skin=sp&i=6013"
DEFAULT_LANDINGPAGE_URL = "https://connect.schulportal.hessen.de/"
DEFAULT_SUBSTITUTE_URL = "https://start.schulportal.hessen.de/vertretungsplan.php"


def setup_platform(hass, config, add_entities, discovery_info=None):
    # url = config.get("url")
    username = config.get("username")
    password = config.get("password")
    name = config.get("name")

    # if not url or not username or not password or not name:
    #    _LOGGER.error("URL, username, name or password not provided.")
    #    return False

    try:
        # _LOGGER.debug(f"Loading KSF data from {url}")
        ksf = ksfData(username, password)
        ksf.update()
    except Exception as e:
        _LOGGER.error(f"Failed to connect to KSF: {e}")
        return False

    ksf_entity = ksfSensor(ksf, name, username)
    add_entities([ksf_entity], True)


#    add_entities(
#        [
#            PortainerContainerSensor(container, ksf, url, name)
#            for container in ksf.containers
#        ],
#        True,
#    )


class ksfSensor(Entity):
    def __init__(self, ksf, name, username):
        self._ksf = ksf
        self._state = None
        self._attributes = {}
        self._name = f"ksf_daten_{name}"
        self._username = username

    @property
    def unique_id(self):
        return self._name

    @property
    def name(self):
        return self._name

    @property
    def username(self):
        return self._username

    @property
    def state(self):
        return self._state

    @property
    def icon(self):
        return "mdi:account"

    @property
    def extra_state_attributes(self):
        return self._attributes

    @property
    def extra_state_attributes(self):
        return {
            "Name": self._name,
            "FriendlyName": self._username,
            # "Version": self._portainer.version,
            "SubstitutePlan": str(self._ksf.substituteplan),
        }

    def update(self):
        self._ksf.update()
        _LOGGER.debug(f"Updating KSF data for {self._ksf.username}")
        now = datetime.now().strftime("%H:%M")
        _LOGGER.info("It is {}".format(now))
        self._state = now


class ksfData:
    def __init__(self, username, password):
        self._username = username
        self._password = password
        self._substituteplan = None

    @property
    def substituteplan(self):
        return self._substituteplan

    @property
    def username(self):
        return self._username

    @property
    def state(self):
        return self._state

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        ex = None
        if not self._substituteplan:
            self._substituteplan, ex = self._get_substituteplan()

        if self._substituteplan:
            self._state = True
        else:
            self._state = False
            _LOGGER.error("Failed to request substituteplan!")

    def _get_substituteplan(self):
        """Vertretungsplan getter using pyscript."""
        try:
            # log.info(f"Vertretungsplan: got user {user} password {password}")
            login_url = DEFAULT_LOGIN_URL
            landing_url = DEFAULT_LANDINGPAGE_URL
            substitute_url = DEFAULT_SUBSTITUTE_URL
            payload = {
                "user2": "user",
                "user": "6013." + str(self._username),
                "password": str(self._password),
                "skin": "sp",
                "timezone": "1",
                "url": "aHR0cHM6Ly9jb25uZWN0LnNjaHVscG9ydGFsLmhlc3Nlbi5kZS8=",
            }
            headers = {"User-Agent": "Mozilla/5.0"}

            # log.info(f"Start login")
            session = requests.Session()
            resp = session.get(login_url, headers=headers, timeout=5)
            # did this for first to get the cookies from the page, stored them with next line:
            cookies = requests.utils.cookiejar_from_dict(
                requests.utils.dict_from_cookiejar(session.cookies)
            )
            resp = session.post(
                login_url, headers=headers, data=payload, cookies=cookies
            )
            if resp.status_code != 200:
                retVal = "Login failed!"
                _LOGGER.error("Login not possible")
                return retVal, None

            cookies = requests.utils.cookiejar_from_dict(
                requests.utils.dict_from_cookiejar(session.cookies)
            )
            resp = session.get(landing_url, cookies=cookies)
            if resp.status_code != 200:
                retVal = "Calling connect.schulportal.hessen.de not possible"
                _LOGGER.error("Calling connect.schulportal.hessen.de not possible")
                return retVal, None

            cookies = requests.utils.cookiejar_from_dict(
                requests.utils.dict_from_cookiejar(session.cookies)
            )

            resp = session.get(
                substitute_url,
                cookies=cookies,
            )
            if resp.status_code != 200:
                retVal = "Calling https://start.schulportal.hessen.de/vertretungsplan.php not possible"
                _LOGGER.error(
                    "Calling https://start.schulportal.hessen.de/vertretungsplan.php not possible"
                )
                return retVal, None

            pageData = resp.text
            # start processing and parsing of the page...
            d = pq(pageData)

            dates = []
            VertretungenDates = d(".panel-body")
            for my_div in VertretungenDates.items():
                dates.append(my_div("h3").text())

            p = HTMLTableParser()
            p.feed(pageData)
            data = p.tables

            i = 1
            SubstitutionPlan = []
            for inner_list in data:
                if len(inner_list[0]) > 1:
                    if inner_list[0][1] == "Datenschutz | Impressum":
                        break
                if (
                    str(inner_list[0]) == "['Abwesende Klassen']"
                    or str(inner_list[0]) == "['Betroffene Lehrer']"
                    or str(inner_list[0]) == "['Abwesende Lehrkräfte']"
                ):
                    continue
                planOfDay = SubstitutionDay(dates[i], [])
                if len(inner_list) <= 2 and len(inner_list[1]) == 1:
                    noticeField = str(inner_list[1][0]).replace("\n", "")
                    while "  " in noticeField:
                        noticeField = noticeField.replace("  ", " ")
                    substitution_data = planOfDay.Substitution(
                        substitute="",
                        teacher="",
                        hours="",
                        class_name="",
                        subject="",
                        subject_old="",
                        room="",
                        room_old="",
                        notice=noticeField,
                    )
                    planOfDay.substitutions.append(substitution_data)
                else:
                    # Stunde Klasse Vertretung Lehrkraft Art Fach Fach_alt Raum Raum_alt Hinweis
                    for sublist in inner_list[1:]:
                        substitution_data = planOfDay.Substitution(
                            substitute=sublist[3],
                            teacher=sublist[4],
                            hours=sublist[1],
                            class_name=sublist[2],
                            subject=sublist[6],
                            subject_old=sublist[7],
                            room=sublist[8],
                            room_old=sublist[9],
                            notice=sublist[10] if sublist[10] else None,
                        )
                        planOfDay.substitutions.append(substitution_data)
                i += 1
                SubstitutionPlan.append(planOfDay)

            json_string = jsonpickle.encode(SubstitutionPlan, unpicklable=False)
            # json_string = jsonpickle.encode(SubstitutionPlan)

            return json_string, None
        except Exception as e:
            _LOGGER.error("Failed to request substituteplan - exception occured!")
            return None, e


class HTMLTableParser(HTMLParser):
    """This class serves as a html table parser. It is able to parse multiple
    tables which you feed in. You can access the result per .tables field.
    """

    def __init__(
        self,
        decode_html_entities: bool = False,
        data_separator: str = " ",
    ) -> None:
        HTMLParser.__init__(self, convert_charrefs=decode_html_entities)

        self._data_separator = data_separator

        self._in_td = False
        self._in_th = False
        self._current_table = []
        self._current_row = []
        self._current_cell = []
        self.tables = []
        self.named_tables = {}
        self.name = ""

    def handle_starttag(self, tag: str, attrs: List) -> None:
        """We need to remember the opening point for the content of interest.
        The other tags (<table>, <tr>) are only handled at the closing point.
        """
        if tag == "table":
            name = [a[1] for a in attrs if a[0] == "id"]
            if len(name) > 0:
                self.name = name[0]
        if tag == "td":
            self._in_td = True
        if tag == "th":
            self._in_th = True

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


@define
class SubstitutionDay:
    """The substitution plan page in a data type.

    Parameters
    ----------
    date : datetime.datetime
        Date of the substitution plan.
    substitutions : list[Substitution]
        The individual substitutions.
    info : str
        ``info`` is the box with the title "Allgemein" that exists sometimes.
    """

    @define
    class Substitution:
        """The individual substitution data (table row).

        Parameters
        ----------
        substitute : str
            Often abbreviation of the substitute.
        teacher : str
            Often abbreviation of the teacher.
        hours : str
            When is it in school hours.
        class_name : str
            Name of the classes.
        subject : str
            The subject is rarely given.
        room : str
            Room of the substitution.
        notice : str
            More info about the substitution.
        """

        substitute: field(type=str)
        teacher: field(type=str)
        hours: field(type=str)
        class_name: field(type=str)
        subject: field(type=str)
        subject_old: field(type=str)
        room: field(type=str)
        room_old: field(type=str)
        notice: field(type=str)

    date: field(type=datetime)
    substitutions: field(factory=list, type=list[Substitution])
