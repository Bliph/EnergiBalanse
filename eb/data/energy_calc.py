import time
import datetime
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

#####################################################################
# Returns (start, end) of month as timestamps
#
class EnergyCalculator():
    def __init__(self):
        self.power_buffer = FloatTimeBuffer()
        self.energy_buffer = FloatTimeBuffer()
        pass

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

        ret = {
            'ts_from': ts_from,
            'ts_to': ts_to,
            'duration': duration,
            'ts': ts,
            'power': self.power_buffer.get_value(ts=ts, selection='pre'),
            'power_avg_5m': self.power_buffer.avg(ts_from=ts-300, ts_to=ts),
            'energy': energy,
            'max_energy': max_energy,
            'remaining_energy': max_energy - energy,
            'remaining_time': remaining_time,
            'remaining_max_power': 3600*(max_energy - energy)/remaining_time
        }

        return ret
