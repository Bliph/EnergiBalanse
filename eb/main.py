import teslapy
from integration.mqtt import MQTTClient

# https://tesla-api.timdorr.com/
# https://github.com/tdorssers/TeslaPy 
# https://github.com/nside/pytesla (old)


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


def input(message):
    print(str(message))

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