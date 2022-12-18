import teslapy
import time
import datetime
from integration.mqtt import MQTTClient
from data.float_tb import FloatTimeBuffer
from data.energy_calc import EnergyCalculator

# https://tesla-api.timdorr.com/
# https://github.com/tdorssers/TeslaPy 
# https://github.com/nside/pytesla (old)

calculator = EnergyCalculator()
DEAD_BAND = 300     # Current dead band when increasing charging current
ADJUST_TIME = 30    # Min time in sec between adjustments
MAX_PERIOD_ENERGY = 8000
PERIOD_DURATION = 3600

def ts2iso(ts):
    local_zone = datetime.datetime.now().astimezone().tzinfo
    ts_iso = datetime.datetime.fromtimestamp(ts, local_zone).isoformat()
    return ts_iso

############
# Workaround based on fix in git issue 103: https://github.com/tdorssers/TeslaPy/issues/103
# https://github.com/tdorssers/TeslaPy/commit/81cd715d42c79555989abfc88c8cea2212698132
#
def get_latest_vehicle_data(v):
    """ Cached data, pushed by the vehicle on sleep, wake and around OTA.
    Raises HTTPError if no data is available and vehicle is not online. """
    response = v.api('CACHED_PROTO_VEHICLE_DATA')['response']
    v.update(response['data'] if 'data' in response else response)
    v.timestamp = time.time()
    return v

###########################################################
# Find vehicle with highest charge current
#
def get_max_vehicle(vs):
    
    v_max = None

    try:
        for v in vs:
            v.get_vehicle_data()
    #        if time.time()-v.get('charge_state').get('timestamp')/1000 > 
            if v.get('charge_state').get('charging_state').lower() == 'charging':
                if v_max is None: 
                    v_max = v
                elif v.get('charge_state').get('charge_amps') > v_max.get('charge_state').get('charge_amps'):
                    v_max = v
    except Exception as e:
        pass

    return v_max

###########################################################
# Find vehicle with highest charge current
#
def get_min_vehicle(vs):
    
    v_min = None

    try:
        for v in vs:
            v.get_vehicle_data()
    #        if time.time()-v.get('charge_state').get('timestamp')/1000 > 
            if v.get('charge_state').get('charging_state').lower() == 'charging':
                if v_min is None: 
                    v_min = v
                elif v.get('charge_state').get('charge_amps') < v_min.get('charge_state').get('charge_amps'):
                    v_min = v
    except Exception as e:
        pass

    return v_min

def adjust(v, up=False):
    if v is None:
        return 0

    current_current = 0

    try:
        # if not v.available():
        #     v.sync_wake_up()
        v.get_vehicle_data()

        lat = v.get('drive_state').get('latitude')
        lon = v.get('drive_state').get('longitude')

        max_current = v.get('charge_state').get('charge_current_request_max')
        current_current = v.get('charge_state').get('charge_amps')

        HOME_LAT = 58.0880027
        HOME_LON = 7.8252463

        if abs(lat - HOME_LAT) > 0.001 or abs(lon - HOME_LON) > 0.001:
            print('Not home!')
            return 0

        if v.get('charge_state').get('charging_state').lower() != 'charging':
            return 0

        if up and current_current < max_current:
            v.command('CHARGING_AMPS', charging_amps=current_current + 1)
        elif not up and current_current > 5:
            v.command('CHARGING_AMPS', charging_amps=current_current - 1)

        v.get_vehicle_data()
        current_current = v.get('charge_state').get('charge_amps')

    except Exception as e:
        return 0

    return current_current

def input(message):
    ts = message.get('payload', {}).get('timestamp')
    p = message.get('payload', {}).get('P_pos')
    e = message.get('payload', {}).get('A_pos')
    if p is not None and ts is not None:
        calculator.insert_power(ts=ts, value=p)
    if e is not None and ts is not None:
        calculator.insert_energy(ts=ts, value=e)

#    print(str(message))

mqtt_client = MQTTClient(
    client_id='johan_tesla', 
    host='forsvoll.casa', 
    port=6883, 
    username='johan', 
    password='036758ff69785e97',
    keepalive=60)

mqtt_client.set_input(input=input, topics=['geiterasen/HAN_gw/+/measurements/#'])
mqtt_client.start()

tesla = teslapy.Tesla('johan.forsvoll@gmail.com')
a = tesla.fetch_token()
if not tesla.authorized:
    print('URL: {}'.format(tesla.authorization_url()))
    tesla.fetch_token(authorization_response=input('Enter URL after authentication: '))

vehicles = tesla.vehicle_list()

for v in vehicles:
    if v.get('vin') == '5YJ3E7EB8KF336792':
        graa = v

    if v.get('vin') == '5YJSA7E21GF130924':
        blaa = v

if False:
    if not graa.available():
        graa.sync_wake_up()
        time.sleep(10)

    graa.command('CHARGING_AMPS', 12)
    graa.command('START_CHARGE')
    graa.command('STOP_CHARGE')

    graa.get_latest_vehicle_data()
    graa.get_vehicle_data()
    graa.get('charge_state').get('charging_state')  # 'Stopped', 
    time.time() - graa.get('charge_state').get('timestamp')/1000

    graa.get('charge_state').get('charge_amps')

    a = blaa.api('CACHED_PROTO_VEHICLE_DATA')['response']
    b = blaa.api('VEHICLE_DATA')['response']

    blaa.get_latest_vehicle_data()
    print(ts2iso(blaa.get('charge_state', {}).get('timestamp', 0)/1000))
    get_latest_vehicle_data(blaa)
    print(ts2iso(blaa.get('charge_state', {}).get('timestamp', 0)/1000))

    get_latest_vehicle_data(graa)
    print(ts2iso(graa.get('charge_state', {}).get('timestamp', 0)/1000))
    pass

try:
    last_adjust = time.time()
    while True:
        payload=calculator.period_status(max_energy=MAX_PERIOD_ENERGY, duration=PERIOD_DURATION)
        mqtt_client.publish(topic='geiterasen/shedd', payload=payload)
        remaining_max_power = payload.get('remaining_max_power')
        power = payload.get('power_avg_1m')
        if power > remaining_max_power and time.time()-last_adjust > ADJUST_TIME:
            v = get_max_vehicle(vehicles)
            np = adjust(v, up=False)
            if np > 0:
                print('Adjusted {} DOWN to {} A'.format(v.get('display_name'), np))
                last_adjust = time.time()
        elif power < remaining_max_power-DEAD_BAND and time.time()-last_adjust > ADJUST_TIME:
            v = get_min_vehicle(vehicles)
            np = adjust(v, up=True)
            if np > 0:
                print('Adjusted {} UP to {} A'.format(v.get('display_name'), np))
                last_adjust = time.time()

        print(str(payload))
        time.sleep(5)
except KeyboardInterrupt:
    pass

tesla.close()

# #

# Loop 1:
#     Les total effekt
#     Les total energy
#     Les ladeeffekt
#     Akkumuler energi for visning
#     Akkumuler effekt / min

#     * P Gjenomsnitt hittil i timen
#     * P Gjennomsnitt momentant
    

# Loop 2
#     juster opp/ned effekt til effekt / min <= 10 kw

# {'topic': 'geiterasen/HAN_gw/HAN_gw_600194744BB7/measurements', 'payload': {'name': 'main_electric_energy', 'tags': {'id_string': 'HAN_gw_600194744BB7', 'mac': 105559901883319}, 'timestamp': 1670796032, 'P_pos': 3902, 'P_neg': 0, 'Q_pos': 1102, 'Q_neg': 0, 'I1': 14.96, 'I2': 3.32, 'I3': 14.77, 'U1': 230, 'U2': 229, 'U3': 231}, 'timestamp': 1670796033706}
# {'topic': 'geiterasen/HAN_gw/HAN_gw_600194744BB7/measurements', 'payload': {'name': 'main_electric_energy', 'tags': {'id_string': 'HAN_gw_600194744BB7', 'mac': 105559901883319}, 'timestamp': 1670796042, 'P_pos': 3868, 'P_neg': 0, 'Q_pos': 1076, 'Q_neg': 0, 'I1': 14.94, 'I2': 3.3, 'I3': 14.61, 'U1': 230, 'U2': 229, 'U3': 232}, 'timestamp': 1670796043674}
# {'topic': 'geiterasen/HAN_gw/HAN_gw_600194744BB7/measurements', 'payload': {'name': 'main_electric_energy', 'tags': {'id_string': 'HAN_gw_600194744BB7', 'mac': 105559901883319}, 'timestamp': 1670796052, 'P_pos': 3927, 'P_neg': 0, 'Q_pos': 1089, 'Q_neg': 0, 'I1': 14.99, 'I2': 3.51, 'I3': 14.72, 'U1': 230, 'U2': 229, 'U3': 231}, 'timestamp': 1670796053703}
# {'topic': 'geiterasen/HAN_gw/HAN_gw_600194744BB7/measurements', 'payload': {'name': 'main_electric_energy', 'tags': {'id_string': 'HAN_gw_600194744BB7', 'mac': 105559901883319}, 'timestamp': 1670796057, 'P_pos': 3858, 'P_neg': 0, 'Q_pos': 1102, 'Q_neg': 0, 'I1': 14.96, 'I2': 3.26, 'I3': 14.7, 'U1': 230, 'U2': 229, 'U3': 231, 'A_pos': 172483.3, 'A_neg': 0, 'R_pos': 25315.5, 'R_neg': 1307.49}, 'timestamp': 1670796058110}
# {'topic': 'geiterasen/HAN_gw/HAN_gw_600194744BB7/measurements', 'payload': {'name': 'main_electric_energy', 'tags': {'id_string': 'HAN_gw_600194744BB7', 'mac': 105559901883319}, 'timestamp': 1670796061, 'P_pos': 3867, 'P_neg': 0, 'Q_pos': 1088, 'Q_neg': 0, 'I1': 14.99, 'I2': 3.23, 'I3': 14.69, 'U1': 230, 'U2': 229, 'U3': 231}, 'timestamp': 1670796062842}
