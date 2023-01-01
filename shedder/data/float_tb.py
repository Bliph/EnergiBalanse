from operator import itemgetter
import copy
from .timebuffer import TimeBuffer

class FloatTimeBuffer(TimeBuffer):

    def __init__(self, age=-1, backup_filename=None, accumulated=False):
        TimeBuffer.__init__(self, age, backup_filename)
        self.accumulated=accumulated

    #################################################################
    # Get value
    # * 'inter'
    # * 'pre'
    # * 'post'
    # * 'avg'
    #
    def get_value(self, ts: int, selection='inter'):

        # Empty: Default to 0
        if len(self.sorted_list) <= 0:
            return 0
        
        idx = self.get_index(ts=ts)

        # Last value: Return last value
        if idx >= len(self.sorted_list):
            return self.sorted_list[len(self.sorted_list)-1][1]
        
        # First value: Return first value
        elif idx <= 0:
            return self.sorted_list[0][1]

        # Spot on
        elif self.sorted_list[idx][0] == ts:
            return self.sorted_list[idx][1]
     
        # Get index of values for idx-1 and idx+1
        pre_idx = max(0, idx-1)
        post_idx = min(idx, len(self.sorted_list)-1)

        pre = self.sorted_list[pre_idx]
        post = self.sorted_list[post_idx]

        if selection.lower() == 'pre':
            return pre[1]
        elif selection.lower() == 'post':
            return post[1]
        elif selection.lower() == 'avg':
            return (post[1]+pre[1])/2
        elif selection.lower() == 'inter':
            dt = post[0]-pre[0]
            dv = post[1]-pre[1]
            if dt == 0:
                return pre[1]
            else:
                return pre[1] + dv*(ts-pre[0])/dt
        else:
            return 0

    #################################################################
    # Integrate value over time
    #
    def integrate(self, ts_from: int, ts_to: int):

        if len(self.sorted_list) <= 0:
            return 0

        sum = 0
            
        if self.accumulated:
            pre_value = self.get_value(ts=ts_from, selection='inter')
            post_value = self.get_value(ts=ts_to, selection='inter')
            sum = post_value-pre_value
        else:
            idx_from = self.get_index(ts=ts_from, valid_read_index=True)
            idx_to = self.get_index(ts=ts_to, valid_read_index=True)
            
            # End point not at ts
            if self.sorted_list[idx_to][0] > ts_to:
                idx_to = max(idx_from, idx_to-1)

            pre_value = self.get_value(ts=ts_from, selection='pre')
            post_value = self.get_value(ts=ts_to, selection='pre')

            for idx in range(idx_from, idx_to):
                sum += self.sorted_list[idx][1] * (self.sorted_list[idx+1][0] - self.sorted_list[idx][0])

            sum += pre_value * (self.sorted_list[idx_from][0] - ts_from)
            sum += post_value * (ts_to - self.sorted_list[idx_to][0])

        return sum

    #################################################################
    # Average value over time
    #
    def avg(self, ts_from: int, ts_to: int):
        
        dt = ts_to - ts_from
        if dt == 0:
            return 0
        else:
            return self.integrate(ts_from=ts_from, ts_to=ts_to)/dt

    #################################################################
    # Max value
    #
    def get_max(self, ts_from: int, ts_to: int):
        measurements = self.get_interval(from_ts=ts_from, to_ts=ts_to)
        if len(measurements) > 0:
            if self.accumulated:
                # for i in range(len(measurements)-1, 0, -1):
                #     measurements[i][1] -= measurements[i-1][1]
                # del measurements[0]
                for i in range(0, len(measurements)-1):
                    measurements[i][1] = measurements[i+1][1] - measurements[i][1]
                del measurements[len(measurements)-1]

            if len(measurements) > 0:
                return max(measurements, key=itemgetter(1))
            else:
                return None
            
        else:
            return None

    #################################################################
    # Min value
    #
    def get_min(self, ts_from: int, ts_to: int):
        measurements = self.get_interval(from_ts=ts_from, to_ts=ts_to)
        if len(measurements) > 0:
            if self.accumulated:
                # for i in range(len(measurements)-1, 0, -1):
                #     measurements[i][1] -= measurements[i-1][1]
                # del measurements[0]
                for i in range(0, len(measurements)-1):
                    measurements[i][1] = measurements[i+1][1] - measurements[i][1]
                del measurements[len(measurements)-1]

            if len(measurements) > 0:
                return min(measurements, key=itemgetter(1))
            else:
                return None
        else:
            return None

    #################################################################
    # Max values over group of values
    #
    def get_period_max_list(self, ts_from: int, ts_to: int, duration=3600*24):
        max_values = []

        for f in range(ts_from, ts_to, duration):
            vm = self.get_max(f, f+duration)
            if vm is not None:
                max_values.append(vm)

        if len(max_values) > 0:
            return sorted(max_values, key=itemgetter(1), reverse=True)
        else:
            return []

    #################################################################
    # Min values over group of values
    #
    def get_period_min_list(self, ts_from: int, ts_to: int, duration=3600*24):
        min_values = []

        for f in range(ts_from, ts_to, duration):
            vm = self.get_min(f, f+duration)
            if vm is not None:
                min_values.append(vm)

        if len(min_values) > 0:
            return sorted(min_values, key=itemgetter(1), reverse=False)
        else:
            return []






if __name__ == '__main__':

    import time
    import random

    a = FloatTimeBuffer() 
    for i in range(10):
        a.insert_sorted(ts = int(random.random()*10), value=int(random.random()*100)) 

    x1 = a.get_value(5.5, 'pre')
    x2 = a.get_value(5.5, 'post')
    x3 = a.get_value(5.5, 'avg')
    x4 = a.get_value(5.5, 'inter')

    a = FloatTimeBuffer() 
    a.insert_sorted(ts=1, value=35) 
    a.insert_sorted(ts=3, value=234) 
    a.insert_sorted(ts=4, value=5) 
    a.insert_sorted(ts=7, value=-5) 
    a.insert_sorted(ts=8, value=70) 
    a.insert_sorted(ts=9, value=71) 

    z1 = a.integrate(3, 8)
    z2 = a.avg(3, 8)

    y0 = a.integrate(0, 3.99)
    y1 = a.integrate(2.5, 8.2)
    y2 = a.avg(2.5, 8.2)
    
    pass

