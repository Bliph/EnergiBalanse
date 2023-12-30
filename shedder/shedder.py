import teslapy
import time
import datetime
import logging
import configparser
import argparse
import yaml
import random
import copy
from pathlib import Path
import os
from logging.handlers import WatchedFileHandler
import sys
from integration.mqtt import MQTTClient
from data.float_tb import FloatTimeBuffer
from data.energy_calc import EnergyCalculator
from logger import create_logger

# https://tesla-api.timdorr.com/
# https://github.com/tdorssers/TeslaPy
# https://github.com/nside/pytesla (old)

#DEAD_BAND = 300     # Current dead band when increasing charging current
#ADJUST_TIME = 30    # Min time in sec between adjustments

#PERIOD_DURATION = 3600
#SETTINGS_TOPIC_PREFIX = 'geiterasen/shedd/settings'

__version__ = '0.0.1c'
APP_NAME = os.path.basename(__file__).split('.')[0]
DEFAULT_CFG_DIR = "/etc/opt/jofo/{}".format(APP_NAME)
settings = {}
dynamic_settings = {}
calculator_export = None
calculator_import = None
cfg_dir = DEFAULT_CFG_DIR
MIN_CURRENT = 5

###########################################################
#
#
def ts2iso(ts):
    local_zone = datetime.datetime.now().astimezone().tzinfo
    ts_iso = datetime.datetime.fromtimestamp(ts, local_zone).isoformat()
    return ts_iso

###########################################################
# Get command line arguments
#
def get_arguments(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cfg_dir", help="Location of cfg files", default=DEFAULT_CFG_DIR)
    parser.add_argument("-v", "--version", action="version", version=__version__)
    arguments = parser.parse_args(args)

    return arguments

def merge_dicts(dest, source):
    # Merge in defaults
    for (k, v) in source.items():
        if k not in dest.keys():
            dest[k] = v
        elif isinstance(source.get(k), dict) and isinstance(dest.get(k), dict):
            merge_dicts(dest.get(k), source.get(k))

###########################################################
# Import remote configurable settings
#
def get_dynamic_settings(cfg_dir):
    MAX_PERIOD_ENERGY = 8000

    defaults = {
        'control': {
            'max_energy': MAX_PERIOD_ENERGY,
            'enabled': True,
            'included_cars': ['5YJSA7E21GF130924', '5YJ3E7EB8KF336792']
        }
    }

    filename = str(Path(cfg_dir) / "{}_control.yaml".format(APP_NAME))

    try:
        with open(filename, "r") as f:
            dyn_settings = yaml.safe_load(f)
    except Exception:
        dyn_settings = defaults

    # Merge in defaults
    merge_dicts(dyn_settings, defaults)

    return dyn_settings

###########################################################
# Import remote configurable settings
#
def store_dynamic_settings(cfg_dir, settings):

    filename = str(Path(cfg_dir) / "{}_control.yaml".format(APP_NAME))
    try:
        with open(filename, "w") as f:
            f.write(yaml.dump(settings))
    except Exception:
        pass

###########################################################
# Import settings
#
def get_settings(cfg_dir):
    HOME_LAT = 58.0880027
    HOME_LON = 7.8252463
    DEFAULT_LOG_DIR = "/var/log/jofo/{}".format(APP_NAME)

    defaults = {
        'times': {
            'adjust_period': 30,
            'calculation_period_duration': 3600,
            'loop_sleep': 5,
            'max_offline_time': 600
        },
        'mqtt_server': {
            'host': 'mqtt_host',
            'port': 1883,
            'username': 'mqtt_user',
            'password': 'mqtt_password',
        },
        'mqtt_client': {
            'measurement_topic': 'measurement_topic',
            'power_element': 'power',
            'energy_element': 'energy',
            'timestamp_element': 'timestamp',
            'status_topic': 'topic/shedder/status',
            'control_topic': 'topic/shedder/control'
        },
        'location': {
            'lat': 0.0,
            'lon': 0.0
        },
        'control': {
            'energy_deadband_up': 300,
            'energy_deadband_down': 0,
        },
        'tesla_client': {
            'user_id':'someuser@gmail.com',
            'update_period': 5
        },
        'logging': {
            'log_level': 'DEBUG',
            'log_dir': '.'
        }
    }
    settings = configparser.ConfigParser()
    settings.read_dict(defaults)

    filename = str(Path(cfg_dir) / "{}.conf".format(APP_NAME))
    if not os.path.exists(filename):
        sys.stderr.write('Missing configuration {}!\n'.format(filename))
        sys.exit(1)

    try:
        settings.read(filename)
    except Exception as e:
        sys.stderr.write('Error wile reading configuration {}\n\n{}\n'.format(filename, e))
        sys.exit(1)

    return settings

###########################################################
# Find vehicle with highest/lowest charge power
#
# def select_vehicle(vs, select_max=True):

#     v_return = None

#     try:
#         for v in vs:
#             get_vehicle_data(v)
#             if v.get('charge_state').get('charging_state').lower() == 'charging':
#                 if v_return is None:
#                     v_return = v
#                 elif select_max and v.get('charge_state').get('charger_power') > v_return.get('charge_state').get('charger_power'):
#                     v_return = v
#                 elif not select_max and v.get('charge_state').get('charger_power') < v_return.get('charge_state').get('charger_power'):
#                     v_return = v
#     except Exception as e:
#         pass

#     return v_return

###########################################################
# Update vehicle data if older than <
#
def get_vehicle_data(v):
    prev_ts = 0
    try:
        prev_ts = v.timestamp
    except Exception:
        pass

    if time.time() - prev_ts > settings.getint('tesla_client', 'update_period'):
#        v.get_vehicle_data()
        v.update(v.api('VEHICLE_DATA', endpoints='location_data;drive_state;'
                            'charge_state;climate_state;vehicle_state;'
                            'gui_settings;vehicle_config')['response'])
        v.timestamp = time.time()

    logger.debug(f"{v.get('vin')} updated {ts2iso(v.timestamp)}")
    pass

###########################################################
# Find random vehicle from vehicles charging
#
def get_random_vehicle(vs, included_cars):
    v_return = None

    try:
        l = []
        for v in vs:
            get_vehicle_data(v)
            if v.get('vin') in included_cars and v.get('charge_state').get('charging_state').lower() == 'charging':
                l.append(v)
        if len(l) > 0:
            v_return = random.choice(l)

    except Exception as e:
        logger.warning('get_random_vehicle() failed: {}'.format(e))

    return v_return

###########################################################
# Find vehicle with highest charge power
#
def get_max_vehicle(vs, included_cars):
    MIN_CURRENT = 5
    v_return = None

    try:
        for v in vs:
            get_vehicle_data(v)
            if v.get('vin') in included_cars and v.get('charge_state').get('charging_state').lower() == 'charging':
                if v_return is None:
                    v_return = v
                if v_return.get('charge_state').get('charge_amps') <= MIN_CURRENT:
                    v_return = v
                    # Check power
                elif v.get('charge_state').get('charger_power') >= v_return.get('charge_state').get('charger_power'):
                    v_return = v
    except Exception as e:
        logger.warning('get_max_vehicle() failed: {}'.format(e))

    return v_return

###########################################################
# Find vehicle with lowest charge power
#
def get_min_vehicle(vs, included_cars):
    v_return = None

    try:
        for v in vs:
            get_vehicle_data(v)
            if v.get('vin') in included_cars and v.get('charge_state').get('charging_state').lower() == 'charging':
                if v_return is None:
                    v_return = v
                if v_return.get('charge_state').get('charge_amps') >= v_return.get('charge_state').get('charge_current_request_max'):
                    v_return = v
                    # Check power
                elif v.get('charge_state').get('charger_power') <= v_return.get('charge_state').get('charger_power'):
                    v_return = v
    except Exception as e:
        logger.warning('get_min_vehicle() failed: {}'.format(e))

    return v_return

###########################################################
# Adjust vehicle power up or down
# Returns active current
#
def adjust(v, up=False):
    if v is None:
        return 0

    logger = logging.getLogger(APP_NAME)
    current_current = 0

    try:
        # if not v.available():
        #     v.sync_wake_up()
        get_vehicle_data(v)

        max_current = v.get('charge_state').get('charge_current_request_max')
        current_current = v.get('charge_state').get('charge_amps')

        if not at_location(v):
            logger.debug('Not home!')
            return 0

        if v.get('charge_state').get('charging_state').lower() != 'charging':
            return 0

        if up and current_current < max_current:
            v.command('CHARGING_AMPS', charging_amps=current_current + 1)
        elif not up and current_current > MIN_CURRENT:
            v.command('CHARGING_AMPS', charging_amps=current_current - 1)

        get_vehicle_data(v)
        current_current = v.get('charge_state').get('charge_amps')

    except Exception as e:
        return 0

    if current_current > 0:
        if up:
            logger.debug('Adjusted {} UP to {}A'.format(v.get('display_name'), current_current))
        else:
            logger.debug('Adjusted {} DOWN to {}A'.format(v.get('display_name'), current_current))

    return current_current

###########################################################
# MQTT subscription callbasck
#
def input(message):
    if message.get('topic').startswith(settings.get('mqtt_client', 'control_topic')):
        control = message.get('payload', {})
        dynamic_settings['control'].update(control)
        store_dynamic_settings(cfg_dir, dynamic_settings)

    else:
        ts = message.get('payload', {}).get(settings.get('mqtt_client', 'timestamp_element'))
        p_positive = message.get('payload', {}).get(settings.get('mqtt_client', 'power_element_pos'))
        p_negative = message.get('payload', {}).get(settings.get('mqtt_client', 'power_element_neg'))
        e_export = message.get('payload', {}).get(settings.get('mqtt_client', 'energy_element_neg'))
        e_import = message.get('payload', {}).get(settings.get('mqtt_client', 'energy_element_pos'))
        if p_positive is not None  and ts is not None:
            calculator_import.insert_power(ts=ts, value=p_positive)
        if e_import is not None and ts is not None:
            calculator_import.insert_energy(ts=ts, value=e_import)

        if p_negative is not None and ts is not None:
            calculator_export.insert_power(ts=ts, value=p_negative)
        if e_export is not None and ts is not None:
            calculator_export.insert_energy(ts=ts, value=e_export)

###########################################################
# Check if car is within charging location
# Default to True
#
def at_location(v):
    try:
        lat = v.get('drive_state').get('latitude')
        lon = v.get('drive_state').get('longitude')

        if (abs(lat - settings.getfloat('location', 'lat')) > 0.001 or
            abs(lon - settings.getfloat('location', 'lon')) > 0.001):
            logger.debug('Not home!')
            return False
    except Exception as e:
        pass

    return True

###########################################################
# Car status
#
def get_car_status(vs, included_cars):
    car_status = []
    if vs is not None:
        min_v = get_min_vehicle(vs, included_cars)
        max_v = get_max_vehicle(vs, included_cars)
        for v in vs:
            cs = {}
            try:
                # Ref. https://github.com/tdorssers/TeslaPy/discussions/148
                get_vehicle_data(v)
                # v.update(v.api('VEHICLE_DATA', endpoints='location_data;drive_state;'
                #                     'charge_state;climate_state;vehicle_state;'
                #                     'gui_settings;vehicle_config')['response'])
                # v.timestamp = time.time()

                cs['vin'] = v.get('vin')
                cs['shedder_enabled'] = (v.get('vin') in included_cars)
                cs['at_location'] = at_location(v)
                cs['latitude'] = v.get('drive_state', {}).get('latitude')
                cs['longitude'] = v.get('drive_state', {}).get('longitude')
                cs['car_name'] = v.get('display_name') or v.get('vehicle_state').get('vehicle_name')
                cs['charging_state'] = v.get('charge_state').get('charging_state')
                cs['charger_power'] = v.get('charge_state').get('charger_power')
                cs['charge_current_request'] = v.get('charge_state').get('charge_current_request')
                cs['charge_amps'] = v.get('charge_state').get('charge_amps')
                cs['battery_level'] = v.get('charge_state').get('battery_level')
                cs['charge_current_request_max'] = v.get('charge_state').get('charge_current_request_max')
                cs['charger_phases'] = v.get('charge_state').get('charger_phases')
                cs['charge_rate'] = v.get('charge_state').get('charge_rate')
                cs['timestamp'] = ts2iso(v.get('charge_state').get('timestamp')/1000)
                cs['avaliable'] = v.available()
                cs['minumum_charging_vehicle'] = v == min_v
                cs['maximum_charging_vehicle'] = v == max_v

            except Exception as e:
                print(v.get('vin') + str(e))
            finally:
                car_status.append(cs)

    return car_status

################################################################

if __name__ == '__main__':

    args = get_arguments()
    cfg_dir = args.cfg_dir
    settings = get_settings(cfg_dir=args.cfg_dir)
    dynamic_settings = get_dynamic_settings(cfg_dir=args.cfg_dir)

    create_logger(
        name='timebuffer',
        level=settings.get('logging', 'log_level'),
        log_dir=settings.get('logging', 'log_dir'))

    logger = create_logger(
        name=APP_NAME,
        level=settings.get('logging', 'log_level'),
        log_dir=settings.get('logging', 'log_dir'))

    calculator_import = EnergyCalculator(log_dir=settings.get('logging', 'log_dir'), postfix='_import')
    calculator_export = EnergyCalculator(log_dir=settings.get('logging', 'log_dir'), postfix='_export')

    mqtt_client = MQTTClient(
        client_id=APP_NAME,
        host=settings.get('mqtt_server', 'host'),
        port=settings.getint('mqtt_server', 'port'),
        username=settings.get('mqtt_server', 'username'),
        password=settings.get('mqtt_server', 'password'),
        keepalive=60)

    topics = [
        settings.get('mqtt_client', 'measurement_topic'),
        settings.get('mqtt_client', 'control_topic')
    ]
    mqtt_client.set_input(input=input, topics=topics)
    mqtt_client.start()

    tesla = teslapy.Tesla(
        email=settings.get('tesla_client', 'user_id'),
        cache_file=str(Path(cfg_dir) / 'tesla_cache.json')
    )

    if not tesla.authorized:
        logger.debug('URL: {}'.format(tesla.authorization_url()))
        tesla.fetch_token(authorization_response=input('Enter URL after authentication: '))

    vehicles = tesla.vehicle_list()
    for v in vehicles:
        v.timestamp = 0
        get_vehicle_data(v)

##############################################################################
##############################################################################
##############################################################################
##############################################################################
##############################################################################
#    for i in range(0, len(vehicles)):
#        if vehicles[i].get('vin').upper() == '5YJSA7E21GF130924':
#            del vehicles[i]
#            break
##############################################################################
##############################################################################
##############################################################################
##############################################################################
##############################################################################
    try:
        last_adjust = time.time()
        while True:
            included_cars = dynamic_settings.get('control').get('included_cars')
            period_status_import = calculator_import.period_status(
                max_energy=dynamic_settings.get('control').get('max_energy'),
                duration=settings.getint('times', 'calculation_period_duration'),
                max_offline_time=settings.getint('times', 'max_offline_time'))

            period_status_export = calculator_export.period_status(
                max_energy=16000,
                duration=settings.getint('times', 'calculation_period_duration'),
                max_offline_time=settings.getint('times', 'max_offline_time'))

            mqtt_status = {
                'enabled': dynamic_settings.get('control').get('enabled'),
                'energy_status_import': period_status_import,
                'energy_status_export': period_status_export,
                'monthly_status_import': calculator_import.monthly_status(),
                'cars': get_car_status(vehicles, included_cars),
                'included_cars': included_cars
            }
            mqtt_client.publish(
                topic=settings.get('mqtt_client', 'status_topic'),
                payload=mqtt_status)

            control_current = copy.copy(dynamic_settings)
            control_current['_hint'] = f"Send message to topic '{settings.get('mqtt_client', 'control_topic')}' to change..."

            mqtt_client.publish(
                topic=settings.get('mqtt_client', 'control_topic')+'_current',
                payload=control_current)

            if dynamic_settings.get('control').get('enabled'):

                # Beregn og finn gjenværende effekt
                remaining_max_power = period_status_import.get('remaining_max_power')
                power = period_status_import.get('power_avg_1m')

                # Dersom faktisk effekt > gjenværende tillatt max, gjør noe!
                if period_status_import.get('metering_offline'):

                    logger.debug('Adjusting DOWN when energy/power metering is offline')

                    # Finn kjøretøy med høyest effekt (som skal justeres NED)
                    adjust(get_max_vehicle(vehicles, included_cars), up=False)
                    adjust(get_random_vehicle(vehicles, included_cars), up=False)
                    last_adjust = time.time()
                else:
                    if power > remaining_max_power + settings.getint('control', 'energy_deadband_down') and \
                        time.time()-last_adjust > settings.getint('times', 'adjust_period'):

                        logger.debug('Adjusting DOWN ({:.1f}W > {:.1f}W + db)'.format(power, remaining_max_power))

                        # Finn kjøretøy med høyest effekt (som skal justeres NED)
                        adjust(get_max_vehicle(vehicles, included_cars), up=False)
                        adjust(get_random_vehicle(vehicles, included_cars), up=False)
                        last_adjust = time.time()

                    elif power < remaining_max_power - settings.getint('control', 'energy_deadband_up') \
                        and time.time()-last_adjust > settings.getint('times', 'adjust_period'):

                        logger.debug('Adjusting UP ({:.1f}W < {:.1f}W + db)'.format(power, remaining_max_power))

                        # Finn kjøretøy med lavest effekt (som skal justeres OPP)
                        adjust(get_min_vehicle(vehicles, included_cars), up=True)
                        adjust(get_random_vehicle(vehicles, included_cars), up=True)
                        last_adjust = time.time()

            time.sleep(settings.getint('times', 'loop_sleep'))
    except KeyboardInterrupt:
        pass

    tesla.close()
    sys.exit(1)

# {'topic': 'geiterasen/HAN_gw/HAN_gw_600194744BB7/measurements', 'payload': {'name': 'main_electric_energy', 'tags': {'id_string': 'HAN_gw_600194744BB7', 'mac': 105559901883319}, 'timestamp': 1670796032, 'P_pos': 3902, 'P_neg': 0, 'Q_pos': 1102, 'Q_neg': 0, 'I1': 14.96, 'I2': 3.32, 'I3': 14.77, 'U1': 230, 'U2': 229, 'U3': 231}, 'timestamp': 1670796033706}
# {'topic': 'geiterasen/HAN_gw/HAN_gw_600194744BB7/measurements', 'payload': {'name': 'main_electric_energy', 'tags': {'id_string': 'HAN_gw_600194744BB7', 'mac': 105559901883319}, 'timestamp': 1670796042, 'P_pos': 3868, 'P_neg': 0, 'Q_pos': 1076, 'Q_neg': 0, 'I1': 14.94, 'I2': 3.3, 'I3': 14.61, 'U1': 230, 'U2': 229, 'U3': 232}, 'timestamp': 1670796043674}
# {'topic': 'geiterasen/HAN_gw/HAN_gw_600194744BB7/measurements', 'payload': {'name': 'main_electric_energy', 'tags': {'id_string': 'HAN_gw_600194744BB7', 'mac': 105559901883319}, 'timestamp': 1670796052, 'P_pos': 3927, 'P_neg': 0, 'Q_pos': 1089, 'Q_neg': 0, 'I1': 14.99, 'I2': 3.51, 'I3': 14.72, 'U1': 230, 'U2': 229, 'U3': 231}, 'timestamp': 1670796053703}
# {'topic': 'geiterasen/HAN_gw/HAN_gw_600194744BB7/measurements', 'payload': {'name': 'main_electric_energy', 'tags': {'id_string': 'HAN_gw_600194744BB7', 'mac': 105559901883319}, 'timestamp': 1670796057, 'P_pos': 3858, 'P_neg': 0, 'Q_pos': 1102, 'Q_neg': 0, 'I1': 14.96, 'I2': 3.26, 'I3': 14.7, 'U1': 230, 'U2': 229, 'U3': 231, 'A_pos': 172483.3, 'A_neg': 0, 'R_pos': 25315.5, 'R_neg': 1307.49}, 'timestamp': 1670796058110}
# {'topic': 'geiterasen/HAN_gw/HAN_gw_600194744BB7/measurements', 'payload': {'name': 'main_electric_energy', 'tags': {'id_string': 'HAN_gw_600194744BB7', 'mac': 105559901883319}, 'timestamp': 1670796061, 'P_pos': 3867, 'P_neg': 0, 'Q_pos': 1088, 'Q_neg': 0, 'I1': 14.99, 'I2': 3.23, 'I3': 14.69, 'U1': 230, 'U2': 229, 'U3': 231}, 'timestamp': 1670796062842}
