import time
import datetime
from pathlib import Path
from .float_tb import FloatTimeBuffer

#####################################################################
# Returns (start, end) of month as timestamps
#
def epoch_to_month_ts(ts=None):

    if ts is None:
        ts = int(time.time())
    else:
        ts = int(ts)

    local_zone = datetime.datetime.now().astimezone().tzinfo

    from_date = datetime.datetime.fromtimestamp(ts, local_zone).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    to_date = (from_date + datetime.timedelta(days=32)).replace(day=1)

    return (int(from_date.timestamp()), int(to_date.timestamp()))

# #########################################################################
# Returns iso time to local time zone from epoch time (ms)
#
def ts2iso(ts):
    local_zone = datetime.datetime.now().astimezone().tzinfo
    ts_iso = datetime.datetime.fromtimestamp(ts, local_zone).isoformat()
    return ts_iso

# #########################################################################
# Returns YYYY.MM.DD time to local time zone from epoch time
#
def ts2ymd(ts):
    local_zone = datetime.datetime.now().astimezone().tzinfo
    ts_ymd = datetime.datetime.fromtimestamp(ts, local_zone).strftime('%Y.%m.%d')
    return ts_ymd

# #########################################################################
# Returns HH:MM:SS time to local time zone from epoch time 
#
def ts2hms(ts):
    local_zone = datetime.datetime.now().astimezone().tzinfo
    ts_hms = datetime.datetime.fromtimestamp(ts, local_zone).strftime('%H:%M:%S')
    return ts_hms

#####################################################################
# Returns (start, end) of month as timestamps
#
class EnergyCalculator():
    def __init__(self, log_dir='.', postfix=''):
        self.power_buffer = FloatTimeBuffer(age=7*3600, backup_filename=str(Path(log_dir) / f'power_buffer{postfix}.yaml'))
        self.energy_buffer = FloatTimeBuffer(age=24*3600*32, backup_filename=str(Path(log_dir) / f'energy_buffer{postfix}.yaml'), accumulated=True)

    def insert_power(self, ts, value):
        self.power_buffer.insert_sorted(ts=ts, value=value)

    def insert_energy(self, ts, value):
        self.energy_buffer.insert_sorted(ts=ts, value=value)

    def monthly_status(self, ts=None):
        if ts is None:
            ts = int(time.time())
        else:
            ts = int(ts)

        (ts_from, ts_to) = epoch_to_month_ts(ts)
        this_month_max = self.energy_buffer.get_period_max_list(ts_from, ts_to, duration=3600*24)[:3]
        this_month_min = self.energy_buffer.get_period_min_list(ts_from, ts_to, duration=3600*24)[:3]

        (ts_from, ts_to) = epoch_to_month_ts(ts_from-3600)
        prev_month_max = self.energy_buffer.get_period_max_list(ts_from, ts_to, duration=3600*24)[:3]
        prev_month_min = self.energy_buffer.get_period_min_list(ts_from, ts_to, duration=3600*24)[:3]

        # Normalize and add human readable timestamp
        for l in [this_month_max, this_month_min, prev_month_max, prev_month_min]:
            for e in l:
                e[0] = ts2ymd(e[0]) + ' ' + ts2hms(e[0])
                e[1] = int(e[1] * 1000)

        if len(this_month_max) > 0:
            this_avg = int(sum(e[1] for e in this_month_max) / len(this_month_max))
        else:
            this_avg = 0

        if len(prev_month_max) > 0:
            prev_avg = int(sum(e[1] for e in prev_month_max) / len(prev_month_max))
        else:
            prev_avg = 0

        return {
            'this_month': {
                'max_values': this_month_max,
                'min_values': this_month_min,
                'max3_avg': this_avg
            },
            'prev_month': {
                'max_values': prev_month_max,
                'min_values': prev_month_min,
                'max3_avg': prev_avg
            }
        }

    def period_status(self, max_energy, ts=None, duration=3600, max_offline_time=600):
        if ts is None:
            ts = int(time.time())
        else:
            ts = int(ts)

        ts_from = duration*int(ts/duration)
        ts_to = ts_from + duration
        energy = self.power_buffer.integrate(ts_from=ts_from, ts_to=ts)/3600
        remaining_time = max(ts_to - ts, 1)     # Minimmum value 1 to avoid /0

        last_power = self.power_buffer.get_last_tuple()
        if last_power is None:
            metering_offline = True
        else:
            metering_offline = int(time.time()) - last_power[0] > max_offline_time

        # Set emulated power-usage to max if power-reading is offline/missing to avoid over-usage 
        if metering_offline:
            if last_power is None or last_power[1] < max_energy*3600/duration:
                self.insert_power(ts=ts-max_offline_time, value=max_energy*3600/duration)

        power_avg_1m = self.power_buffer.avg(ts_from=ts-60, ts_to=ts)
        power_avg_5m = self.power_buffer.avg(ts_from=ts-300, ts_to=ts)

        ret = {
            'ts_from': ts_from,
            'ts_to': ts_to,
            'ts_from_text': ts2hms(ts_from),
            'ts_to_text': ts2hms(ts_to),
            'duration': duration,
            'duration_text': time.strftime("%H:%M:%S", time.gmtime(duration)),
            'ts': ts,
            'power': self.power_buffer.get_value(ts=ts, selection='pre'),
            'power_ts': self.power_buffer.sorted_list[-1][0],
            'power_ts_text': ts2ymd(self.power_buffer.sorted_list[-1][0]) + ' ' + ts2hms(self.power_buffer.sorted_list[-1][0]),
            'power_avg_1m': power_avg_1m,
            'power_avg_5m': power_avg_5m,
            'metering_offline': metering_offline,
            'energy': energy,
            'max_energy': max_energy,
            'remaining_energy': max_energy - energy,
            'remaining_time': remaining_time,
            'remaining_max_power': 3600*(max_energy - energy)/remaining_time,
            'estimated_energy': energy + power_avg_1m*remaining_time/3600,
            'prev_hour_energy': 1000*self.energy_buffer.get_value(ts=int(time.time())) - \
                1000*self.energy_buffer.get_value(ts=int(time.time()-3600), selection='pre'),
            'prev_hour_energy_ts': self.energy_buffer.sorted_list[-1][0],
            'prev_hour_energy_ts_text': ts2ymd(self.energy_buffer.sorted_list[-1][0]) + ' ' + ts2hms(self.energy_buffer.sorted_list[-1][0]),
            'prev_hour_energy_int': self.power_buffer.integrate(ts_from=ts_from-3600, ts_to=ts_from)/3600
        }

        return ret
