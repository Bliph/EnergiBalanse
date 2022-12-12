import teslapy
import time
from integration.mqtt import MQTTClient
from data.float_tb import FloatTimeBuffer

# https://tesla-api.timdorr.com/
# https://github.com/tdorssers/TeslaPy 
# https://github.com/nside/pytesla (old)

power_buffer = FloatTimeBuffer()
energy_buffer = FloatTimeBuffer()

def input(message):
    ts = message.get('payload', {}).get('timestamp')
    p = message.get('payload', {}).get('P_pos')
    e = message.get('payload', {}).get('A_pos')
    if p is not None and ts is not None:
        power_buffer.insert_sorted(ts=ts, value=p)
    if e is not None and ts is not None:
        energy_buffer.insert_sorted(ts=ts, value=e)

    print(str(message))

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
tesla.close()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass

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
