import time
import random
import datetime
import log_handler
from utils import ts2iso

class ChargeController():

    MIN_CURRENT = 5

    def __init__(self, vehicles, home_location: dict, update_period: int, max_floor_time: int, log_dir: str, log_level: str):

        self.vehicles = vehicles
        self.update_period = update_period
        self.max_floor_time = max_floor_time
        self.home_location = home_location
        self.logger = log_handler.create_logger(name='charge_controller', log_dir=log_dir, level=log_level)

        # Floor current timer: seconds on lowest curent
        self.floor_time = {}

        for v in vehicles:
            v.timestamp = 0
            self.floor_time[v.get('vin')] = time.time()

            self.get_vehicle_data(v)

    ###########################################################
    # Update vehicle data if older than <
    #
    def get_vehicle_data(self, v):
        prev_ts = 0
        try:
            prev_ts = v.timestamp
        except Exception:
            pass

        if time.time() - prev_ts > self.update_period:
            v.update(v.api('VEHICLE_DATA', endpoints='location_data;drive_state;'
                                'charge_state;climate_state;vehicle_state;'
                                'gui_settings;vehicle_config')['response'])
            v.timestamp = time.time()

            self.logger.debug(f"{v.get('vin')} updated {ts2iso(v.timestamp)}")

    ###########################################################
    #
    #
    def shed(self, v):
        vin = v.get('vin')
        h = datetime.datetime.now().hour + 1
        self.logger.warning(f"{vin} Shedding/cutting power after {int(time.time() - self.floor_time.get(vin))}s")
        self.logger.warning(f"{vin} => Postponing charging to {h:2}:00:00")

        v.command('SCHEDULED_CHARGING', enable=True, time=h*60 + int(random.random()*10))
        time.sleep(1)
        v.command('STOP_CHARGE')

    ###########################################################
    # Find random vehicle from vehicles charging
    #
    def get_random_vehicle(self, included_cars):
        v_return = None

        try:
            l = []
            for v in self.vehicles:
                self.get_vehicle_data(v)
                if v.get('vin') in included_cars and v.get('charge_state').get('charging_state').lower() == 'charging':
                    l.append(v)
            if len(l) > 0:
                v_return = random.choice(l)

        except Exception as e:
            self.logger.warning('get_random_vehicle() failed: {}'.format(e))

        return v_return

    ###########################################################
    # Find vehicle with highest charge power
    #
    def get_max_vehicle(self, included_cars):
        v_return = None

        try:
            for v in self.vehicles:
                self.get_vehicle_data(v)
                if v.get('vin') in included_cars and v.get('charge_state').get('charging_state').lower() == 'charging':
                    if v_return is None:
                        v_return = v
                    if v_return.get('charge_state').get('charge_amps') <= self.MIN_CURRENT:
                        v_return = v
                        # Check power
                    elif v.get('charge_state').get('charger_power') >= v_return.get('charge_state').get('charger_power'):
                        v_return = v
        except Exception as e:
            self.logger.warning('get_max_vehicle() failed: {}'.format(e))

        return v_return

    ###########################################################
    # Find vehicle with lowest charge power
    #
    def get_min_vehicle(self, included_cars):
        v_return = None

        try:
            for v in self.vehicles:
                self.get_vehicle_data(v)
                if v.get('vin') in included_cars and v.get('charge_state').get('charging_state').lower() == 'charging':
                    if v_return is None:
                        v_return = v
                    if v_return.get('charge_state').get('charge_amps') >= v_return.get('charge_state').get('charge_current_request_max'):
                        v_return = v
                        # Check power
                    elif v.get('charge_state').get('charger_power') <= v_return.get('charge_state').get('charger_power'):
                        v_return = v
        except Exception as e:
            self.logger.warning('get_min_vehicle() failed: {}'.format(e))

        return v_return

    ###########################################################
    # Adjust vehicle power up or down
    # Returns active current
    #
    def adjust(self, v, up: bool=False):
        if v is None:
            return 0

        down = not up

        current_current = 0

        try:
            # if not v.available():
            #     v.sync_wake_up()
            self.get_vehicle_data(v)

            max_current = v.get('charge_state').get('charge_current_request_max')
            current_current = v.get('charge_state').get('charge_amps')

            if not self.at_location(v):
                self.logger.debug(f"{v.get('vin')} not home!")

                # Reset floor current timer
                self.floor_time[v.get('vin')] = time.time()
                return 0

            if v.get('charge_state').get('charging_state').lower() != 'charging':

                # Reset floor current timer
                self.floor_time[v.get('vin')] = time.time()
                return 0

            if up and current_current < max_current:
                v.command('CHARGING_AMPS', charging_amps=current_current + 1)

                # Reset floor current timer
                self.floor_time[v.get('vin')] = time.time()

            elif down:
                if current_current > self.MIN_CURRENT:
                    v.command('CHARGING_AMPS', charging_amps=current_current - 1)

                    # Reset floor current timer
                    self.floor_time[v.get('vin')] = time.time()
                else:
                    # If trying to reduce charge power lower than min, cut power
                    if time.time() - self.floor_time[v.get('vin')] > (self.max_floor_time + int(random.random()*120)):
                        self.shed(v)

            self.get_vehicle_data(v)
            current_current = v.get('charge_state').get('charge_amps')

        except Exception as e:
            return 0

        if current_current > 0:
            if up:
                self.logger.debug('Adjusted {} UP to {}A'.format(v.get('display_name'), current_current))
            else:
                self.logger.debug('Adjusted {} DOWN to {}A'.format(v.get('display_name'), current_current))

        return current_current

    ###########################################################
    # Check if car is within charging location
    # Default to True
    #
    def at_location(self, v):
        try:
            lat = v.get('drive_state').get('latitude')
            lon = v.get('drive_state').get('longitude')

            if (abs(lat - self.home_location.get('lat')) > 0.001 or
                abs(lon - self.home_location.get('lon')) > 0.001):
                self.logger.debug('Not home!')
                return False
        except Exception as e:
            pass

        return True

    ###########################################################
    # Car status
    #
    def get_car_status(self, included_cars):
        car_status = []
        if self.vehicles is not None:
            min_v = self.get_min_vehicle(included_cars)
            max_v = self.get_max_vehicle(included_cars)
            for v in self.vehicles:
                cs = {}
                try:
                    # Ref. https://github.com/tdorssers/TeslaPy/discussions/148
                    self.get_vehicle_data(v)
                    # v.update(v.api('VEHICLE_DATA', endpoints='location_data;drive_state;'
                    #                     'charge_state;climate_state;vehicle_state;'
                    #                     'gui_settings;vehicle_config')['response'])
                    # v.timestamp = time.time()

                    cs['vin'] = v.get('vin')
                    cs['shedder_enabled'] = (v.get('vin') in included_cars)
                    cs['shedder_floor_time']  = ts2iso(self.floor_time.get(v.get('vin')))
                    cs['seconds_until_shed']  = self.max_floor_time - int(time.time() - self.floor_time.get(v.get('vin')))
                    cs['at_location'] = self.at_location(v)
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
