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
    def __init__(self, log_dir='.'):
        self.power_buffer = FloatTimeBuffer(age=7*3600, backup_filename=str(Path(log_dir) / 'power_buffer.yaml'))
        self.energy_buffer = FloatTimeBuffer(age=24*3600*32, backup_filename=str(Path(log_dir) / 'energy_buffer.yaml'))

    def insert_power(self, ts, value):
        self.power_buffer.insert_sorted(ts=ts, value=value)

    def insert_energy(self, ts, value):
        self.energy_buffer.insert_sorted(ts=ts, value=value)

    def monthly_status(self, max_power, ts=None):
        if ts is None:
            ts = int(time.time())
        else:
            ts = int(ts)

        (ts_from, ts_to) = epoch_to_month_ts(ts)
        return [0,0,0]

    def period_status(self, max_energy, ts=None, duration=3600):
        if ts is None:
            ts = int(time.time())
        else:
            ts = int(ts)

        ts_from = duration*int(ts/duration)
        ts_to = ts_from + duration
        energy = self.power_buffer.integrate(ts_from=ts_from, ts_to=ts)/3600
        remaining_time = max(ts_to - ts, 1)     # Minimmum value 1 to avoid /0
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
            'power_avg_1m': power_avg_1m,
            'power_avg_5m': power_avg_5m,
            'energy': energy,
            'max_energy': max_energy,
            'remaining_energy': max_energy - energy,
            'remaining_time': remaining_time,
            'remaining_max_power': 3600*(max_energy - energy)/remaining_time,
            'estimated_energy': energy + power_avg_1m*remaining_time/3600,
            'prev_hour_energy': 1000*self.energy_buffer.get_value(ts=int(time.time())) - \
                1000*self.energy_buffer.get_value(ts=int(time.time()-3600), selection='pre'),
            'prev_hour_energy_int': self.power_buffer.integrate(ts_from=ts_from-3600, ts_to=ts_from)/3600
        }

        return ret
