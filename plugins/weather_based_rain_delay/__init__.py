# !/usr/bin/env python
# first author: Martin Pihrt
__author__ = 'Vaclav Hrabe' # Add netatmo function 

from threading import Thread, Event
import traceback
import json
import time
import datetime
import re
import urllib
import urllib2
import web
from ospy.helpers import stop_onrain
from ospy.log import log
from ospy.options import options, rain_blocks
from ospy.webpages import ProtectedPage
from plugins import PluginOptions, plugin_url
from time import strftime

import i18n

from sys import version_info
import imghdr
import warnings

# HTTP libraries depends upon Python 2 or 3
if version_info.major == 3 :
    import urllib.parse, urllib.request
else:
    from urllib import urlencode
    import urllib2

NAME = 'Weather-based Rain Delay'
LINK = 'settings_page'

plugin_options = PluginOptions(
    NAME,
    {
        'enabled': False,
        'delay_duration': 24,
        'weather_provider': 'yahoo',
        'wapikey': '',
        'use_netatmo': False,
        'netatmo_id':'',
        'netatmo_secret':'',
        'netatmo_user':'',
        'netatmo_pass':'',
        'netatmomac': '',
        'netatmorain': '05:00:00:',
        'netatmo_level': 0.2,
        'netatmo_hour': 12,
        'netatmo_interval': '60',
        'use_cleanup': False
    })

################################################################################
# Main function loop:                                                          #
################################################################################
class weather_to_delay(Thread):
    def __init__(self):
        Thread.__init__(self)
        self.daemon = True
        self._stop = Event()

        self._sleep_time = 0
        self.start()

    def stop(self):
        self._stop.set()

    def update(self):
        self._sleep_time = 0

    def _sleep(self, secs):
        self._sleep_time = secs
        while self._sleep_time > 0 and not self._stop.is_set():
            time.sleep(1)
            self._sleep_time -= 1

    def run(self):
        while not self._stop.is_set():
            try:
                if plugin_options['enabled']:  # if Weather-based Rain Delay plug-in is enabled
                    if plugin_options['use_netatmo']:
                        authorization = ClientAuth()
                        devList = WeatherStationData(authorization)
                        now = time.time()
                        begin = now - (plugin_options['netatmo_hour']) * 3600
                        mac2 = plugin_options['netatmomac']
                        rainmac2 = plugin_options['netatmorain']
                        resp =  (devList.getMeasure (mac2, '1hour', 'sum_rain', rainmac2, date_begin=begin, date_end=now, limit=None, optimize=False) )
                        result = [(time.ctime(int(k)),v[0]) for k,v in resp['body'].items()]
                        result.sort()
                        xdate, xrain = zip(*result)
                        zrain = 0
                        for yrain in xrain:
                            zrain = zrain + yrain
                    else:
                        zrain = 0

                    log.clear(NAME)
                    log.info(NAME, _('Checking rain status') + '...')

                    delaytime = int(plugin_options['netatmo_interval']) * 60

                    weather = get_weather_data() if plugin_options['weather_provider'] == "yahoo" else get_wunderground_weather_data()
                    delay = code_to_delay(weather['code'])

                    if zrain > 0:
                        log.info(NAME, 'Rain detected: ' + ': %.1fmm' % zrain + '. Adding delay of ' + str(delay))
                        rain_blocks[NAME] = datetime.datetime.now() + datetime.timedelta(hours=float(delay))
                        stop_onrain()

                    else:
                        if delay > 0:
                            log.info(NAME, 'Rain detected: ' + weather['text'] + '. Adding delay of ' + str(delay))
                            rain_blocks[NAME] = datetime.datetime.now() + datetime.timedelta(hours=float(delay))
                            stop_onrain()

                        elif delay == 0:
                            log.info(NAME, _('No rain detected') + ': ' + weather['text'] + '. ' + _('No action.'))

                        elif delay < 0:
                            if plugin_options['use_cleanup']:
                                log.info(NAME, _('Good weather detected') + ': ' + weather['text'] + '. ' + _('Removing rain delay.'))
                                if NAME in rain_blocks:
                                    del rain_blocks[NAME]
                            else:
                                log.info(NAME, _('Good weather detected') + ': ' + weather['text'])
                    self._sleep(delaytime)
                                         
                else:
                    log.clear(NAME)
                    log.info(NAME, _('Plug-in is disabled.'))
                    if NAME in rain_blocks:
                        del rain_blocks[NAME]
                    self._sleep(24 * 3600)

            except Exception:
                log.error(NAME, _('Weather-based Rain Delay plug-in') + ':\n' + traceback.format_exc())
                self._sleep(3600)


checker = None

################################################################################
# Helper functions:                                                            #
################################################################################

def start():
    global checker
    if checker is None:
        checker = weather_to_delay()


def stop():
    global checker
    if checker is not None:
        checker.stop()
        checker.join()
        checker = None
    if NAME in rain_blocks:
        del rain_blocks[NAME]


# Resolve location to LID
def get_wunderground_lid():
    if re.search("pws:", options.location):
        lid = options.location
    else:
        data = urllib2.urlopen(
            "http://autocomplete.wunderground.com/aq?h=0&query=" + urllib.quote_plus(options.location))
        data = json.load(data)
        if data is None:
            return ""
        lid = "zmw:" + data['RESULTS'][0]['zmw']

    return lid


def get_woeid():
    data = urllib2.urlopen(
        "http://query.yahooapis.com/v1/public/yql?q=select%20woeid%20from%20geo.placefinder%20where%20text=%22" +
        urllib.quote_plus(options.location) + "%22").read()
    woeid = re.search("<woeid>(\d+)</woeid>", data)
    if woeid is None:
        return 0
    return woeid.group(1)


def get_weather_data():
    woeid = get_woeid()
    if woeid == 0:
        return {}
    data = urllib2.urlopen("http://weather.yahooapis.com/forecastrss?w=" + woeid).read()
    if data is None:
        return {}
    newdata = re.search("<yweather:condition\s+text=\"([\w|\s]+)\"\s+code=\"(\d+)\"\s+temp=\"(\d+)\"\s+date=\"(.*)\"",
                        data)
    weather = {"text": newdata.group(1),
               "code": newdata.group(2)}
    return weather


def get_wunderground_weather_data():
    lid = get_wunderground_lid()
    if lid == "":
        return []
    data = urllib2.urlopen(
        "http://api.wunderground.com/api/" + plugin_options['wapikey'] + "/conditions/q/" + lid + ".json")
    data = json.load(data)
    if data is None:
        return {}
    if 'error' in data['response']:
        return {}
    weather = {"text": data['current_observation']['weather'],
               "code": data['current_observation']['icon']}
    return weather


# Lookup code and get the set delay
def code_to_delay(code):
    if plugin_options['weather_provider'] == "yahoo":
        adverse_codes = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 35, 37, 38, 39, 40, 41, 42,
                         43, 44, 45, 46, 47]
        reset_codes = [36]
    else:
        adverse_codes = ["flurries", "sleet", "rain", "sleet", "snow", "tstorms"]
        adverse_codes += ["chance" + code_name for code_name in adverse_codes]
        reset_codes = ["sunny", "clear", "mostlysunny", "partlycloudy"]
    if code in adverse_codes:
        return float(plugin_options['delay_duration'])
    if code in reset_codes:
        return -1
    return 0


################################################################################
# Web pages:                                                                   #
################################################################################
class settings_page(ProtectedPage):
    """Load an html page for entering Weather-based Rain Delay adjustments"""

    def GET(self):
        return self.plugin_render.weather_based_rain_delay(plugin_options, log.events(NAME))

    def POST(self):
        plugin_options.web_update(web.input())
        if checker is not None:
            checker.update()
        raise web.seeother(plugin_url(settings_page), True)


class settings_json(ProtectedPage):
    """Returns plugin settings in JSON format"""

    def GET(self):
        web.header('Access-Control-Allow-Origin', '*')
        web.header('Content-Type', 'application/json')
        return json.dumps(plugin_options)


#########################################################################
#NetAtmo APi
#########################################################################

# Published Jan 2013
# Revised Jan 2014 (to add new modules data)
# Author : Philippe Larduinat, philippelt@users.sourceforge.net
# Public domain source code

#########################################################################


# Common definitions
_CLIENT_ID     = (plugin_options['netatmo_id'])   # Your client ID from Netatmo app registration at http://dev.netatmo.com/dev/listapps
_CLIENT_SECRET = (plugin_options['netatmo_secret'])   # Your client app secret   '     '
_USERNAME      = (plugin_options['netatmo_user'])   # Your netatmo account username
_PASSWORD      = (plugin_options['netatmo_pass'])   # Your netatmo account password
_BASE_URL       = "https://api.netatmo.com/"
_AUTH_REQ       = _BASE_URL + "oauth2/token"
_GETMEASURE_REQ = _BASE_URL + "api/getmeasure"
_GETSTATIONDATA_REQ = _BASE_URL + "api/getstationsdata"
_GETEVENTSUNTIL_REQ = _BASE_URL + "api/geteventsuntil"


class ClientAuth:
    """
    Request authentication and keep access token available through token method. Renew it automatically if necessary

    Args:
        clientId (str): Application clientId delivered by Netatmo on dev.netatmo.com
        clientSecret (str): Application Secret key delivered by Netatmo on dev.netatmo.com
        username (str)
        password (str)
        scope (Optional[str]): Default value is 'read_station'
            read_station: to retrieve weather station data (Getstationsdata, Getmeasure)
            read_camera: to retrieve Welcome data (Gethomedata, Getcamerapicture)
            access_camera: to access the camera, the videos and the live stream.
            Several value can be used at the same time, ie: 'read_station read_camera'
    """

    def __init__(self, clientId=_CLIENT_ID,
                       clientSecret=_CLIENT_SECRET,
                       username=_USERNAME,
                       password=_PASSWORD,
                       scope="read_station"):
        postParams = {
                "grant_type" : "password",
                "client_id" : clientId,
                "client_secret" : clientSecret,
                "username" : username,
                "password" : password,
                "scope" : scope
                }
        resp = postRequest(_AUTH_REQ, postParams)
        self._clientId = clientId
        self._clientSecret = clientSecret
        self._accessToken = resp['access_token']
        self.refreshToken = resp['refresh_token']
        self._scope = resp['scope']
        self.expiration = int(resp['expire_in'] + time.time())

    @property
    def accessToken(self):

        if self.expiration < time.time(): # Token should be renewed
            postParams = {
                    "grant_type" : "refresh_token",
                    "refresh_token" : self.refreshToken,
                    "client_id" : self._clientId,
                    "client_secret" : self._clientSecret
                    }
            resp = postRequest(_AUTH_REQ, postParams)
            self._accessToken = resp['access_token']
            self.refreshToken = resp['refresh_token']
            self.expiration = int(resp['expire_in'] + time.time())
        return self._accessToken


class User:
    """
    This class returns basic information about the user

    Args:
        authData (ClientAuth): Authentication information with a working access Token
    """
    def __init__(self, authData):
        postParams = {
                "access_token" : authData.accessToken
                }
        resp = postRequest(_GETSTATIONDATA_REQ, postParams)
        self.rawData = resp['body']
        self.devList = self.rawData['devices']
        self.ownerMail = self.rawData['user']['mail']

class WeatherStationData:
    """
    List the Weather Station devices (stations and modules)

    Args:
        authData (ClientAuth): Authentication information with a working access Token
    """
    def __init__(self, authData):
        self.getAuthToken = authData.accessToken
        postParams = {
                "access_token" : self.getAuthToken
                }
        resp = postRequest(_GETSTATIONDATA_REQ, postParams)
        self.rawData = resp['body']['devices']
        self.stations = { d['_id'] : d for d in self.rawData }
        self.modules = dict()
        for i in range(len(self.rawData)):
            for m in self.rawData[i]['modules']:
                self.modules[ m['_id'] ] = m
        self.default_station = list(self.stations.values())[0]['station_name']

    def modulesNamesList(self, station=None):
        res = [m['module_name'] for m in self.modules.values()]
        res.append(self.stationByName(station)['module_name'])
        return res

    def stationByName(self, station=None):
        if not station : station = self.default_station
        for i,s in self.stations.items():
            if s['station_name'] == station :
                return self.stations[i]
        return None

    def stationById(self, sid):
        return None if sid not in self.stations else self.stations[sid]

    def moduleByName(self, module, station=None):
        s = None
        if station :
            s = self.stationByName(station)
            if not s : return None
        for m in self.modules:
            mod = self.modules[m]
            if mod['module_name'] == module :
                if not s or mod['main_device'] == s['_id'] : return mod
        return None

    def moduleById(self, mid, sid=None):
        s = self.stationById(sid) if sid else None
        if mid in self.modules :
            if s:
                for module in s['modules']:
                    if module['_id'] == mid:
                        return module
            else:
                return self.modules[mid]

    def lastData(self, station=None, exclude=0):
        s = self.stationByName(station)
        if not s : return None
        lastD = dict()
        # Define oldest acceptable sensor measure event
        limit = (time.time() - exclude) if exclude else 0
        ds = s['dashboard_data']
        if ds['time_utc'] > limit :
            lastD[s['module_name']] = ds.copy()
            lastD[s['module_name']]['When'] = lastD[s['module_name']].pop("time_utc")
            lastD[s['module_name']]['wifi_status'] = s['wifi_status']
        for module in s["modules"]:
            ds = module['dashboard_data']
            if ds['time_utc'] > limit :
                lastD[module['module_name']] = ds.copy()
                lastD[module['module_name']]['When'] = lastD[module['module_name']].pop("time_utc")
                # For potential use, add battery and radio coverage information to module data if present
                for i in ('battery_vp', 'rf_status') :
                    if i in module : lastD[module['module_name']][i] = module[i]
        return lastD

    def checkNotUpdated(self, station=None, delay=3600):
        res = self.lastData(station)
        ret = []
        for mn,v in res.items():
            if time.time()-v['When'] > delay : ret.append(mn)
        return ret if ret else None

    def checkUpdated(self, station=None, delay=3600):
        res = self.lastData(station)
        ret = []
        for mn,v in res.items():
            if time.time()-v['When'] < delay : ret.append(mn)
        return ret if ret else None

    def getMeasure(self, device_id, scale, mtype, module_id=None, date_begin=None, date_end=None, limit=None, optimize=False, real_time=False):
        postParams = { "access_token" : self.getAuthToken }
        postParams['device_id']  = device_id
        if module_id : postParams['module_id'] = module_id
        postParams['scale']      = scale
        postParams['type']       = mtype
        if date_begin : postParams['date_begin'] = date_begin
        if date_end : postParams['date_end'] = date_end
        if limit : postParams['limit'] = limit
        postParams['optimize'] = "true" if optimize else "false"
        postParams['real_time'] = "true" if real_time else "false"
        return postRequest(_GETMEASURE_REQ, postParams)

    def MinMaxTH(self, station=None, module=None, frame="last24"):
        if not station : station = self.default_station
        s = self.stationByName(station)
        if not s :
            s = self.stationById(station)
            if not s : return None
        if frame == "last24":
            end = time.time()
            start = end - 24*3600 # 24 hours ago
        elif frame == "day":
            start, end = todayStamps()
        if module and module != s['module_name']:
            m = self.moduleByName(module, s['station_name'])
            if not m :
                m = self.moduleById(s['_id'], module)
                if not m : return None
            # retrieve module's data
            resp = self.getMeasure(
                    device_id  = s['_id'],
                    module_id  = m['_id'],
                    scale      = "max",
                    mtype      = "Temperature,Humidity",
                    date_begin = start,
                    date_end   = end)
        else : # retrieve station's data
            resp = self.getMeasure(
                    device_id  = s['_id'],
                    scale      = "max",
                    mtype      = "Temperature,Humidity",
                    date_begin = start,
                    date_end   = end)
        if resp:
            T = [v[0] for v in resp['body'].values()]
            H = [v[1] for v in resp['body'].values()]
            return min(T), max(T), min(H), max(H)
        else:
            return None

class DeviceList(WeatherStationData):
    """
    This class is now deprecated. Use WeatherStationData directly instead
    """
    warnings.warn("The 'DeviceList' class was renamed 'WeatherStationData'",
            DeprecationWarning )
    pass

# Utilities routines

def postRequest(url, params, json_resp=True, body_size=65535):
    # Netatmo response body size limited to 64k (should be under 16k)
    if version_info.major == 3:
        req = urllib.request.Request(url)
        req.add_header("Content-Type","application/x-www-form-urlencoded;charset=utf-8")
        params = urllib.parse.urlencode(params).encode('utf-8')
        resp = urllib.request.urlopen(req, params).read(body_size).decode("utf-8")
    else:
        params = urlencode(params)
        headers = {"Content-Type" : "application/x-www-form-urlencoded;charset=utf-8"}
        req = urllib2.Request(url=url, data=params, headers=headers)
        resp = urllib2.urlopen(req).read(body_size)
    if json_resp:
        return json.loads(resp)
    else:
        return resp

def toTimeString(value):
    return time.strftime("%Y-%m-%d_%H:%M:%S", time.localtime(int(value)))

def toEpoch(value):
    return int(time.mktime(time.strptime(value,"%Y-%m-%d_%H:%M:%S")))

def todayStamps():
    today = time.strftime("%Y-%m-%d")
    today = int(time.mktime(time.strptime(today,"%Y-%m-%d")))
    return today, today+3600*24

# Global shortcut

def getStationMinMaxTH(station=None, module=None):
    authorization = ClientAuth()
    devList = DeviceList(authorization)
    if not station : station = devList.default_station
    if module :
        mname = module
    else :
        mname = devList.stationByName(station)['module_name']
    lastD = devList.lastData(station)
    if mname == "*":
        result = dict()
        for m in lastD.keys():
            if time.time()-lastD[m]['When'] > 3600 : continue
            r = devList.MinMaxTH(module=m)
            result[m] = (r[0], lastD[m]['Temperature'], r[1])
    else:
        if time.time()-lastD[mname]['When'] > 3600 : result = ["-", "-"]
        else : result = [lastD[mname]['Temperature'], lastD[mname]['Humidity']]
        result.extend(devList.MinMaxTH(station, mname))
    return result