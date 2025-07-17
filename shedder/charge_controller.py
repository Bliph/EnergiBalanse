import time
import random
import datetime
import log_handler
from requests.exceptions import HTTPError
from utils import ts2iso

class ChargeController():

    MIN_CURRENT = 5
    VEHICLE_SLEEP_TIME = 16*60

    def __init__(
        self,
        vehicles,
        settings,
        home_location: dict,
        update_period: int,
        log_dir: str,
        log_level: str
    ):

        self.vehicles = vehicles
        self.settings = settings
        self.update_period = update_period
        self.home_location = home_location
        self.last_start_stop = 0

        self.logger = log_handler.create_logger(name='charge_controller', log_dir=log_dir, level=log_level)

        # Floor current timer: seconds on lowest curent
        self.floor_time = {}

        for v in vehicles:
            v.timestamp = 0
            self.floor_time[v.get('vin')] = time.time()

            self.get_vehicle_data(v)

    def check_sun_enabled(self, vehicle_data):
        charge_start_time = vehicle_data.get('charge_state', {}).get('scheduled_charging_start_time_app', 0) or 0
        sun_charge_enabled = ((charge_start_time % 60) == self.settings.get('control').get('sun_charge_enable_minute_magic'))     # Enable sun charge if set to xx:30
        cheduled_enabled = (vehicle_data.get('charge_state', {}).get('scheduled_charging_mode') or "").lower() != "off"
        n = vehicle_data.get("display_name", "?") or vehicle_data.get("vehicle_state", {}).get("vehicle_name", "?")
        return sun_charge_enabled and cheduled_enabled

    ###########################################################
    # Update vehicle data if older than <
    #
    def get_vehicle_data(self, v, awake=False):
        prev_ts = 0
        try:
            prev_ts = v.timestamp
        except Exception:
            self.logger.warning(f"Failed to read timestamp: {e}")

        if awake or time.time() - prev_ts > self.update_period:
            try:
                sleep_time = self.settings.get("control").get("sleep_time", {}).get(v.get("vin"), 0) or 0

                v.get_vehicle_summary()
                prev_charge_ts = v.get("charge_state", {}).get("timestamp", 0) / 1000

                if (awake or v.get("charge_state") is None) and not v.available():
                    self.logger.info(
                        f"Waking up vehicle {v.get('vin')} {v.get('display_name', '?') or v.get('vehicle_state', {}).get('vehicle_name', '?')}"
                    )
                    v.sync_wake_up()

                if (
                    awake
                    or v.get("charge_state") is None
                    or (v.get("charge_state", {}).get("charging_state") or "").lower()
                    == "charging"
                    or time.time() - prev_charge_ts > sleep_time
                ):

                    # NOTE: Keep awake
                    v.update(v.api('VEHICLE_DATA', endpoints='location_data;drive_state;'
                                        'charge_state;climate_state;vehicle_state;'
                                        'gui_settings;vehicle_config')['response'])

                    n = v.get("display_name", "?") or v.get("vehicle_state", {}).get(
                        "vehicle_name", "?"
                    )
                    ts = int(v.get("charge_state", {}).get("timestamp", 0) / 1000)
                    self.logger.debug(f"{v.get('vin')} {n} updated {ts2iso(ts)}")

                else:
                    n = v.get("display_name", "?") or v.get("vehicle_state", {}).get("vehicle_name", "?")
                    t = int(prev_charge_ts + sleep_time - time.time())
                    self.logger.debug(f"{v.get('vin')} {n} polling postponed {t // 60}m {t % 60}s (not charging) to avoid keeping vehicle awake")

            except HTTPError as httpe:
                if httpe.response.status_code == 408 and (
                    httpe.response.reason.find("offline") > 0
                    or httpe.response.reason.find("unavailab") > 0
                ):
                    self.logger.info(
                        f"Vehicle {v.get('vin')} unavailable {ts2iso(time.time())}: {httpe.response.reason}"
                    )
                else:
                    self.logger.warning(
                        f"Failed to get vehicle data for {v.get('vin')} at {ts2iso(time.time())}: {e}"
                    )

            except Exception as e:
                self.logger.warning(f"Failed to get vehicle data for {v.get('vin')} at {ts2iso(time.time())}: {e}")

            finally:
                pass

    ###########################################################
    #
    #
    def shed(self, v):
        vin = v.get('vin')
        h = datetime.datetime.now().hour + 1
        self.logger.warning(f"{vin} Shedding/cutting power after {int(time.time() - self.floor_time.get(vin))}s")
        self.logger.warning(f"{vin} => Postponing charging to {h:2}:00:00")

        if self.sun_charge_enabled():
            try:
                if self.check_sun_enabled(vehicle_data=v) \
                    and v.get('charge_state').get('battery_level') < v.get('charge_state').get('charge_limit_soc') \
                    and v.get('charge_state').get('charging_state').lower() == 'charging':
                    if (time.time() - self.last_start_stop) < self.settings.get('control').get('start_stop_guard_time'):
                        self.logger.warning('sun_charge_stop() not completed because of guard time')
                        return

                    self.logger.debug('shed() - sun')

                    # NOTE: Wake
                    v.command('STOP_CHARGE')
                    self.last_start_stop = time.time()

            except Exception as e:
                self.logger.warning('shed() failed: {}'.format(e))

        else:
            # NOTE: Wake
            v.command(
                "SCHEDULED_CHARGING",
                enable=True,
                time=h * 60 + int(random.random() * 10),
            )
            time.sleep(1)
            self.logger.debug('shed() - normal')
            # NOTE: Wake
            v.command("STOP_CHARGE")
            self.last_start_stop = time.time()

    ###########################################################
    # Find random vehicle from vehicles charging
    #
    def sun_charge_enabled(self):

        # Sun charge during day only
        if datetime.datetime.now().hour < self.settings.get('control').get('sun_charge_start_hour') or datetime.datetime.now().hour >= self.settings.get('control').get('sun_charge_stop_hour'):
            return False

        included_cars = self.settings.get('control').get('included_cars')
        sun_charge_enabled = False

        try:
            for v in self.vehicles:
                self.get_vehicle_data(v)

                if v.get('vin') in included_cars:
                    sun_charge_enabled |= self.check_sun_enabled(vehicle_data=v)
                    if sun_charge_enabled:
                        break

        except Exception as e:
            self.logger.warning('get_random_vehicle() failed: {}'.format(e))

        return sun_charge_enabled

    ###########################################################
    # Start charging on vehicles with sun charge enabled
    #
    def sun_charge_start_minimum(self):

        # # Ensure start/stop is not called too often
        # if (time.time() - self.last_start_stop) < self.settings.get('control').get('start_stop_guard_time'):
        #     self.logger.warning('sun_charge_start_minimum() not completed because of guard time')
        #     return

        included_cars = self.settings.get('control').get('included_cars')

        try:
            for v in self.vehicles:
                self.get_vehicle_data(v)

                if v.get('vin') in included_cars:

                    # Start charge if (sun enabled and < level and not charging)
                    if self.check_sun_enabled(vehicle_data=v) \
                        and self.at_location(v) \
                        and v.get('charge_state').get('battery_level') < v.get('charge_state').get('charge_limit_soc') \
                        and v.get('charge_state').get('charging_state').lower() != 'charging':

                        name = v.get('display_name') or v.get('vehicle_state').get('vehicle_name')
                        self.logger.debug(f'sun_charge_start_minimum() {name}')
                        self.get_vehicle_data(v, awake=True)

                        if (time.time() - self.last_start_stop) < self.settings.get('control').get('start_stop_guard_time'):
                            self.logger.warning(f'sun_charge_start_minimum({name}) not completed because of guard time')
                        else:
                            v.command('CHARGING_AMPS', charging_amps=self.MIN_CURRENT)
                            v.command('START_CHARGE')
                            self.last_start_stop = time.time()

        except Exception as e:
            self.logger.warning('start_sun_charge_minimum() failed: {}'.format(e))

    ###########################################################
    # Stop charging on vehicles with sun charge enabled
    #
    def sun_charge_stop(self):

        # Ensure start/stop is not called too often
        if (time.time() - self.last_start_stop) < self.settings.get('control').get('start_stop_guard_time'):
            self.logger.warning('sun_charge_stop() not completed because of guard time')
            return

        self.logger.debug('sun_charge_stop()')

        included_cars = self.settings.get('control').get('included_cars')

        try:
            for v in self.vehicles:
                self.get_vehicle_data(v)

                if v.get('vin') in included_cars:

                    # Start charge if (sun enabled and < level and not charging)
                    if self.check_sun_enabled(vehicle_data=v) \
                        and v.get('charge_state').get('battery_level') < v.get('charge_state').get('charge_limit_soc') \
                        and v.get('charge_state').get('charging_state').lower() == 'charging':

                        # NOTE: Wake
                        v.command("STOP_CHARGE")
                        self.last_start_stop = time.time()

        except Exception as e:
            self.logger.warning('sun_charge_stop() failed: {}'.format(e))

    ###########################################################
    # Find random vehicle from vehicles charging
    #
    def get_random_vehicle(self, sun_mode=False):
        included_cars = self.settings.get('control').get('included_cars')
        v_return = None

        try:
            l = []
            for v in self.vehicles:
                self.get_vehicle_data(v)
                if v.get('vin') in included_cars and v.get('charge_state').get('charging_state').lower() == 'charging':
                    if (not sun_mode) or (sun_mode and self.check_sun_enabled(v)):
                        l.append(v)

            if len(l) > 0:
                v_return = random.choice(l)

        except Exception as e:
            self.logger.warning('get_random_vehicle() failed: {}'.format(e))

        return v_return

    ###########################################################
    # Find vehicle with highest charge power
    #
    def get_max_vehicle(self):
        included_cars = self.settings.get('control').get('included_cars')
        v_return = None

        try:
            for v in self.vehicles:
                self.get_vehicle_data(v)
                if v.get('vin') in included_cars and v.get('charge_state') is not None:
                    if v.get('charge_state').get('charging_state').lower() == 'charging':
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
    def get_min_vehicle(self):
        included_cars = self.settings.get('control').get('included_cars')
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
                # NOTE: Wake
                v.command('CHARGING_AMPS', charging_amps=current_current + 1)

                # Reset floor current timer
                self.floor_time[v.get('vin')] = time.time()

            elif down:
                if current_current > self.MIN_CURRENT:
                    # NOTE: Wake
                    v.command("CHARGING_AMPS", charging_amps=current_current - 1)

                    # Reset floor current timer
                    self.floor_time[v.get('vin')] = time.time()
                else:
                    # If trying to reduce charge power lower than min, cut power
                    if time.time() - self.floor_time[v.get('vin')] > (self.settings.get('control').get('max_floor_time') + int(random.random()*120)):
                        self.shed(v)

            self.get_vehicle_data(v)
            current_current = v.get('charge_state').get('charge_amps')

        except Exception as e:
            return 0

        name = v.get('display_name') or v.get('vehicle_state').get('vehicle_name')
        if current_current > 0:
            if up:
                self.logger.debug(f'Adjusted {name} UP to {current_current+1}A')
            else:
                self.logger.debug(f'Adjusted {name} DOWN to {current_current-1}A')

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
                name = v.get('display_name') or v.get('vehicle_state').get('vehicle_name')
                self.logger.debug(f'{name} ikke hjemme!')
                return False
        except Exception as e:
            pass

        return True

    def count_at_location(self):
        n = 0
        try:
            for v in self.vehicles:
                self.get_vehicle_data(v)
                if self.at_location(v):
                    n += 1
        except Exception as e:
            self.logger.warning(f"count_at_location() failed: {str(e)}")

        return n

    def count_sun_mode_at_location(self):
        n = 0
        try:
            for v in self.vehicles:
                self.get_vehicle_data(v)
                if self.check_sun_enabled(v) and self.at_location(v):
                    n += 1
        except Exception as e:
            self.logger.warning(f"count_sun_mode_at_location() failed: {str(e)}")

        return n

    ###########################################################
    # Car status
    #
    def get_car_status(self):
        included_cars = self.settings.get('control').get('included_cars')
        car_status = []

        if self.vehicles is not None:
            min_v = self.get_min_vehicle()
            max_v = self.get_max_vehicle()
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
                    cs['seconds_until_shed']  = self.settings.get('control').get('max_floor_time') - int(time.time() - self.floor_time.get(v.get('vin')))
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
                    cs['sun_charge_enabled'] = self.check_sun_enabled(vehicle_data=v)

                except Exception as e:
                    print(v.get('vin') + str(e))
                finally:
                    car_status.append(cs)

        return car_status
