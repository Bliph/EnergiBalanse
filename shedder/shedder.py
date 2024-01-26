import time
import datetime
import logging
import configparser
import argparse
import random
import copy
from pathlib import Path
import os
import sys
import yaml
from integration.mqtt import MQTTClient
from data.energy_calc import EnergyCalculator
from charge_controller import ChargeController
import teslapy
from log_handler import create_logger

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
# Get command line arguments
#
def get_arguments(args_=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cfg_dir", help="Location of cfg files", default=DEFAULT_CFG_DIR)
    parser.add_argument("-v", "--version", action="version", version=__version__)
    arguments = parser.parse_args(args_)

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
            'included_cars': ['5YJSA7E21GF130924', '5YJ3E7EB8KF336792'],
            'max_floor_time': 300
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
        keepalive=60,
        log_dir=settings.get('logging', 'log_dir'))

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

    # WORKAROUND: Ref https://github.com/tdorssers/TeslaPy/pull/158
    # https://github.com/tdorssers/TeslaPy/issues/156
    # https://github.com/teslamate-org/teslamate/issues/3629
#    vehicles = tesla.vehicle_list()
#    vehicles = [teslapy.Vehicle(vehicle=v, tesla=tesla) for v in tesla.api('PRODUCT_LIST')['response']]
    vehicles = []
    for v in tesla.api('PRODUCT_LIST')['response']:
        vehicles.append(teslapy.Vehicle(vehicle=v, tesla=tesla))

    cc = ChargeController(
        vehicles=vehicles,
        settings=dynamic_settings,
        home_location={'lat': settings.getfloat('location', 'lat'), 'lon': settings.getfloat('location', 'lon')},
        update_period=settings.getint('tesla_client', 'update_period'),
        log_dir=settings.get('logging', 'log_dir'),
        log_level='DEBUG'
    )

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
                'cars': cc.get_car_status(),
                'included_cars': included_cars
            }
            mqtt_client.publish(
                topic=settings.get('mqtt_client', 'status_topic'),
                payload=mqtt_status)

            control_status = copy.copy(dynamic_settings)
            control_status['_hint'] = f"Send JSON message to topic '{settings.get('mqtt_client', 'control_topic')}' to change..."

            mqtt_client.publish(
                topic=settings.get('mqtt_client', 'control_topic')+'_status',
                payload=control_status)

            if dynamic_settings.get('control').get('enabled'):

                # Beregn og finn gjenværende effekt
                remaining_max_power = period_status_import.get('remaining_max_power')
                power = period_status_import.get('power_avg_1m')

                # Dersom faktisk effekt > gjenværende tillatt max, gjør noe!
                if period_status_import.get('metering_offline'):

                    logger.debug('Adjusting DOWN when energy/power metering is offline')

                    # Finn kjøretøy med høyest effekt (som skal justeres NED)
                    cc.adjust(cc.get_max_vehicle(), up=False)
                    cc.adjust(cc.get_random_vehicle(), up=False)
                    last_adjust = time.time()
                else:
                    if power > remaining_max_power + settings.getint('control', 'energy_deadband_down') and \
                        time.time()-last_adjust > settings.getint('times', 'adjust_period'):

                        logger.debug('Adjusting DOWN ({:.1f}W > {:.1f}W + db)'.format(power, remaining_max_power))

                        # Finn kjøretøy med høyest effekt (som skal justeres NED)
                        cc.adjust(cc.get_max_vehicle(), up=False)
                        cc.adjust(cc.get_random_vehicle(), up=False)
                        last_adjust = time.time()

                    elif power < remaining_max_power - settings.getint('control', 'energy_deadband_up') \
                        and time.time()-last_adjust > settings.getint('times', 'adjust_period'):

                        logger.debug('Adjusting UP ({:.1f}W < {:.1f}W + db)'.format(power, remaining_max_power))

                        # Finn kjøretøy med lavest effekt (som skal justeres OPP)
                        cc.adjust(cc.get_min_vehicle(), up=True)
                        cc.adjust(cc.get_random_vehicle(), up=True)
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
